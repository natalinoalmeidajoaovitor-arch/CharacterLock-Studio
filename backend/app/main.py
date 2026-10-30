"""FastAPI application for a single, trusted local operator."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import logging
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .comfy import ComfyError
from .characters import DEFAULTS, catalog, compose_profile, normalize_attributes
from .character_lab import CharacterLab, router as lab_router
from .db import Database, InstanceLock, encode, now, uid
from .engine_manager import EngineManager
from .model_setup import STUDIO_MODULES, inspect_environment, inspect_models_and_nodes, load_manifest
from .preset_seed import seed_preset_workflows
from .sdk_comfy import SDKComfyClient
from .sdk_proxy import LocalEngineStack, SDKProxyManager
from .jobs import ACTIVE, JobHub, JobWorker, public_job
from .memory_manager import AIModelMemoryManager
from .settings import Settings
from .storage import CATEGORIES, Storage, public_asset, safe_path
from .workflows import WorkflowAdapter, WorkflowError, supported_video_input

MODULE = Literal["character_lab", "video_studio", "motion_swap", "voice"]
MODULES = ("character_lab", "video_studio", "motion_swap", "voice")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CharacterCreate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str = Field(default="", max_length=8000)
    prompt: str = Field(default="", max_length=16000)
    attributes: dict[str, str] | None = None
    consent_confirmed: Literal[True]


class CharacterPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=8000)
    prompt: str | None = Field(default=None, max_length=16000)
    attributes: dict[str, str] | None = None


class PresetCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    parameters: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreate(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    module: MODULE
    workflow: dict[str, Any]
    mapping: dict[str, Any] | None = None


class ValidationRequest(StrictModel):
    parameters: dict[str, Any] | None = None


class JobCreate(StrictModel):
    module: MODULE
    character_id: str
    workflow_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    asset_inputs: dict[str, str | Annotated[list[str], Field(min_length=1, max_length=9)]] = Field(default_factory=dict)
    consent_confirmed: Literal[True]


class EngineStartRequest(StrictModel):
    pass


class BodyTooLarge(HTTPException):
    def __init__(self):
        super().__init__(413, "Request exceeds configured body limit")


class LocalBoundaryMiddleware:
    """Reject DNS rebinding and untrusted browser origins before processing bodies."""
    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in scope.get("headers", [])}
        host = headers.get("host", "")
        try:
            parsed = urlsplit("http://" + host)
            trusted_host = parsed.hostname in {"localhost", "127.0.0.1", "::1"} and not parsed.username and not parsed.password and parsed.path == ""
            _ = parsed.port
        except ValueError:
            trusted_host = False
        origin = headers.get("origin")
        trusted_origin = origin is None or origin in self.settings.allowed_origins
        if not origin and headers.get("sec-fetch-site") == "cross-site":
            trusted_origin = False
        if not trusted_host or not trusted_origin:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                response = JSONResponse({"detail": "Untrusted Host or browser Origin. This server accepts local loopback access only."}, status_code=403)
                await response(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        is_upload = scope.get("method") == "POST" and scope.get("path", "").endswith("/assets")
        limit = self.settings.max_upload_bytes + 1024 * 1024 if is_upload else 16 * 1024 * 1024
        try:
            content_length = int(headers.get("content-length", "0"))
            if content_length < 0:
                raise ValueError()
        except ValueError:
            await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
            return
        if content_length > limit:
            await JSONResponse({"detail": "Request exceeds configured body limit"}, status_code=413)(scope, receive, send)
            return
        consumed, started = 0, False

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    raise BodyTooLarge()
            return message

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, tracked_send)
        except BodyTooLarge:
            if not started:
                await JSONResponse({"detail": "Request exceeds configured body limit"}, status_code=413)(scope, receive, send)


def create_app(settings: Settings | None = None, comfy=None, engine_manager=None, memory_manager=None) -> FastAPI:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.data_dir / "characterlock.sqlite3")
    storage = Storage(settings.data_dir, db, settings.max_upload_bytes)
    client = comfy or SDKComfyClient(settings.comfy_url, settings.comfy_proxy_url, timeout=15, max_output_bytes=settings.max_upload_bytes)
    hub = JobHub()
    memory = memory_manager or (AIModelMemoryManager(client, db, storage.root) if comfy is None else None)
    worker = JobWorker(db, storage, client, hub, settings.poll_seconds, memory_manager=memory)
    lab = CharacterLab(db, storage)
    engine = engine_manager or EngineManager(settings, client)
    if comfy is None and engine_manager is None:
        engine = LocalEngineStack(engine, SDKProxyManager(settings, client))
    lock = InstanceLock(settings.data_dir / ".server.lock")

    @asynccontextmanager
    async def lifespan(app):
        lock.acquire()
        try:
            if comfy is None and settings.seed_presets:
                seed_preset_workflows(db, settings)
            engine.start()
            if settings.start_worker:
                worker.start()
            yield
        finally:
            await worker.close()
            await engine.close()
            await client.close()
            lock.release()

    app = FastAPI(title="CharacterLock Studio", version="1.0.0", description="Local character library and validated ComfyUI execution. One API worker; no simulated generation.", lifespan=lifespan)
    app.state.db, app.state.storage, app.state.comfy = db, storage, client
    app.state.worker, app.state.settings = worker, settings
    app.state.engine = engine
    app.state.lab = lab
    app.state.memory = memory

    @app.get("/api/memory/status")
    async def memory_status():
        return {"enabled": bool(memory), **(memory.status() if memory else {"phase": "disabled_in_test_transport"})}
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "OPTIONS"], allow_headers=["Content-Type"], expose_headers=["Content-Disposition"])
    app.add_middleware(LocalBoundaryMiddleware, settings=settings)

    @app.exception_handler(WorkflowError)
    async def workflow_error(request, exc):
        return JSONResponse({"detail": {"code": exc.code, "message": str(exc), "errors": exc.details}}, status_code=422)

    @app.exception_handler(ComfyError)
    async def comfy_error(request, exc):
        return JSONResponse({"detail": {"code": "comfy_unavailable", "message": str(exc), "details": exc.details}}, status_code=503)

    def character_row(character_id):
        row = db.one("SELECT * FROM characters WHERE id=?", (character_id,))
        if not row:
            raise HTTPException(404, "Character not found")
        return row

    def character_public(row):
        counts = db.one("SELECT COUNT(*) AS count FROM assets WHERE character_id=?", (row["id"],))
        pointers = lab.pointers(row["id"])
        preview = db.one("SELECT id FROM assets WHERE character_id=? AND media_type LIKE 'image/%' ORDER BY CASE WHEN id=? THEN 0 WHEN category='identity' THEN 1 ELSE 2 END,created_at DESC LIMIT 1", (row["id"], pointers["principal_asset_id"]))
        attributes = json.loads(row["attributes"])
        return row | {"attributes": attributes, "attributes_catalog_version": 1 if attributes else None, "consent_confirmed": bool(row["consent_confirmed"]), "asset_count": counts["count"], "preview_asset_id": preview["id"] if preview else None}

    def workflow_row(workflow_id):
        row = db.one("SELECT * FROM workflows WHERE id=?", (workflow_id,))
        if not row:
            raise HTTPException(404, "Workflow not found")
        return row

    def workflow_public(row, include_graph=False):
        inspection = json.loads(row["inspection"])
        result = {k: row[k] for k in ("id", "name", "module", "sha256", "created_at")} | {"format": inspection["format"], "executable": inspection["executable"], "inspection": inspection, "mapping": json.loads(row["mapping"]), "validation": json.loads(row["validation"]) if row["validation"] else None}
        graph = json.loads(row["workflow"])
        result["video_input_parameters"] = [name for name, spec in result["mapping"].get("parameters", {}).items() if supported_video_input(graph, spec)]
        if include_graph:
            result["workflow"] = json.loads(row["workflow"])
        return result

    def job_row(job_id):
        row = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not row:
            raise HTTPException(404, "Job not found")
        return row

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": "1.0.0", "worker": "running" if settings.start_worker else "disabled"}

    @app.get("/api/system")
    async def system():
        stats, info = await asyncio.gather(client.system_stats(), client.object_info(), return_exceptions=True)
        native_connected = EngineManager.responses_ready(stats, info)
        sdk_connected = await client.proxy_health() if isinstance(client, SDKComfyClient) else True
        connected = native_connected and sdk_connected
        error = str(stats) if isinstance(stats, Exception) else str(info) if isinstance(info, Exception) else None
        if connected:
            engine.confirm_ready()
        elif error is None:
            error = "O proxy local do Comfy SDK ainda não está pronto." if native_connected else "O serviço local ainda não respondeu com os dados esperados do ComfyUI."
        capabilities = {}
        rows = db.all("SELECT * FROM workflows ORDER BY created_at DESC")
        for module in MODULES:
            registered = [row for row in rows if row["module"] == module]
            reports = []
            if connected:
                for row in registered:
                    adapter = WorkflowAdapter(json.loads(row["workflow"]), json.loads(row["mapping"]))
                    report = adapter.validate(info)
                    reports.append(report)
            valid_count = sum(report["valid"] for report in reports)
            reason = None if valid_count else engine.snapshot()["message"] if not connected else "Import an API-format workflow and explicit parameter mapping for this module." if not registered else "Registered workflows have validation errors. Validate them against installed ComfyUI nodes and models."
            capabilities[module] = {"available": valid_count > 0, "reason": reason, "workflow_count": len(registered), "validated_count": valid_count}
        states = db.all("SELECT status,COUNT(*) AS count FROM jobs GROUP BY status")
        counts = {row["status"]: row["count"] for row in states}
        return {"comfy": {"connected": connected, "url": settings.comfy_url, "error": error, "lifecycle": engine.snapshot(), "system_stats": stats if not isinstance(stats, Exception) else None, "node_count": len(info) if isinstance(info, dict) else 0,
                          "sdk": {"transport": getattr(client, "transport_name", "native"), "connected": sdk_connected, "proxy_url": settings.comfy_proxy_url if isinstance(client, SDKComfyClient) else None}},
                "capabilities": capabilities, "modules": capabilities, "storage": {"max_upload_bytes": settings.max_upload_bytes, "categories": sorted(CATEGORIES)}, "queue": {"active": sum(counts.get(status, 0) for status in ACTIVE), "queued": counts.get("queued", 0)}, "memory": {"enabled": bool(memory), **(memory.status() if memory else {})}, "limitations": ["Compatibility and local weights are checked against the connected ComfyUI server.", "Image staging and the reviewed VHS_LoadVideo MP4 input are supported; upstream audio input is unavailable.", "LoRA imports are library assets; no files are copied into ComfyUI model directories.", "Progress percentages require real engine events.", "Training, trimming, lip-sync and automatic identity-quality scoring are not implemented."]}

    @app.get("/api/engine/status")
    async def engine_status():
        return engine.snapshot()

    @app.post("/api/engine/start", status_code=202)
    async def engine_start(payload: EngineStartRequest | None = None):
        return engine.request_start()

    @app.get("/api/character-options")
    async def character_options():
        return catalog()

    @app.get("/api/characters")
    async def list_characters():
        return [character_public(row) for row in db.all("SELECT * FROM characters ORDER BY updated_at DESC")]

    @app.post("/api/characters", status_code=201)
    async def create_character(payload: CharacterCreate):
        name = payload.name.strip() if payload.name else ""
        attributes = normalize_attributes(payload.attributes) if payload.attributes is not None else {}
        description, prompt = payload.description, payload.prompt
        if payload.attributes is not None:
            name, description, prompt = compose_profile(attributes, name=name or None)
        if not name:
            raise HTTPException(422, "Selecione um nome artístico ou informe o nome do personagem")
        stamp, character_id = now(), uid()
        db.execute("INSERT INTO characters(id,name,description,prompt,consent_confirmed,created_at,updated_at,attributes) VALUES(?,?,?,?,?,?,?,?)", (character_id, name, description, prompt, 1, stamp, stamp, encode(attributes)))
        row = character_row(character_id)
        storage.character_dirs(character_id)
        storage.profile(row | {"attributes": attributes, "consent_confirmed": True})
        return character_public(row)

    @app.get("/api/characters/{character_id}")
    async def get_character(character_id: str):
        return character_public(character_row(character_id))

    @app.patch("/api/characters/{character_id}")
    async def patch_character(character_id: str, payload: CharacterPatch):
        current = character_row(character_id)
        changes = payload.model_dump(exclude_none=True, exclude={"attributes"})
        if "name" in changes:
            changes["name"] = changes["name"].strip()
            if not changes["name"]:
                raise HTTPException(422, "Character name cannot be blank")
        if payload.attributes is not None:
            existing_attributes = json.loads(current["attributes"])
            attributes = normalize_attributes(payload.attributes, existing=existing_attributes)
            artistic_name_changed = ("artistic_name" in payload.attributes and payload.attributes["artistic_name"] != existing_attributes.get("artistic_name", DEFAULTS["artistic_name"]))
            chosen_name = changes.get("name") or (None if artistic_name_changed else current["name"])
            name, description, prompt = compose_profile(attributes, name=chosen_name)
            changes.update({"name": name, "description": description, "prompt": prompt, "attributes": encode(attributes)})
        if changes:
            assignments = ",".join(f"{field}=?" for field in changes)
            db.execute(f"UPDATE characters SET {assignments},updated_at=? WHERE id=?", (*changes.values(), now(), character_id))
        row = character_row(character_id)
        storage.profile(row | {"attributes": json.loads(row["attributes"]), "consent_confirmed": True})
        return character_public(row)

    @app.get("/api/characters/{character_id}/assets")
    async def list_assets(character_id: str, category: str | None = None):
        character_row(character_id)
        if category is not None and category not in CATEGORIES:
            raise HTTPException(422, "Unsupported asset category")
        rows = db.all("SELECT * FROM assets WHERE character_id=?" + (" AND category=?" if category else "") + " ORDER BY created_at DESC", (character_id, category) if category else (character_id,))
        return [public_asset(row) for row in rows]

    @app.post("/api/characters/{character_id}/assets", status_code=201)
    async def upload_asset(character_id: str, file: UploadFile = File(...), category: str = Form(...), consent_confirmed: bool = Form(False)):
        character_row(character_id)
        if consent_confirmed is not True:
            await file.close()
            raise HTTPException(422, "Confirm authorized use of this identity, image, video or voice before importing")
        return await storage.save_upload(character_id, category, file)

    @app.get("/api/assets/{asset_id}/file")
    async def get_asset_file(asset_id: str):
        row, path = storage.asset_path(asset_id)
        return FileResponse(path, media_type=row["media_type"], filename=row["filename"], content_disposition_type="inline", headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox", "Cache-Control": "no-store"})

    @app.get("/api/characters/{character_id}/presets")
    async def list_presets(character_id: str):
        character_row(character_id)
        return [row | {"parameters": json.loads(row["parameters"])} for row in db.all("SELECT * FROM presets WHERE character_id=? ORDER BY created_at DESC", (character_id,))]

    @app.post("/api/characters/{character_id}/presets", status_code=201)
    async def create_preset(character_id: str, payload: PresetCreate):
        character_row(character_id)
        if not payload.name.strip():
            raise HTTPException(422, "Preset name cannot be blank")
        row = {"id": uid(), "character_id": character_id, "name": payload.name.strip(), "parameters": payload.parameters, "created_at": now()}
        try:
            parameters_json = encode(row["parameters"])
        except ValueError as exc:
            raise HTTPException(422, "Preset parameters must contain finite JSON values") from exc
        db.execute("INSERT INTO presets VALUES(?,?,?,?,?)", (row["id"], character_id, row["name"], parameters_json, row["created_at"]))
        return row

    @app.get("/api/workflows")
    async def list_workflows(module: MODULE | None = None):
        rows = db.all("SELECT * FROM workflows" + (" WHERE module=?" if module else "") + " ORDER BY created_at DESC", (module,) if module else ())
        return [workflow_public(row) for row in rows]

    @app.post("/api/workflows", status_code=201)
    async def import_workflow(payload: WorkflowCreate):
        if not payload.name.strip():
            raise HTTPException(422, "Workflow name cannot be blank")
        if len(payload.workflow) > 10000:
            raise HTTPException(422, "Workflow exceeds 10,000 top-level entries")
        adapter = WorkflowAdapter(payload.workflow, payload.mapping)
        inspection = adapter.inspect()
        workflow_id = uid()
        try:
            original = encode(payload.workflow)
            mapping_json = encode(adapter.mapping)
        except ValueError as exc:
            raise HTTPException(422, "Workflow and mapping must contain finite JSON values") from exc
        mapping = adapter.mapping
        original_path = f"workflows/{workflow_id}/original.json"
        folder = safe_path(settings.data_dir, f"workflows/{workflow_id}")
        folder.mkdir(parents=True, exist_ok=False)
        with (folder / "original.json").open("x", encoding="utf-8") as handle:
            handle.write(original)
        with (folder / "mapping.json").open("x", encoding="utf-8") as handle:
            handle.write(mapping_json)
        db.execute("INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?,?,?)", (workflow_id, payload.name.strip(), payload.module, original, mapping_json, encode(inspection), None, original_path, hashlib.sha256(original.encode("utf-8")).hexdigest(), now()))
        return workflow_public(workflow_row(workflow_id))

    @app.get("/api/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str):
        return workflow_public(workflow_row(workflow_id), include_graph=True)

    @app.post("/api/workflows/{workflow_id}/validate")
    async def validate_workflow(workflow_id: str, payload: ValidationRequest | None = None):
        row = workflow_row(workflow_id)
        adapter = WorkflowAdapter(json.loads(row["workflow"]), json.loads(row["mapping"]))
        info = await client.object_info()
        report = adapter.validate(info, payload.parameters if payload else None)
        report["validated_at"] = now()
        db.execute("UPDATE workflows SET validation=? WHERE id=?", (encode(report), workflow_id))
        return report

    async def enqueue(payload: JobCreate, lab_context=None):
        character_row(payload.character_id)
        if isinstance(client, SDKComfyClient) and not await client.proxy_health():
            raise ComfyError("A conexão local do Comfy SDK está iniciando ou indisponível. Aguarde ou repita a inicialização do motor.")
        row = workflow_row(payload.workflow_id)
        if lab_context is None and db.one("SELECT workflow_id FROM lab_workflows WHERE workflow_id=?", (payload.workflow_id,)):
            raise HTTPException(409, "Use a geração da etapa do Character Lab para resolver identidade, aprovação e referências automaticamente.")
        if payload.module != row["module"]:
            raise HTTPException(422, "Job module must match the registered workflow module")
        adapter = WorkflowAdapter(json.loads(row["workflow"]), json.loads(row["mapping"]))
        if not adapter.inspect()["executable"]:
            raise HTTPException(422, "Only valid ComfyUI API-format prompts can execute. UI workflow exports are inspection-only; export the API format from ComfyUI.")
        specs = adapter.mapping.get("parameters", {})
        if payload.parameters.keys() & payload.asset_inputs.keys():
            raise HTTPException(422, "A parameter cannot be provided both as a scalar value and an asset reference")
        for name in payload.parameters:
            if specs.get(name, {}).get("kind") in {"image", "audio", "video"}:
                raise HTTPException(422, "Media parameters must use asset_inputs with a character-owned asset ID")
        for name, asset_value in payload.asset_inputs.items():
            spec = specs.get(name)
            if not isinstance(spec, dict) or spec.get("kind") not in {"image", "audio", "video"}:
                raise HTTPException(422, f"Asset input '{name}' is not an explicitly mapped media parameter")
            if isinstance(asset_value, list) and spec.get("serializer") != "h3_media_state":
                raise HTTPException(422, "Multiple image references require the explicitly mapped H3 media serializer")
            for asset_id in asset_value if isinstance(asset_value, list) else [asset_value]:
                asset = storage.asset(asset_id)
                if asset["character_id"] != payload.character_id:
                    raise HTTPException(422, "Asset inputs must belong to the selected character")
                video = supported_video_input(adapter.workflow, spec)
                if video:
                    if isinstance(asset_value, list) or asset["media_type"] != "video/mp4" or Path(asset["relative_path"]).suffix.lower() != ".mp4":
                        raise HTTPException(422, "The reviewed VHS video input requires one character-owned MP4.")
                elif spec.get("kind") != "image" or not asset["media_type"].startswith("image/"):
                    raise HTTPException(422, "Only mapped images or the reviewed VHS_LoadVideo MP4 input can be staged. Audio input is unsupported.")
                elif asset["media_type"] not in {"image/png", "image/jpeg", "image/webp"}:
                    raise HTTPException(422, "ComfyUI image staging accepts PNG, JPEG and WEBP references. Convert this library image before using it as an input.")
                storage.asset_path(asset_id)
        parameter_report = adapter.validate_parameters(payload.parameters, allow_missing=set(payload.asset_inputs))
        if not parameter_report["valid"]:
            raise WorkflowError("Job parameter validation failed", details=parameter_report["errors"])
        info = await client.object_info()
        report = adapter.validate(info, payload.parameters, allow_missing=set(payload.asset_inputs))
        if not report["valid"]:
            raise WorkflowError("Workflow is not compatible with installed ComfyUI nodes or models", details=report["errors"])
        if not payload.asset_inputs:
            adapter.build(payload.parameters, info)
        job_id, stamp = uid(), now()
        with db.connect() as conn:
            conn.execute("INSERT INTO jobs(id,module,character_id,workflow_id,status,parameters,asset_inputs,client_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (job_id, payload.module, payload.character_id, payload.workflow_id, "queued", encode(payload.parameters), encode(payload.asset_inputs), uid(), stamp, stamp))
            if lab_context is not None:
                conn.execute("INSERT INTO lab_jobs VALUES(?,?,?,?,?,?)", (job_id, payload.character_id, lab_context["stage"], lab_context["revision_id"], encode(lab_context), stamp))
        db.transition(job_id, "queued", detail={"message": "Validated job queued; no generation has been simulated"})
        worker.notify(job_id)
        worker.wake.set()
        return public_job(db, job_row(job_id))

    @app.get("/api/jobs")
    async def list_jobs(character_id: str | None = None, limit: int = 100):
        if not 1 <= limit <= 500:
            raise HTTPException(422, "limit must be between 1 and 500")
        rows = db.all("SELECT * FROM jobs" + (" WHERE character_id=?" if character_id else "") + " ORDER BY created_at DESC LIMIT ?", (character_id, limit) if character_id else (limit,))
        return [public_job(db, row) for row in rows]

    @app.post("/api/jobs", status_code=202)
    async def create_job(payload: JobCreate):
        return await enqueue(payload)

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        result = public_job(db, job_row(job_id))
        result["events"] = [row | {"detail": json.loads(row["detail"]) if row["detail"] else None} for row in db.all("SELECT status,detail,created_at FROM job_events WHERE job_id=? ORDER BY id", (job_id,))]
        return result

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        job_row(job_id)
        if not worker.transition(job_id, "cancelled", allowed={"queued"}, detail={"message": "Cancelled before preparation; ComfyUI was not interrupted"}):
            raise HTTPException(409, "Only queued jobs can be cancelled. Running jobs keep their prompt ID; this application never sends a global interrupt.")
        return public_job(db, job_row(job_id))

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    async def retry_job(job_id: str):
        row = job_row(job_id)
        if row["status"] not in {"failed", "cancelled", "succeeded"}:
            raise HTTPException(409, "Retry is allowed only for confirmed terminal jobs. Ambiguous or active submissions must be inspected in ComfyUI.")
        if row["prompt_id"]:
            history = await client.history(row["prompt_id"])
            entry = worker.history_entry(history, row["prompt_id"])
            status = entry.get("status", {}) if entry else {}
            if not (status.get("completed") is True or status.get("status_str") in {"success", "error"}):
                raise HTTPException(409, "The previous prompt's terminal history is no longer available. Inspect ComfyUI before creating a new job.")
        previous_lab = db.one("SELECT context FROM lab_jobs WHERE job_id=?", (job_id,))
        return await enqueue(JobCreate(module=row["module"], character_id=row["character_id"], workflow_id=row["workflow_id"], parameters=json.loads(row["parameters"]), asset_inputs=json.loads(row["asset_inputs"]), consent_confirmed=True), json.loads(previous_lab["context"]) if previous_lab else None)

    async def enqueue_lab(payload, context):
        return await enqueue(JobCreate(**payload), context)

    app.include_router(lab_router(lab, client, enqueue_lab))

    @app.get("/api/setup/environment")
    async def setup_environment():
        return inspect_environment(settings.app_root, settings.comfyui_dir)

    @app.get("/api/setup/models")
    async def setup_models(modules: str | None = None):
        manifest = load_manifest(settings.app_root)
        selected = None
        if modules:
            selected = [m.strip() for m in modules.split(",") if m.strip() in STUDIO_MODULES]
            if not selected:
                raise HTTPException(422, f"Unsupported module filter; choose from {', '.join(STUDIO_MODULES)}")
        return inspect_models_and_nodes(manifest, settings.comfyui_dir, selected)

    @app.post("/api/setup/seed-workflows")
    async def setup_seed_workflows():
        return seed_preset_workflows(db, settings)

    @app.websocket("/api/ws/jobs")
    async def job_updates(websocket: WebSocket):
        await websocket.accept()
        queue = hub.subscribe()
        try:
            await websocket.send_json({"type": "snapshot", "jobs": [public_job(db, row) for row in db.all("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100")]})
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=25)
                except asyncio.TimeoutError:
                    message = {"type": "heartbeat"}
                await websocket.send_json(message)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.listeners.discard(queue)

    frontend_dist = settings.app_root / "frontend" / "dist"
    index_html = frontend_dist / "index.html"
    if index_html.is_file():
        assets_dir = frontend_dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

        @app.get("/", include_in_schema=False)
        async def serve_spa_root():
            return FileResponse(index_html)

    return app


app = create_app()

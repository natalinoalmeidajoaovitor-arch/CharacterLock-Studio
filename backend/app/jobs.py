"""One durable, sequential queue. Ambiguous submissions are never replayed."""
import asyncio
from contextlib import suppress
import json
import logging
from pathlib import Path

from .comfy import ComfyError
from .character_lab import CharacterLab, PHYSICAL_CATEGORIES, lab_output
from .db import Database, encode, now, uid
from .storage import public_asset, safe_path
from .workflows import WorkflowAdapter, WorkflowError, supported_video_input

log = logging.getLogger("characterlock.jobs")
TERMINAL = {"succeeded", "failed", "cancelled", "needs_attention"}
ACTIVE = {"preparing", "submitting", "running"}


def public_job(db: Database, row: dict) -> dict:
    job = {k: row[k] for k in ("id", "module", "character_id", "workflow_id", "status", "prompt_id", "created_at", "updated_at")}
    for key in ("parameters", "asset_inputs", "progress", "error"):
        job[key] = json.loads(row[key]) if row[key] else None
    job["output_assets"] = [public_asset(asset) for asset_id in json.loads(row["output_assets"]) if (asset := db.one("SELECT * FROM assets WHERE id=?", (asset_id,)))]
    detail = {}
    for event in db.all("SELECT detail FROM job_events WHERE job_id=? ORDER BY id DESC LIMIT 20", (row["id"],)):
        candidate = json.loads(event["detail"]) if event["detail"] else {}
        if isinstance(candidate, dict) and isinstance(candidate.get("message"), str):
            detail = candidate
            break
    job["result_message"] = detail.get("message") if row["status"] == "succeeded" and isinstance(detail, dict) else None
    context = db.one("SELECT context FROM lab_jobs WHERE job_id=?", (row["id"],))
    job["lab_context"] = json.loads(context["context"]) if context else None
    return job


class JobHub:
    def __init__(self):
        self.listeners: set[asyncio.Queue] = set()

    def subscribe(self):
        queue = asyncio.Queue(maxsize=100)
        self.listeners.add(queue)
        return queue

    def publish(self, message):
        for queue in list(self.listeners):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(message)


class JobWorker:
    def __init__(self, db, storage, comfy, hub, poll_seconds=2.0, memory_manager=None):
        self.db, self.storage, self.comfy, self.hub = db, storage, comfy, hub
        self.poll_seconds = poll_seconds
        self.wake = asyncio.Event()
        self.task = None
        self.memory_manager = memory_manager
        if memory_manager:
            memory_manager.notify = self.notify

    def notify(self, job_id):
        row = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if row:
            self.hub.publish({"type": "job", "job": public_job(self.db, row)})

    def transition(self, job_id, status, **kwargs):
        result = self.db.transition(job_id, status, **kwargs)
        if result:
            self.notify(job_id)
        return result

    def update_progress(self, job_id, progress, *, snapshot=False):
        """Persist and publish observed changes without inventing a percentage."""
        row = self.db.one("SELECT status,progress FROM jobs WHERE id=?", (job_id,))
        if not row or row["status"] != "running":
            return
        previous = json.loads(row["progress"]) if row["progress"] else {}
        progress = progress if snapshot else previous | progress
        if progress == previous:
            return
        if self.db.execute("UPDATE jobs SET progress=?,updated_at=? WHERE id=? AND status='running'", (encode(progress), now(), job_id)):
            self.notify(job_id)

    def observation_phase(self, job_id, phase, message, **extra):
        row = self.db.one("SELECT progress FROM jobs WHERE id=?", (job_id,))
        previous = json.loads(row["progress"]) if row and row["progress"] else {}
        # A poll without sampler counters must not erase a newer live event.
        if previous.get("phase") != phase or any(previous.get(key) != value for key, value in extra.items()):
            self.update_progress(job_id, {"phase": phase, "message": message, **extra})

    def start(self):
        # Preparing has not crossed the submission boundary, so it is safe to requeue.
        for row in self.db.all("SELECT * FROM jobs WHERE status IN ('preparing','submitting','running')"):
            if row["prompt_id"]:
                self.db.transition(row["id"], "running", detail={"message": "Resuming observation of persisted ComfyUI prompt ID"})
            elif row["status"] == "preparing":
                self.db.transition(row["id"], "queued", detail={"message": "Preparation interrupted before submission; safe to requeue"})
            else:
                self.db.transition(row["id"], "needs_attention", error={"code": "submission_unknown", "message": "The server stopped during submission. Check ComfyUI history before creating another generation; this job will not be replayed."})
        self.task = asyncio.create_task(self.run(), name="characterlock-sequential-queue")

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task

    async def run(self):
        while True:
            try:
                active = self.db.one("SELECT * FROM jobs WHERE status='running' ORDER BY created_at LIMIT 1")
                if active:
                    if self.memory_manager:
                        async with self.memory_manager.execution(active["id"], resumed=True):
                            try:
                                await self.observe(active, resumed=True)
                            finally:
                                await self.memory_manager.finish(active["id"], self.db.one("SELECT * FROM jobs WHERE id=?", (active["id"],)))
                    else:
                        await self.observe(active, resumed=True)
                    continue
                row = self.db.one("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1")
                if row:
                    await self.execute(row)
                    continue
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=self.poll_seconds)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Unexpected queue loop failure; preserving durable states")
                await asyncio.sleep(self.poll_seconds)

    async def execute(self, row):
        if self.memory_manager:
            async with self.memory_manager.execution(row["id"]):
                try:
                    await self._execute(row)
                finally:
                    await self.memory_manager.finish(row["id"], self.db.one("SELECT * FROM jobs WHERE id=?", (row["id"],)))
        else:
            await self._execute(row)

    async def _execute(self, row):
        job_id, stage = row["id"], "preparing"
        if not self.transition(job_id, "preparing", allowed={"queued"}):
            return
        try:
            workflow = self.db.one("SELECT * FROM workflows WHERE id=?", (row["workflow_id"],))
            adapter = WorkflowAdapter(json.loads(workflow["workflow"]), json.loads(workflow["mapping"]))
            parameters = json.loads(row["parameters"])
            asset_inputs = json.loads(row["asset_inputs"])
            info = await self.comfy.object_info()
            report = adapter.validate(info, parameters, allow_missing=set(asset_inputs))
            if not report["valid"]:
                raise WorkflowError("Workflow validation failed", details=report["errors"], code="validation_failed")
            uploaded_assets = {}
            specs = adapter.mapping.get("parameters", {})
            for name, asset_value in asset_inputs.items():
                spec = specs.get(name, {})
                serialized = spec.get("serializer") == "h3_media_state"
                video = supported_video_input(adapter.workflow, spec)
                asset_ids = asset_value if isinstance(asset_value, list) else [asset_value]
                if (spec.get("kind") != "image" and not video or not 1 <= len(asset_ids) <= 9
                        or isinstance(asset_value, list) and not serialized):
                    raise WorkflowError("Asset lists require an explicitly mapped H3 image serializer", code="unsupported_asset_input")
                filenames = []
                for asset_id in asset_ids:
                    asset, path = self.storage.asset_path(asset_id)
                    media_valid = asset["media_type"] == "video/mp4" and path.suffix.lower() == ".mp4" if video else asset["media_type"] in {"image/png", "image/jpeg", "image/webp"}
                    if asset["character_id"] != row["character_id"] or not media_valid:
                        raise WorkflowError("The mapped input requires a character-owned supported image or reviewed VHS MP4", code="unsupported_asset_input")
                    if asset_id not in uploaded_assets:
                        uploaded = await self.comfy.upload_file(path)
                        filename, subfolder = uploaded.get("name"), uploaded.get("subfolder", "")
                        if not isinstance(filename, str) or not filename or not isinstance(subfolder, str):
                            raise ComfyError("ComfyUI did not return an uploaded image filename")
                        filename = f"{subfolder}/{filename}" if subfolder else filename
                        if ("\x00" in filename or ":" in filename or filename.startswith(("/", "\\"))
                                or ".." in filename.replace("\\", "/").split("/") or "[" in filename or "]" in filename):
                            raise ComfyError("ComfyUI returned an unsafe uploaded image filename")
                        uploaded_assets[asset_id] = filename
                    filenames.append(uploaded_assets[asset_id])
                parameters[name] = encode([{"kind": "picture", "file": filename, "enabled": True} for filename in filenames]) if serialized else filenames[0]
            if asset_inputs:
                info = await self.comfy.object_info()
            prompt = adapter.build(parameters, info)
            if self.memory_manager:
                await self.memory_manager.prepare(job_id, prompt, adapter.mapping.get("output_nodes"), info)
            execution_dir = safe_path(self.storage.root, f"jobs/{job_id}")
            execution_dir.mkdir(parents=True, exist_ok=True)
            # Each job is a new immutable execution, including resolved upstream asset names.
            # Preparation can safely restart; only the snapshot committed at submission is executed.
            with (execution_dir / "prompt.pending").open("w", encoding="utf-8") as handle:
                handle.write(encode(prompt))
            (execution_dir / "prompt.pending").replace(execution_dir / "prompt.json")
            context = self.db.one("SELECT context FROM lab_jobs WHERE job_id=?", (job_id,))
            with (execution_dir / "request.json").open("w", encoding="utf-8") as handle:
                handle.write(encode({"workflow_id": row["workflow_id"], "module": row["module"], "character_id": row["character_id"], "parameters": json.loads(row["parameters"]), "asset_inputs": asset_inputs, "lab_context": json.loads(context["context"]) if context else None}))
            # Commit this boundary BEFORE the request. A crash here is intentionally ambiguous.
            self.transition(job_id, "submitting", allowed={"preparing"}, detail={"message": "Submitting validated prompt to ComfyUI"})
            stage = "submitting"
            submitted = await self.comfy.submit(prompt, client_id=row["client_id"])
            prompt_id = submitted.get("prompt_id")
            if not isinstance(prompt_id, str) or not prompt_id:
                raise ComfyError("ComfyUI response omitted prompt_id; submission outcome is unknown")
            self.transition(job_id, "running", allowed={"submitting"}, prompt_id=prompt_id, detail={"prompt_id": prompt_id, "transport": submitted.get("transport", "native")})
            await self.observe(self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,)), resumed=False)
        except asyncio.CancelledError:
            # The persisted phase is reconciled on restart; do not hide an in-flight submission.
            raise
        except Exception as exc:
            current = self.db.one("SELECT status FROM jobs WHERE id=?", (job_id,))
            if current and current["status"] in TERMINAL:
                return
            rejected = isinstance(exc, ComfyError) and isinstance(exc.details, dict) and exc.details.get("submission_uncertain") is False
            if stage == "submitting" and not rejected:
                self.transition(job_id, "needs_attention", error={"code": "submission_unknown", "message": "Submission outcome could not be confirmed. Inspect ComfyUI before starting another copy.", "details": str(exc)})
            else:
                self.transition(job_id, "failed", error={"code": getattr(exc, "code", "preparation_failed"), "message": str(exc), "details": getattr(exc, "details", None)})
            log.warning("Job %s stopped in %s: %s", job_id, stage, exc)

    @staticmethod
    def history_entry(history, prompt_id):
        if not isinstance(history, dict):
            return None
        if prompt_id in history:
            return history[prompt_id]
        return history if "outputs" in history or "status" in history else None

    @staticmethod
    def queue_contains(queue, prompt_id):
        for key in ("queue_running", "queue_pending"):
            for item in queue.get(key, []):
                if isinstance(item, (list, tuple)) and len(item) > 1 and item[1] == prompt_id:
                    return True
        return False

    async def observe(self, row, resumed=False):
        events = getattr(self.comfy, "progress_events", None)
        stream = asyncio.create_task(self.observe_progress(row)) if callable(events) else None
        try:
            await self.observe_history(row, resumed)
        finally:
            if stream:
                stream.cancel()
                with suppress(asyncio.CancelledError):
                    await stream

    async def observe_progress(self, row):
        try:
            async for progress in self.comfy.progress_events(row["prompt_id"]):
                self.update_progress(row["id"], progress, snapshot="value" in progress)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # The optional stream cannot block the durable poll/queue path.
            log.warning("Live progress unavailable for job %s; continuing observation: %s", row["id"], exc)

    async def observe_history(self, row, resumed=False):
        job_id, prompt_id = row["id"], row["prompt_id"]
        missing = 0
        while True:
            try:
                history = await self.comfy.history(prompt_id)
                entry = self.history_entry(history, prompt_id)
                if entry:
                    status = entry.get("status", {})
                    messages = status.get("messages", [])
                    failed = status.get("status_str") == "error" or any(isinstance(message, (list, tuple)) and message and message[0] in {"execution_error", "execution_interrupted"} for message in messages)
                    if failed:
                        self.save_history(row, entry)
                        self.transition(job_id, "failed", error={"code": "comfy_execution_failed", "message": "ComfyUI reported an execution failure", "details": messages}, detail={"upstream_status": status})
                        return
                    completed = status.get("completed") is True or status.get("status_str") == "success"
                    if completed:
                        self.observation_phase(job_id, "saving_outputs", "Geração concluída; salvando os arquivos na biblioteca.")
                        await self.save_outputs(row, entry)
                        return
                queue = await self.comfy.queue()
                if self.queue_contains(queue, prompt_id):
                    missing = 0
                    pending = [item[1] for item in queue.get("queue_pending", []) if isinstance(item, (list, tuple)) and len(item) > 1]
                    if prompt_id in pending:
                        self.observation_phase(job_id, "queued", "Aguardando a fila do ComfyUI.", queue_position=pending.index(prompt_id) + 1)
                    else:
                        self.observation_phase(job_id, "running", "ComfyUI está processando a geração.", queue_position=None)
                else:
                    missing += 1
                    if missing >= (2 if resumed else 4):
                        self.transition(job_id, "needs_attention", error={"code": "prompt_not_found", "message": "The saved prompt ID is absent from ComfyUI queue and completed history. It may have been cleared; it will not be resubmitted."})
                        return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Connection loss is not evidence that a GPU job stopped.
                log.warning("Cannot observe job %s; retaining prompt ID: %s", job_id, exc)
                self.observation_phase(job_id, "reconnecting", "Conexão com o ComfyUI interrompida; aguardando reconexão sem reenviar a geração.")
            await asyncio.sleep(self.poll_seconds)

    def save_history(self, row, entry):
        execution_dir = safe_path(self.storage.root, f"jobs/{row['id']}")
        execution_dir.mkdir(parents=True, exist_ok=True)
        history_path = execution_dir / "history.json"
        if not history_path.exists():
            with history_path.open("x", encoding="utf-8") as handle:
                handle.write(encode(entry))

    async def save_outputs(self, row, entry):
        self.save_history(row, entry)
        workflow = self.db.one("SELECT mapping FROM workflows WHERE id=?", (row["workflow_id"],))
        selected_outputs = set(json.loads(workflow["mapping"]).get("output_nodes", []))
        existing_ids = json.loads(self.db.one("SELECT output_assets FROM jobs WHERE id=?", (row["id"],))["output_assets"])
        existing_keys = {json.loads(asset["metadata"]).get("comfy_output_key") for asset_id in existing_ids if (asset := self.db.one("SELECT metadata FROM assets WHERE id=?", (asset_id,)))}
        output_ids = list(existing_ids)
        try:
            seen = set()
            for node_id, node_output in entry.get("outputs", {}).items():
                if selected_outputs and str(node_id) not in selected_outputs:
                    continue
                if not isinstance(node_output, dict):
                    continue
                for group, items in node_output.items():
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        if not isinstance(item, dict) or not isinstance(item.get("filename"), str):
                            continue
                        if item.get("type", "output") not in {"output", "temp"}:
                            continue
                        descriptor_key = [node_id, item["filename"], item.get("subfolder", ""), item.get("type", "output")]
                        if item.get("sdk_asset_id"):
                            descriptor_key.append(item["sdk_asset_id"])
                        key = encode(descriptor_key)
                        if key in seen or key in existing_keys:
                            continue
                        seen.add(key)
                        content = await self.comfy.download_output(item)
                        if len(content) > self.storage.max_bytes:
                            raise ValueError("Generated file exceeds configured storage size limit")
                        ext = Path(item["filename"]).suffix.lower()
                        category = "audio" if ext in {".mp3", ".wav", ".flac", ".ogg", ".m4a"} else "videos" if ext in {".mp4", ".mov", ".webm"} else "identity"
                        lab_metadata = lab_output(self.db, row["id"], str(node_id))
                        if lab_metadata:
                            if category in {"audio", "videos"}:
                                raise ValueError("Character Lab image workflow returned unsupported audio/video media")
                            category = PHYSICAL_CATEGORIES[lab_metadata["stage"]]
                        temporary = self.storage.root / "tmp" / f"{uid()}.part"
                        registered_asset = None
                        try:
                            temporary.write_bytes(content)
                            metadata = {"job_id": row["id"], "workflow_id": row["workflow_id"], "prompt_id": row["prompt_id"], "comfy_output_key": key, "node_id": str(node_id), "output_group": group}
                            if lab_metadata:
                                metadata["lab"] = lab_metadata
                                metadata["parameters"] = json.loads(row["parameters"])
                                metadata["reference_asset_ids"] = json.loads(row["asset_inputs"])
                            # Register the asset, Lab provenance and recovery
                            # checkpoint atomically. A restart cannot observe a
                            # registered output without its identity revision.
                            with self.db.connect() as conn:
                                asset = self.storage.register(temporary, row["character_id"], category, item["filename"], metadata=metadata, connection=conn)
                                registered_asset = asset
                                if lab_metadata:
                                    CharacterLab(self.db, self.storage).write_asset(lab_metadata | {"asset_id": asset["id"], "character_id": row["character_id"]}, conn)
                                next_ids = output_ids + [asset["id"]]
                                conn.execute("UPDATE jobs SET output_assets=?,updated_at=? WHERE id=?", (encode(next_ids), now(), row["id"]))
                            output_ids = next_ids
                        except BaseException:
                            # The file is moved before the SQLite transaction;
                            # remove it only after proving its row rolled back.
                            if registered_asset and not self.db.one("SELECT id FROM assets WHERE id=?", (registered_asset["id"],)):
                                orphan = safe_path(self.storage.root, f"characters/{row['character_id']}/{category}/{registered_asset['id']}{Path(item['filename']).suffix.lower()}")
                                # Decoded format can normalize .jpeg to .jpg.
                                for path in orphan.parent.glob(registered_asset["id"] + ".*"):
                                    path.unlink(missing_ok=True)
                            raise
                        finally:
                            temporary.unlink(missing_ok=True)
            self.transition(row["id"], "succeeded", outputs=output_ids, detail={"output_count": len(output_ids), "code": "completed" if output_ids else "completion_without_media", "message": "ComfyUI completed; supported output media copied to character library" if output_ids else "ComfyUI completed but selected output nodes returned no supported media descriptors. Inspect the saved history."})
        except Exception as exc:
            self.transition(row["id"], "needs_attention", outputs=output_ids, error={"code": "output_download_failed", "message": "ComfyUI completed, but some output media could not be saved. Keep the ComfyUI outputs and inspect this job before rerunning.", "details": str(exc)})

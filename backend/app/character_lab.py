"""Additive Character Lab orchestration; workflows are explicitly bound, never guessed.

The existing asset rows/files and sequential SDK worker remain authoritative. Lab
tables add approvals, revision pointers and immutable generation provenance.
"""
import json
from string import Formatter
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .db import encode, now, uid
from .workflows import WorkflowAdapter, WorkflowError

STAGES = ("character_sheet", "dataset", "outfits", "references")
Stage = Literal["character_sheet", "dataset", "outfits", "references"]
Role = Literal["sheet", "sheet_face", "sheet_upper_bundle", "sheet_full_bundle", "dataset", "outfit", "optional_reference", "garment"]
SHEET_ANCHORS = ("face", "upper_body", "full_body")
SHEET_COMPANIONS = {*SHEET_ANCHORS, "side", "back", "face_three_quarter", "face_profile", "body_three_quarter", "pose_a", "pose_hands_on_hips"}
SHEET_ROLES = {"sheet", "sheet_face", "sheet_upper_bundle", "sheet_full_bundle"}
LOGICAL_CATEGORIES = {
    "character_sheet": {"character_sheet", "character_sheets", "identity", *SHEET_COMPANIONS},
    "dataset": {"dataset", "face", "body", "angles", "expressions", "poses", "identity"},
    "outfits": {"outfit", "outfits"},
    "references": {"reference", "references"},
}
PHYSICAL_CATEGORIES = {"character_sheet": "character_sheets", "dataset": "dataset", "outfits": "outfits", "references": "references"}
LEGACY_STAGES = {"identity": "character_sheet", "character_sheets": "character_sheet", "dataset": "dataset", "expressions": "dataset", "poses": "dataset", "outfits": "outfits", "references": "references"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowBinding(StrictModel):
    workflow_id: str
    stage: Stage
    prompt_parameter: str | None = None
    steps_parameter: str | None = None
    reference_parameters: dict[str, Role] = Field(default_factory=dict)
    output_categories: dict[str, str]
    prompt_template: str | None = Field(default=None, max_length=24000)


class AssetPatch(StrictModel):
    approval: Literal["pending", "approved", "rejected"] | None = None
    priority: bool | None = None
    stage: Stage | None = None
    category: str | None = None
    outfit_name: str | None = Field(default=None, max_length=160)


class AssetSelection(StrictModel):
    asset_id: str


class GenerateRequest(StrictModel):
    stage: Stage
    workflow_id: str
    steps: int | None = Field(default=None, strict=True, ge=1, le=10000)
    prompt_text: str | None = Field(default=None, max_length=16000)
    outfit_name: str | None = Field(default=None, max_length=160)
    reference_asset_id: str | None = None
    garment_asset_id: str | None = None
    outfit_asset_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    consent_confirmed: Literal[True]


def category_for(stage, category):
    if category not in LOGICAL_CATEGORIES[stage]:
        raise HTTPException(422, f"Categoria incompatível com a etapa {stage}.")
    return "character_sheet" if stage == "character_sheet" and category in {"character_sheet", "character_sheets", "identity"} else "outfits" if stage == "outfits" else "references" if stage == "references" else category


class CharacterLab:
    def __init__(self, db, storage):
        self.db, self.storage = db, storage

    def character(self, character_id):
        row = self.db.one("SELECT * FROM characters WHERE id=?", (character_id,))
        if not row:
            raise HTTPException(404, "Character not found")
        return row

    def pointers(self, character_id):
        return self.db.one("SELECT * FROM lab_characters WHERE character_id=?", (character_id,)) or {
            "character_id": character_id, "active_revision_id": None, "principal_asset_id": None, "default_outfit_asset_id": None}

    def image(self, character_id, asset_id):
        row, _ = self.storage.asset_path(asset_id)
        if row["character_id"] != character_id:
            raise HTTPException(422, "A referência deve pertencer à personagem selecionada.")
        if row["media_type"] not in {"image/png", "image/jpeg", "image/webp"}:
            raise HTTPException(422, "Use uma imagem PNG, JPEG ou WEBP desta personagem.")
        return row

    def asset_metadata(self, row):
        explicit = self.db.one("SELECT * FROM lab_assets WHERE asset_id=?", (row["id"],))
        if explicit:
            return explicit
        saved = json.loads(row["metadata"]).get("lab")
        if saved:
            return saved | {"asset_id": row["id"], "character_id": row["character_id"]}
        stage = LEGACY_STAGES.get(row["category"])
        if not stage or not row["media_type"].startswith("image/"):
            return None
        # Read-only logical migration: old filenames, rows, categories and files
        # are left untouched. No legacy image is silently approved as a sheet.
        return {"asset_id": row["id"], "character_id": row["character_id"], "stage": stage,
                "category": category_for(stage, row["category"]), "approval": "pending", "priority": 0,
                "revision_id": None, "legacy": 1, "outfit_name": None,
                "job_id": json.loads(row["metadata"]).get("job_id")}

    def assets(self, character_id):
        result = []
        for row in self.db.all("SELECT * FROM assets WHERE character_id=? ORDER BY created_at DESC,id", (character_id,)):
            meta = self.asset_metadata(row)
            if meta:
                result.append(meta | {"priority": bool(meta["priority"]), "legacy": bool(meta["legacy"])})
        return result

    def sync_profile(self, character_id):
        row = self.character(character_id)
        self.storage.profile(row | {"attributes": json.loads(row["attributes"]), "consent_confirmed": True})

    def state(self, character_id):
        self.character(character_id)
        pointers = self.pointers(character_id)
        assets = self.assets(character_id)
        current = pointers["active_revision_id"]
        sheet_ok = bool(current and pointers["principal_asset_id"])
        if sheet_ok:
            try:
                self.image(character_id, pointers["principal_asset_id"])
            except HTTPException:
                sheet_ok = False
        approved_dataset = [a for a in assets if a["stage"] == "dataset" and a["approval"] == "approved" and a["revision_id"] == current]
        usable_dataset = []
        for asset in approved_dataset:
            try:
                self.image(character_id, asset["asset_id"])
                usable_dataset.append(asset)
            except HTTPException:
                pass
        bindings = [json.loads(row["config"]) for row in self.db.all("SELECT config FROM lab_workflows ORDER BY created_at")]
        stages = []
        for stage in STAGES:
            locked = stage != "character_sheet" and not sheet_ok or stage in {"outfits", "references"} and not usable_dataset
            reason = "Aprove um Character Sheet para esta identidade primeiro." if stage != "character_sheet" and not sheet_ok else "Aprove pelo menos uma imagem do Dataset desta versão da identidade." if stage in {"outfits", "references"} and not usable_dataset else None
            complete = sheet_ok if stage == "character_sheet" else bool(usable_dataset) if stage == "dataset" else any(a["stage"] == stage and a["approval"] == "approved" and a["revision_id"] == current for a in assets)
            stages.append({"key": stage, "locked": bool(locked), "reason": reason, "complete": bool(complete), "workflow_ids": [b["workflow_id"] for b in bindings if b["stage"] == stage]})
        revisions = self.db.all("SELECT id,sheet_asset_id,created_at FROM lab_revisions WHERE character_id=? ORDER BY created_at DESC,id", (character_id,))
        jobs = self.db.all("SELECT job_id,stage,revision_id FROM lab_jobs WHERE character_id=? ORDER BY created_at DESC", (character_id,))
        principal = next((a for a in assets if a["asset_id"] == pointers["principal_asset_id"]), None)
        anchors = {key: None for key in SHEET_ANCHORS}
        if sheet_ok and principal and principal.get("job_id"):
            for asset in assets:
                key = asset["category"]
                if (key in anchors and anchors[key] is None and asset["stage"] == "character_sheet"
                        and asset["approval"] == "approved" and asset["revision_id"] == current
                        and asset.get("job_id") == principal["job_id"]):
                    try:
                        self.image(character_id, asset["asset_id"])
                        anchors[key] = asset["asset_id"]
                    except HTTPException:
                        pass
        return pointers | {"revisions": revisions, "stages": stages, "assets": assets, "workflow_bindings": bindings, "jobs": jobs, "sheet_anchors": anchors}

    def write_asset(self, metadata, conn):
        fields = ("asset_id", "character_id", "stage", "category", "approval", "priority", "revision_id", "legacy", "outfit_name", "job_id")
        conn.execute("INSERT INTO lab_assets(asset_id,character_id,stage,category,approval,priority,revision_id,legacy,outfit_name,job_id) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_id) DO UPDATE SET stage=excluded.stage,category=excluded.category,approval=excluded.approval,priority=excluded.priority,revision_id=excluded.revision_id,legacy=excluded.legacy,outfit_name=excluded.outfit_name,job_id=excluded.job_id", tuple(metadata.get(key) for key in fields))

    def approve_sheet(self, character_id, asset_id):
        self.character(character_id)
        row = self.image(character_id, asset_id)
        metadata = self.asset_metadata(row)
        if not metadata or metadata["stage"] != "character_sheet" or metadata["category"] != "character_sheet":
            raise HTTPException(422, "Selecione a prancha principal de Character Sheet; imagens auxiliares não podem definir a identidade.")
        job_id = metadata.get("job_id")
        job = self.db.one("SELECT character_id,status FROM jobs WHERE id=?", (job_id,)) if job_id else None
        if job and (job["character_id"] != character_id or job["status"] != "succeeded"):
            raise HTTPException(409, "Aguarde a conclusão do Character Sheet e de suas imagens auxiliares antes de aprovar a identidade.")
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT * FROM lab_characters WHERE character_id=?", (character_id,)).fetchone()
            if not previous or previous["principal_asset_id"] != asset_id:
                revision_id = uid()
                conn.execute("INSERT INTO lab_revisions VALUES(?,?,?,?)", (revision_id, character_id, asset_id, now()))
                conn.execute("INSERT INTO lab_characters(character_id,active_revision_id,principal_asset_id) VALUES(?,?,?) ON CONFLICT(character_id) DO UPDATE SET active_revision_id=excluded.active_revision_id,principal_asset_id=excluded.principal_asset_id,default_outfit_asset_id=NULL", (character_id, revision_id, asset_id))
            else:
                revision_id = previous["active_revision_id"]
            self.write_asset(metadata | {"approval": "approved", "revision_id": revision_id}, conn)
            # The approved board and its real image outputs form one identity
            # bundle. Companions from another job/revision are never adopted.
            if job:
                companions = conn.execute("SELECT * FROM lab_assets WHERE character_id=? AND job_id=? AND stage='character_sheet'", (character_id, job_id)).fetchall()
                for companion in companions:
                    if companion["category"] in SHEET_COMPANIONS:
                        self.image(character_id, companion["asset_id"])
                        self.write_asset(dict(companion) | {"approval": "approved", "revision_id": revision_id}, conn)
        self.sync_profile(character_id)
        return self.state(character_id)

    def patch_asset(self, character_id, asset_id, patch):
        self.character(character_id)
        row = self.image(character_id, asset_id)
        metadata = self.asset_metadata(row)
        if not metadata:
            raise HTTPException(422, "Este arquivo não pertence a uma etapa do Character Lab.")
        changes = patch.model_dump(exclude_none=True)
        pointers = self.pointers(character_id)
        stage = changes.get("stage", metadata["stage"])
        if asset_id == pointers["principal_asset_id"] and (stage != "character_sheet" or changes.get("approval", "approved") != "approved"):
            raise HTTPException(409, "A referência principal permanece aprovada; aprove outro Character Sheet para substituir a identidade.")
        if stage == "character_sheet" and changes.get("approval") == "approved":
            raise HTTPException(422, "Use Aprovar Character Sheet para definir a referência principal e sua versão.")
        if stage != metadata["stage"] and (metadata["revision_id"] or metadata.get("job_id")):
            raise HTTPException(409, "A etapa de origem de uma geração ou referência versionada não pode ser alterada. Importe uma cópia para uma nova finalidade.")
        if stage != metadata["stage"]:
            metadata = metadata | {"approval": "pending", "revision_id": None, "priority": 0}
        category = changes.get("category", metadata["category"] if stage == metadata["stage"] else PHYSICAL_CATEGORIES[stage])
        if stage == "character_sheet" and metadata.get("job_id") and category != metadata["category"]:
            raise HTTPException(409, "A função de uma imagem gerada do Character Sheet pertence ao workflow original e não pode ser reclassificada.")
        if asset_id == pointers["principal_asset_id"] and category_for(stage, category) != "character_sheet":
            raise HTTPException(409, "A prancha principal deve permanecer na categoria Character Sheet.")
        metadata = metadata | changes | {"stage": stage, "category": category_for(stage, category)}
        if changes.get("approval") == "approved":
            stage_state = next(s for s in self.state(character_id)["stages"] if s["key"] == stage)
            if stage_state["locked"]:
                raise HTTPException(409, stage_state["reason"])
            if metadata["revision_id"] and metadata["revision_id"] != pointers["active_revision_id"]:
                raise HTTPException(409, "Este arquivo pertence à versão anterior da identidade. Preserve seu histórico e gere um novo resultado para a versão atual.")
            metadata["revision_id"] = pointers["active_revision_id"]
        if metadata["approval"] == "rejected":
            metadata["priority"] = False
        with self.db.connect() as conn:
            self.write_asset(metadata, conn)
            if asset_id == pointers["default_outfit_asset_id"] and (metadata["approval"] != "approved" or metadata["stage"] != "outfits"):
                conn.execute("UPDATE lab_characters SET default_outfit_asset_id=NULL WHERE character_id=?", (character_id,))
        self.sync_profile(character_id)
        return self.state(character_id)

    def default_outfit(self, character_id, asset_id):
        self.character(character_id)
        row = self.image(character_id, asset_id)
        meta = self.asset_metadata(row)
        pointers = self.pointers(character_id)
        if not meta or meta["stage"] != "outfits" or meta["approval"] != "approved" or not pointers["active_revision_id"] or meta["revision_id"] != pointers["active_revision_id"]:
            raise HTTPException(409, "Escolha um figurino aprovado da versão atual da identidade.")
        self.db.execute("UPDATE lab_characters SET default_outfit_asset_id=? WHERE character_id=?", (asset_id, character_id))
        self.sync_profile(character_id)
        return self.state(character_id)

    async def bind(self, binding, client):
        row = self.db.one("SELECT * FROM workflows WHERE id=?", (binding.workflow_id,))
        if not row:
            raise HTTPException(404, "Workflow not found")
        if row["module"] != "character_lab":
            raise HTTPException(422, "O workflow precisa pertencer ao Character Lab.")
        adapter = WorkflowAdapter(json.loads(row["workflow"]), json.loads(row["mapping"]))
        if not adapter.inspect()["executable"]:
            raise HTTPException(422, "Envie o workflow real em formato API; um grafo de interface não pode ser associado à geração.")
        info = await client.object_info()
        report = adapter.validate(info)
        if not report["valid"]:
            raise WorkflowError("Workflow binding requires a valid local workflow", details=report["errors"])
        specs = adapter.mapping.get("parameters", {})
        prompt = specs.get(binding.prompt_parameter, {})
        if not binding.prompt_parameter or prompt.get("type") != "string" or prompt.get("kind") in {"image", "audio", "video"}:
            raise HTTPException(422, "Mapeie explicitamente o parâmetro de texto que receberá a descrição da personagem.")
        if binding.steps_parameter and specs.get(binding.steps_parameter, {}).get("type") != "integer":
            raise HTTPException(422, "Steps precisa apontar para um parâmetro inteiro real do workflow.")
        media = {name for name, spec in specs.items() if spec.get("kind") in {"image", "audio", "video"}}
        if media != set(binding.reference_parameters) or any(specs[name].get("kind") != "image" for name in media):
            raise HTTPException(422, "Atribua uma função explícita a cada input de imagem mapeado; referências de áudio/vídeo não são suportadas nesta etapa.")
        image_targets = {(specs[name]["node_id"], specs[name]["input"]) for name in media}
        for node_id, node in adapter.workflow.items():
            schema = info[node["class_type"]].get("input", {})
            fields = schema.get("required", {}) | schema.get("optional", {})
            if node["class_type"] == "MiniMaxH3MediaLoader":
                mapped = next((specs[name] for name in media if (specs[name]["node_id"], specs[name]["input"]) == (node_id, "media_state")), None)
                if not mapped or mapped.get("serializer") != "h3_media_state":
                    raise HTTPException(422, f"O loader {node_id}.media_state precisa de referências de personagem com serializer H3 explícito; arquivos fixos não podem definir a identidade.")
            for field, value in node["inputs"].items():
                field_spec = fields.get(field, [])
                options = field_spec[1] if isinstance(field_spec, list) and len(field_spec) > 1 and isinstance(field_spec[1], dict) else {}
                if options.get("image_upload") and not isinstance(value, list) and (node_id, field) not in image_targets:
                    raise HTTPException(422, f"O input de upload {node_id}.{field} precisa de uma referência de personagem explicitamente mapeada; nomes fixos de imagens não podem definir a identidade.")
        roles = set(binding.reference_parameters.values())
        for name, role in binding.reference_parameters.items():
            if role in {"sheet_upper_bundle", "sheet_full_bundle"} and specs[name].get("serializer") != "h3_media_state":
                raise HTTPException(422, "As referências combinadas do Sheet exigem o serializer H3 de imagens explicitamente mapeado.")
        if binding.stage == "dataset" and not SHEET_ROLES & roles:
            raise HTTPException(422, "O Dataset deve receber automaticamente o Character Sheet aprovado.")
        if binding.stage in {"outfits", "references"} and not roles & (SHEET_ROLES | {"dataset"}):
            raise HTTPException(422, "A etapa precisa receber uma referência aprovada da identidade (sheet ou dataset).")
        if binding.stage == "character_sheet" and roles & (SHEET_ROLES | {"dataset", "outfit"}):
            raise HTTPException(422, "Character Sheet aceita somente referências opcionais; não pode depender de etapas futuras.")
        if binding.stage == "dataset" and roles & {"dataset", "outfit", "garment"}:
            raise HTTPException(422, "Dataset depende do Character Sheet, sem dependência circular de Dataset ou figurino.")
        output_nodes = set(adapter.mapping.get("output_nodes", []))
        if not output_nodes or set(binding.output_categories) != output_nodes:
            raise HTTPException(422, "Classifique cada nó de saída real selecionado no mapeamento do workflow.")
        for category in binding.output_categories.values():
            category_for(binding.stage, category)
        if binding.prompt_template is not None:
            try:
                fields = []
                for _, field, fmt, conversion in Formatter().parse(binding.prompt_template):
                    if field is not None:
                        if field not in {"identity", "prompt"} or fmt or conversion:
                            raise ValueError()
                        fields.append(field)
                if "identity" not in fields:
                    raise ValueError()
                binding.prompt_template.format(identity="identity", prompt="request")
            except (ValueError, KeyError, IndexError) as exc:
                raise HTTPException(422, "O template aceita apenas {identity} e {prompt} e deve incluir {identity}.") from exc
        stamp = now()
        self.db.execute("INSERT INTO lab_workflows VALUES(?,?,?,?,?) ON CONFLICT(workflow_id) DO UPDATE SET stage=excluded.stage,config=excluded.config,updated_at=excluded.updated_at", (binding.workflow_id, binding.stage, encode(binding.model_dump()), stamp, stamp))
        return binding.model_dump()

    def generation(self, character_id, payload):
        character = self.character(character_id)
        state = self.state(character_id)
        stage_state = next(s for s in state["stages"] if s["key"] == payload.stage)
        if stage_state["locked"]:
            raise HTTPException(409, stage_state["reason"])
        binding = next((b for b in state["workflow_bindings"] if b["workflow_id"] == payload.workflow_id and b["stage"] == payload.stage), None)
        if not binding:
            raise HTTPException(422, "Workflow desta etapa ainda não foi fornecido, inspecionado e associado explicitamente.")
        row = self.db.one("SELECT * FROM workflows WHERE id=?", (payload.workflow_id,))
        adapter = WorkflowAdapter(json.loads(row["workflow"]), json.loads(row["mapping"]))
        specs = adapter.mapping.get("parameters", {})
        reserved = set(binding["reference_parameters"]) | {binding["prompt_parameter"], binding["steps_parameter"]}
        if set(payload.parameters) & reserved:
            raise HTTPException(422, "Prompt, steps e referências são resolvidos pelos controles da etapa; não podem ser sobrescritos em parâmetros avançados.")
        parameters = dict(payload.parameters)
        identity = (character["description"] or character["prompt"]).strip()
        if not identity:
            raise HTTPException(422, "Preencha a descrição física da personagem antes de gerar.")
        requested = (payload.prompt_text or "").strip()
        template = binding.get("prompt_template")
        if template:
            if requested and "{prompt}" not in template:
                raise HTTPException(422, "Este template não mapeia o texto adicional; inclua {prompt} antes de usar o prompt da etapa.")
            prompt = template.format(identity=identity, prompt=requested)
        else:
            spec = specs[binding["prompt_parameter"]]
            base = spec.get("default", adapter.workflow[spec["node_id"]]["inputs"][spec["input"]])
            prompt = "\n\n".join(part for part in (base if isinstance(base, str) else "", "Character identity (authoritative):\n" + identity, "Requested output:\n" + requested if requested else "") if part)
        if payload.stage != "character_sheet":
            prompt += "\n\nPreserve the same face, facial features, skin tone, hair, body proportions and visual identity of the approved character references."
        parameters[binding["prompt_parameter"]] = prompt
        if payload.steps is not None:
            if not binding["steps_parameter"]:
                raise HTTPException(422, "Este workflow não possui steps mapeados; o valor original será preservado.")
            parameters[binding["steps_parameter"]] = payload.steps
        elif binding["steps_parameter"]:
            spec = specs[binding["steps_parameter"]]
            parameters[binding["steps_parameter"]] = spec.get("default", adapter.workflow[spec["node_id"]]["inputs"][spec["input"]])
        refs = binding["reference_parameters"]
        roles = set(refs.values())
        if payload.reference_asset_id and "optional_reference" not in roles or payload.garment_asset_id and "garment" not in roles or payload.outfit_asset_id and "outfit" not in roles:
            raise HTTPException(422, "O workflow selecionado não possui um input mapeado para essa referência.")
        dataset = sorted((a for a in state["assets"] if a["stage"] == "dataset" and a["approval"] == "approved" and a["revision_id"] == state["active_revision_id"]), key=lambda a: (not a["priority"], a["asset_id"]))
        dataset_index, asset_inputs = 0, {}
        outfit_id = payload.outfit_asset_id or state["default_outfit_asset_id"]
        for name, role in refs.items():
            asset_id = None
            if role == "sheet":
                asset_id = state["principal_asset_id"]
            elif role in {"sheet_face", "sheet_upper_bundle", "sheet_full_bundle"}:
                keys = SHEET_ANCHORS[:1] if role == "sheet_face" else SHEET_ANCHORS[:2] if role == "sheet_upper_bundle" else SHEET_ANCHORS
                missing = [key for key in keys if not state["sheet_anchors"].get(key)]
                if missing:
                    raise HTTPException(409, "O Character Sheet aprovado não possui as imagens auxiliares exigidas (" + ", ".join(missing) + "). Gere e aprove a prancha completa com as referências de rosto e corpo.")
                resolved = [state["sheet_anchors"][key] for key in keys]
                asset_id = resolved[0] if role == "sheet_face" else resolved
            elif role == "dataset":
                if dataset_index < len(dataset):
                    asset_id = dataset[dataset_index]["asset_id"]
                    dataset_index += 1
            elif role == "optional_reference":
                asset_id = payload.reference_asset_id
            elif role == "garment":
                asset_id = payload.garment_asset_id
            elif role == "outfit":
                asset_id = outfit_id
                if asset_id:
                    meta = next((a for a in state["assets"] if a["asset_id"] == asset_id), None)
                    if not meta or meta["stage"] != "outfits" or meta["approval"] != "approved" or meta["revision_id"] != state["active_revision_id"]:
                        raise HTTPException(409, "O figurino selecionado deve estar aprovado para a versão atual da identidade.")
            if asset_id:
                for resolved_id in asset_id if isinstance(asset_id, list) else [asset_id]:
                    self.image(character_id, resolved_id)
                asset_inputs[name] = asset_id
            else:
                # A mapped image slot is a real input in the immutable graph.
                # Never leave a stale sample filename in that slot, even if the
                # mapping calls it optional. A no-reference workflow variant is
                # necessary when its graph has no optional image execution path.
                raise HTTPException(422, f"O input de imagem '{name}' ({role}) precisa de uma referência válida. Use uma variante sem esse input para gerar sem imagem opcional.")
        context = {"stage": payload.stage, "revision_id": state["active_revision_id"], "principal_asset_id": state["principal_asset_id"],
                   "default_outfit_asset_id": state["default_outfit_asset_id"], "outfit_name": payload.outfit_name,
                   "identity_description": identity, "prompt_text": requested, "parameters": parameters,
                   "asset_inputs": asset_inputs, "reference_roles": refs, "output_categories": binding["output_categories"],
                   "binding": binding, "captured_at": now()}
        return {"module": "character_lab", "character_id": character_id, "workflow_id": payload.workflow_id,
                "parameters": parameters, "asset_inputs": asset_inputs, "consent_confirmed": True}, context


def lab_output(db, job_id, node_id):
    """Resolve output classification from submission snapshot, never current UI."""
    row = db.one("SELECT * FROM lab_jobs WHERE job_id=?", (job_id,))
    if not row:
        return None
    context = json.loads(row["context"])
    category = context["output_categories"].get(str(node_id))
    if category is None:
        raise ValueError("Lab output node is absent from its immutable category mapping")
    return {"stage": row["stage"], "category": category_for(row["stage"], category), "revision_id": row["revision_id"],
            "approval": "pending", "priority": False, "legacy": False, "outfit_name": context.get("outfit_name"), "job_id": job_id}


def router(lab, client, enqueue):
    routes = APIRouter()

    @routes.get("/api/characters/{character_id}/lab")
    async def state(character_id: str):
        return lab.state(character_id)

    @routes.post("/api/characters/{character_id}/lab/approve-sheet")
    async def approve_sheet(character_id: str, payload: AssetSelection):
        return lab.approve_sheet(character_id, payload.asset_id)

    @routes.patch("/api/characters/{character_id}/lab/assets/{asset_id}")
    async def patch_asset(character_id: str, asset_id: str, payload: AssetPatch):
        return lab.patch_asset(character_id, asset_id, payload)

    @routes.post("/api/characters/{character_id}/lab/default-outfit")
    async def default_outfit(character_id: str, payload: AssetSelection):
        return lab.default_outfit(character_id, payload.asset_id)

    @routes.post("/api/lab/workflows", status_code=201)
    async def bind_workflow(payload: WorkflowBinding):
        return await lab.bind(payload, client)

    @routes.post("/api/characters/{character_id}/lab/generate", status_code=202)
    async def generate(character_id: str, payload: GenerateRequest):
        request, context = lab.generation(character_id, payload)
        return await enqueue(request, context)

    return routes

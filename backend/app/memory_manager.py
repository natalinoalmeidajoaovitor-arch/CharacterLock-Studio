"""One GPU execution lease and measured, native ComfyUI model transitions.

The installed native /free route queues flags; HTTP 200 is an acknowledgement,
not completion. Its worker unloads registered models, resets the executor cache
(also releasing OmniVoice outputs), collects garbage and empties PyTorch caches.
There is no native loaded-model/flag-completion route. We therefore require an
idle engine and repeated low PyTorch allocation readings before submitting.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import time

from .comfy import ComfyError
from .db import encode, now
from .storage import safe_path

log = logging.getLogger("characterlock.memory")
MIB = 1024 * 1024
_MODEL_FILE = re.compile(r"\.(?:safetensors|gguf|ckpt|pt|pth|bin|onnx)(?:$|[?#])", re.I)
_MODEL_FIELD = re.compile(r"(?:model|unet|clip|vae|lora|checkpoint|encoder|decoder|controlnet|diffusion)", re.I)
_IGNORED = {"prompt", "negative_prompt", "text", "seed", "noise_seed", "steps", "num_step", "filename_prefix"}


class MemoryManagerError(ComfyError):
    def __init__(self, message, *, code, details=None):
        super().__init__(message, details=details)
        self.code = code


def _link(value, prompt):
    return (isinstance(value, list) and len(value) == 2
            and isinstance(value[0], (str, int)) and str(value[0]) in prompt
            and isinstance(value[1], int) and not isinstance(value[1], bool))


def model_signature(prompt: dict, output_nodes=None, object_info=None) -> dict:
    """Fingerprint reachable model loaders and LoRAs, never scene text or seeds.

    Filename, dtype/device, quantization and enabled LoRA strengths matter. Node
    IDs and repeated identical loader instances do not. Unknown model sources
    disable reuse rather than being guessed from a tab/workflow name.
    """
    info = object_info or {}
    roots = [str(node) for node in (output_nodes or []) if str(node) in prompt]
    if not roots:
        roots = [node_id for node_id, node in prompt.items() if info.get(node["class_type"], {}).get("output_node")]
    if not roots:
        referenced = {str(value[0]) for node in prompt.values() for value in node.get("inputs", {}).values() if _link(value, prompt)}
        roots = [node_id for node_id in prompt if node_id not in referenced]
    reachable = set()

    def visit(node_id):
        if node_id in reachable:
            return
        reachable.add(node_id)
        for value in prompt[node_id].get("inputs", {}).values():
            if _link(value, prompt):
                visit(str(value[0]))

    for node_id in roots:
        visit(node_id)

    def literal(value, seen=None):
        if not _link(value, prompt):
            return value
        node_id = str(value[0])
        seen = set() if seen is None else seen
        if node_id in seen:
            return None
        seen.add(node_id)
        node = prompt[node_id]
        if node["class_type"] in {"PrimitiveString", "PrimitiveStringMultiline", "PrimitiveInt", "PrimitiveFloat", "PrimitiveBoolean"}:
            return literal(node.get("inputs", {}).get("value"), seen)
        return None

    resources, unknown = [], []
    for node_id in sorted(reachable):
        node = prompt[node_id]
        class_type, inputs = node["class_type"], node.get("inputs", {})
        is_lora = "lora" in class_type.lower()
        is_loader = "load" in class_type.lower() and any(token in class_type.lower() for token in ("model", "unet", "clip", "vae", "gguf", "checkpoint", "controlnet", "encoder", "lora"))
        fields = {}
        for name, value in inputs.items():
            if name.lower() in _IGNORED:
                continue
            resolved = literal(value)
            if isinstance(resolved, dict) and is_lora:
                # rgthree Power LoRA rows are dictionaries, including an on flag.
                if resolved.get("on", True) and resolved.get("lora") not in {None, "", "None"}:
                    fields[name] = resolved
            elif resolved is not None and not _link(value, prompt):
                if (is_loader or is_lora) and isinstance(resolved, (str, int, float, bool)):
                    fields[name] = resolved
                elif isinstance(resolved, str) and _MODEL_FIELD.search(name) and _MODEL_FILE.search(resolved):
                    fields[name] = resolved
            elif isinstance(resolved, (str, int, float, bool)) and (is_loader or is_lora):
                fields[name] = resolved
        # An empty passthrough Power LoRA node changes no loaded resources.
        if is_lora and not fields:
            continue
        if fields:
            resources.append({"loader": class_type, "settings": fields})
        elif is_loader:
            unknown.append(class_type)
    unique = sorted({encode(resource) for resource in resources})
    resources = [json.loads(resource) for resource in unique]
    # OmniVoice's installed loader has a fixed models/omnivoice path and no file
    # widget. Its class + device/dtype/compile settings are an actual resource.
    reusable = bool(resources) and not unknown
    payload = {"resources": resources, "unknown_loaders": sorted(set(unknown))}
    return payload | {"fingerprint": hashlib.sha256(encode(payload).encode()).hexdigest(), "reusable": reusable}


def _nvidia_snapshot():
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"available": False, "reason": "nvidia-smi not on PATH"}
    try:
        options = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        result = subprocess.run([executable, "--query-gpu=index,name,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=True, **options)
        devices = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) == 5:
                devices.append({"index": int(parts[0]), "name": parts[1], "total_mib": int(parts[2]), "used_mib": int(parts[3]), "free_mib": int(parts[4])})
        return {"available": bool(devices), "devices": devices, "scope": "whole GPU; includes desktop and other processes"}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"available": False, "reason": type(exc).__name__}


class AIModelMemoryManager:
    def __init__(self, comfy, db, storage_root, *, idle_timeout=120.0, release_timeout=45.0, poll_seconds=0.5,
                 settle_seconds=1.0, residual_limit_bytes=512 * MIB, nvidia_reader=_nvidia_snapshot):
        self.comfy, self.db, self.root = comfy, db, Path(storage_root)
        self.idle_timeout, self.release_timeout = idle_timeout, release_timeout
        self.poll_seconds, self.settle_seconds = poll_seconds, settle_seconds
        self.residual_limit_bytes, self.nvidia_reader = residual_limit_bytes, nvidia_reader
        self.lock = asyncio.Lock()
        self.active_job_id = None
        self.owner_task = None
        self.current_signature = None  # Never trust a loaded-state claim across process restarts.
        self.pending_signature = None
        self.notify = None
        self._status = {"name": "AI Model Memory Manager", "phase": "idle", "active_job_id": None,
                        "current_pipeline": None, "last_transition": None, "last_measurement": None,
                        "policy": "one execution; reuse matching reachable model sets; native /free on transitions",
                        "confirmation": "native HTTP acknowledgement plus observed memory; no loaded-model inventory API"}

    def status(self):
        return deepcopy(self._status)

    def owns(self, job_id):
        return self.active_job_id == job_id and self.owner_task is asyncio.current_task()

    def _event(self, job_id, phase, **details):
        event = {"at": now(), "phase": phase, **details}
        self._status.update(phase=phase, last_transition=event)
        directory = safe_path(self.root, f"jobs/{job_id}")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "memory.json"
        document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"job_id": job_id, "events": []}
        document["events"].append(event)
        document["status"] = self.status()
        pending = directory / "memory.pending"
        pending.write_text(encode(document), encoding="utf-8")
        pending.replace(path)
        row = self.db.one("SELECT status FROM jobs WHERE id=?", (job_id,))
        if row:
            self.db.execute("INSERT INTO job_events(job_id,status,detail,created_at) VALUES(?,?,?,?)", (job_id, row["status"], encode({"memory": event}), event["at"]))
            if row["status"] == "preparing":
                messages = {"waiting_for_engine": "Aguardando a geração anterior terminar.", "unloading_models": "Liberando os modelos anteriores da memória.", "release_acknowledged": "Conferindo a memória liberada pelo ComfyUI.", "memory_ready": "Memória conferida; preparando o novo modelo.", "reusing_models": "Reutilizando os modelos já preparados."}
                if phase in messages:
                    self.db.execute("UPDATE jobs SET progress=? WHERE id=? AND status='preparing'", (encode({"phase": phase, "message": messages[phase]}), job_id))
            if self.notify:
                self.notify(job_id)
        log.info("Job %s memory %s: %s", job_id, phase, encode(details))

    @asynccontextmanager
    async def execution(self, job_id, *, resumed=False):
        async with self.lock:
            self.active_job_id, self.owner_task = job_id, asyncio.current_task()
            self.pending_signature = None
            self._status.update(active_job_id=job_id, phase="observing" if resumed else "preparing")
            if resumed:
                # Existing upstream work must finish before *any* unload request.
                self.current_signature = None
                self._status["current_pipeline"] = None
                self._event(job_id, "resuming_observation", message="Persisted prompt is being observed; no unload or resubmission.")
            try:
                yield
            finally:
                self.active_job_id, self.owner_task = None, None
                self._status.update(active_job_id=None, phase="idle")

    def _assert_owner(self, job_id):
        if not self.owns(job_id):
            raise MemoryManagerError("The memory operation requires the central execution lease.", code="memory_lease_required")

    async def _idle(self, job_id, *, wait):
        deadline = time.monotonic() + (self.idle_timeout if wait else 0)
        waiting_logged = False
        while True:
            others = self.db.all("SELECT id,status FROM jobs WHERE status IN ('preparing','submitting','running') AND id<>?", (job_id,))
            queue = await self.comfy.queue()
            if not isinstance(queue, dict) or not all(isinstance(queue.get(key), list) for key in ("queue_running", "queue_pending")):
                raise MemoryManagerError("ComfyUI queue state could not be verified.", code="memory_queue_unknown")
            busy = bool(others or queue["queue_running"] or queue["queue_pending"])
            if not busy:
                return queue
            if not waiting_logged:
                self._event(job_id, "waiting_for_engine", other_app_jobs=others,
                            native_running=len(queue["queue_running"]), native_pending=len(queue["queue_pending"]))
                waiting_logged = True
            if time.monotonic() >= deadline:
                raise MemoryManagerError("ComfyUI is busy. Model unloading and submission were skipped; retry after its queue finishes.",
                                         code="memory_engine_busy", details={"other_app_jobs": others, "native_running": len(queue["queue_running"]), "native_pending": len(queue["queue_pending"])})
            await asyncio.sleep(self.poll_seconds)

    async def snapshot(self, *, include_nvidia=True):
        stats = await self.comfy.system_stats()
        devices = []
        for device in stats.get("devices", []):
            if not isinstance(device, dict):
                continue
            reserved, cache = device.get("torch_vram_total"), device.get("torch_vram_free")
            devices.append({key: device.get(key) for key in ("name", "type", "index", "vram_total", "vram_free", "torch_vram_total", "torch_vram_free")} |
                           {"torch_active_bytes": max(0, reserved - cache) if isinstance(reserved, (int, float)) and isinstance(cache, (int, float)) else None})
        result = {"at": now(), "devices": devices, "ram_free": stats.get("system", {}).get("ram_free")}
        if include_nvidia and self.nvidia_reader:
            result["nvidia_smi"] = await asyncio.to_thread(self.nvidia_reader)
        self._status["last_measurement"] = result
        return result

    def _low_memory(self, measurement):
        devices = [device for device in measurement["devices"] if device.get("type") not in {"cpu", "mps"}]
        if not devices:
            # CPU-only operation is valid only if a device was actually reported.
            return bool(measurement["devices"])
        return all(isinstance(device.get("torch_vram_total"), (int, float))
                   and 0 <= max(device["torch_vram_total"], device.get("torch_active_bytes") or 0) <= self.residual_limit_bytes
                   for device in devices)

    async def _release(self, job_id, *, reason):
        self._assert_owner(job_id)
        await self._idle(job_id, wait=True)
        before = await self.snapshot()
        self._event(job_id, "unloading_models", reason=reason, before=before,
                    payload={"unload_models": True, "free_memory": True})
        # Native-only operation: the installed official SDK exposes jobs/models
        # (Router inference), not a compatible local unload API. Use the existing
        # native client's authenticated/error-checked request, never a new client.
        await self.comfy._request("POST", "/free", json={"unload_models": True, "free_memory": True})
        self.current_signature = None
        self._status["current_pipeline"] = None
        self._event(job_id, "release_acknowledged", message="Flags queued by ComfyUI; measuring memory, not assuming unload completion.")
        started, stable, polls = time.monotonic(), 0, 0
        after = None
        while time.monotonic() - started < self.release_timeout or (0 < stable < 3 and polls < 5):
            polls += 1
            await self._idle(job_id, wait=False)
            after = await self.snapshot(include_nvidia=False)
            stable = stable + 1 if self._low_memory(after) else 0
            if stable >= 3 and time.monotonic() - started >= self.settle_seconds:
                after = await self.snapshot()
                self._event(job_id, "memory_ready", reason=reason, before=before, after=after,
                            confirmation="acknowledged_and_low_memory_observed", residual_limit_bytes=self.residual_limit_bytes,
                            message="Native queue stayed idle and PyTorch allocation is low. CUDA context and other processes may retain VRAM.")
                return
            if time.monotonic() - started >= self.release_timeout and stable == 0:
                break
            await asyncio.sleep(self.poll_seconds)
        self._event(job_id, "release_unverified", before=before, after=after)
        raise MemoryManagerError("ComfyUI accepted model cleanup, but low GPU allocation was not observed before timeout. The next generation was not submitted.",
                                 code="memory_release_unverified", details={"before": before, "after": after})

    async def prepare(self, job_id, prompt, output_nodes=None, object_info=None):
        self._assert_owner(job_id)
        signature = model_signature(prompt, output_nodes, object_info)
        self.pending_signature = signature
        await self._idle(job_id, wait=True)
        matches = bool(self.current_signature and self.current_signature["reusable"] and signature["reusable"]
                       and self.current_signature["fingerprint"] == signature["fingerprint"])
        if matches:
            measurement = await self.snapshot()
            self._event(job_id, "reusing_models", pipeline=signature, measurement=measurement,
                        message="Reachable models and LoRA settings match the previous observed generation.")
        else:
            self._event(job_id, "pipeline_transition", previous=self.current_signature, next=signature)
            await self._release(job_id, reason="unknown_initial_pipeline" if self.current_signature is None else "model_set_changed")
        await self._idle(job_id, wait=False)
        self._status.update(phase="ready", requested_pipeline=signature)

    async def finish(self, job_id, row):
        self._assert_owner(job_id)
        status = row["status"] if row else "unknown"
        error = json.loads(row["error"]) if row and row.get("error") else None
        text = encode(error).lower() if error else ""
        oom = any(token in text for token in ("outofmemoryerror", "out of memory", "cuda_error_out_of_memory", "cuda out of memory"))
        measurement = None
        try:
            measurement = await self.snapshot()
        except Exception as exc:
            self._event(job_id, "measurement_unavailable", error=str(exc))
        self._event(job_id, "execution_finished", job_status=status, measurement=measurement, oom=oom)
        if oom:
            self.current_signature = None
            self._status["current_pipeline"] = None
            self._event(job_id, "oom_detected", error=error, message="Original error retained. Cleanup only; this generation will not be replayed.")
            try:
                # Do not wait or unload while another native/app task is active.
                await self._idle(job_id, wait=False)
                await self._release(job_id, reason="out_of_memory_recovery")
                self._event(job_id, "oom_cleanup_completed", message="Memory was measured after safe cleanup. A new retry requires a user action.")
            except Exception as exc:
                self._event(job_id, "oom_cleanup_deferred", error=str(exc), code=getattr(exc, "code", "memory_cleanup_failed"))
        elif row and row.get("prompt_id") and status in {"succeeded", "failed"} and self.pending_signature:
            self.current_signature = deepcopy(self.pending_signature)
            self._status["current_pipeline"] = self.current_signature
        else:
            self.current_signature = None
            self._status["current_pipeline"] = None

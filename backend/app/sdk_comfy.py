"""Official SDK execution with native node discovery and validated media staging.

The local proxy preserves ComfyUI prompt IDs, including IDs from older jobs.
Image and reviewed VHS MP4 staging use the inherited installed native route;
submission, progress and output retrieval remain on the official SDK.
"""
from copy import deepcopy
import io
import os
from threading import Lock
from urllib.parse import urlsplit
import uuid

import httpx

from comfy_sdk import AsyncComfy
from comfy_sdk.events import Progress, StatusChange
from comfy_sdk.exceptions import ComfyError as SDKError, NotFound

from .comfy import ComfyClient, ComfyError, _safe_descriptor
from .workflows import workflow_format

_constructor_lock = Lock()


def official_sdk(base_url: str, timeout: float) -> AsyncComfy:
    # SDK 0.5 reads its target at construction. Restore the process environment
    # synchronously before serving requests; never inherit cloud credentials.
    with _constructor_lock:
        previous = {key: os.environ.get(key) for key in ("COMFY_BASE_URL", "COMFY_API_KEY", "COMFY_ROUTER_BASE_URL")}
        os.environ.update(COMFY_BASE_URL=base_url, COMFY_ROUTER_BASE_URL=base_url)
        os.environ.pop("COMFY_API_KEY", None)
        try:
            return AsyncComfy(api_key="", timeout=timeout, client_info="CharacterLockStudio/0.1")
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class BoundedBuffer(io.BytesIO):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit

    def write(self, content):
        if self.tell() + len(content) > self.limit:
            raise ComfyError("Comfy SDK output exceeds the configured download size limit.")
        return super().write(content)


class SDKComfyClient(ComfyClient):
    transport_name = "comfy-sdk"

    def __init__(self, base_url, proxy_url, *, sdk=None, **kwargs):
        super().__init__(base_url, **kwargs)
        parsed = urlsplit(proxy_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ComfyError("The SDK target must be a local loopback proxy origin.")
        self.proxy_url = proxy_url.rstrip("/")
        self.sdk = sdk or official_sdk(self.proxy_url, kwargs.get("timeout", 30))

    async def close(self):
        try:
            await self.sdk.aclose()
        finally:
            await super().close()

    async def proxy_health(self):
        try:
            response = await self._client.get(self.proxy_url + "/api/v2/health", timeout=3)
            response.raise_for_status()
            payload = response.json()
            # A healthy proxy for another engine is not a usable connection.
            return (isinstance(payload, dict) and payload.get("status") == "healthy"
                    and payload.get("upstream", "").rstrip("/") == self.base_url)
        except Exception:
            return False

    @staticmethod
    def sdk_error(exc, *, submitting=False):
        status, code = getattr(exc, "http_status", None), getattr(exc, "code", None)
        uncertain = (submitting and (status not in {400, 401, 403, 404, 409, 422, 429}
                                    or code == "idempotency_key_reuse"))
        return ComfyError("Comfy SDK: " + str(exc), status,
                         {"transport": "comfy-sdk", "code": code, "errors": getattr(exc, "details", None),
                          "submission_uncertain": uncertain})

    async def submit(self, prompt, client_id=None):
        if workflow_format(prompt) != "api":
            raise ComfyError("Only validated API-format workflow exports can be submitted through the SDK.")
        workflow = self.sdk.workflows.from_json(deepcopy(prompt))
        try:
            # Stable, persisted key. The SDK only backs off known queue-full
            # rejections; ambiguous network errors are never replayed here.
            job = await self.sdk.submit(workflow, idempotency_key=client_id or str(uuid.uuid4()))
        except (SDKError, httpx.HTTPError) as exc:
            raise self.sdk_error(exc, submitting=True) from exc
        if not isinstance(job.id, str) or not job.id:
            raise ComfyError("Comfy SDK omitted the job ID; submission outcome is unknown.")
        return {"prompt_id": job.id, "transport": self.transport_name}

    async def history(self, prompt_id):
        if not isinstance(prompt_id, str) or not prompt_id or len(prompt_id) > 200:
            raise ComfyError("A valid persisted job ID is required.")
        try:
            job = await self.sdk.jobs.get(prompt_id)
        except NotFound:
            return {}
        except (SDKError, httpx.HTTPError) as exc:
            raise self.sdk_error(exc) from exc
        if job.status in {"expired", "timed_out"}:
            return {}  # Worker checks the native queue before marking absent.
        failed = job.status in {"failed", "canceled", "cancelled"}
        error = job.error.model_dump(mode="json") if job.error is not None else None
        status = {"completed": job.status == "succeeded",
                  "status_str": "error" if failed else "success" if job.status == "succeeded" else "running",
                  "messages": [["execution_error", error or {"sdk_status": job.status}]] if failed else []}
        outputs = {}
        for output in job.outputs:
            descriptor = _safe_descriptor(output.name, "", "output")
            descriptor.update(sdk_job_id=job.id, sdk_asset_id=output.id, sdk_node_id=output.node_id)
            group = {"image": "images", "audio": "audio", "video": "videos"}.get(output.type, "files")
            outputs.setdefault(output.node_id, {}).setdefault(group, []).append(descriptor)
        return {prompt_id: {"status": status, "outputs": outputs, "transport": self.transport_name, "sdk_status": job.status}}

    async def progress_events(self, prompt_id):
        """Live engine observations; polling remains authoritative for completion."""
        try:
            job = await self.sdk.jobs.get(prompt_id)
            async for event in job.events():
                if isinstance(event, Progress):
                    # The local proxy's initial 0/0 snapshot is indeterminate,
                    # not evidence of sampler progress. Only forward real data.
                    if not (event.nodes_total or event.steps or event.current_node or event.message):
                        continue
                    yield {"phase": "running", "value": event.value,
                           "nodes_done": event.nodes_done, "nodes_total": event.nodes_total,
                           "current_node": event.current_node, "step": event.step,
                           "steps": event.steps, "message": event.message or "ComfyUI está processando a geração."}
                elif isinstance(event, StatusChange) and event.status in {"queued", "running", "canceling"}:
                    yield {"phase": event.status, "queue_position": event.queue_position,
                           "message": "Aguardando a fila do ComfyUI." if event.status == "queued"
                           else "ComfyUI está processando a geração." if event.status == "running"
                           else "Cancelamento solicitado ao ComfyUI."}
        except (SDKError, httpx.HTTPError) as exc:
            raise self.sdk_error(exc) from exc

    async def download_output(self, output):
        if not isinstance(output, dict):
            raise ComfyError("Output must be a Comfy SDK descriptor.")
        _safe_descriptor(output.get("filename", ""), output.get("subfolder", ""), output.get("type", "output"))
        # Saved native histories from older jobs remain readable.
        if not output.get("sdk_asset_id"):
            return await super().download_output(output)
        job_id, asset_id, node_id = (output.get(key) for key in ("sdk_job_id", "sdk_asset_id", "sdk_node_id"))
        if not all(isinstance(value, str) and value for value in (job_id, asset_id, node_id)):
            raise ComfyError("Incomplete Comfy SDK output descriptor.")
        try:
            job = await self.sdk.jobs.get(job_id)
            matching = next((item for item in job.get_outputs(node_id) if item.id == asset_id and item.name == output["filename"]), None)
            if matching is None:
                raise ComfyError("Output is no longer present in the persisted SDK job.")
            if matching.size_bytes > self.max_output_bytes:
                raise ComfyError("Comfy SDK output exceeds the configured download size limit.")
            with BoundedBuffer(self.max_output_bytes) as buffer:
                await matching.to_stream(buffer)
                return buffer.getvalue()
        except (SDKError, httpx.HTTPError) as exc:
            raise self.sdk_error(exc) from exc

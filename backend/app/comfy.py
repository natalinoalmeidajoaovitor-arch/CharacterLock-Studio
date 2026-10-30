"""Small real HTTP client for the public ComfyUI server routes.

Reference: https://docs.comfy.org/development/comfyui-server/comms_routes
No retries are performed for /prompt: a timed-out POST might already be queued.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit
import uuid

import httpx

from .workflows import workflow_format


class ComfyError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, details: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


def _safe_descriptor(filename: str, subfolder: str, storage_type: str) -> dict[str, str]:
    if not isinstance(filename, str) or not filename or filename in {".", ".."} or any(char in filename for char in ("/", "\\", "\x00", ":")):
        raise ComfyError("Invalid output filename.")
    if not isinstance(subfolder, str) or "\x00" in subfolder or ":" in subfolder:
        raise ComfyError("Invalid output subfolder.")
    normalized = subfolder.replace("\\", "/")
    if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
        raise ComfyError("Output subfolder must remain relative to ComfyUI storage.")
    if not isinstance(storage_type, str) or storage_type not in {"input", "output", "temp"}:
        raise ComfyError("Unsupported ComfyUI storage type.")
    return {"filename": filename, "subfolder": normalized, "type": storage_type}


class ComfyClient:
    def __init__(self, base_url: str, timeout: float = 30, http_client: httpx.AsyncClient | None = None, max_output_bytes: int = 512 * 1024 * 1024):
        if not isinstance(base_url, str):
            raise ComfyError("ComfyUI URL must be a string.")
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ComfyError("ComfyUI URL must be an HTTP(S) server address without embedded credentials, query or fragment.")
        self.base_url = base_url.rstrip("/")
        if not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool) or max_output_bytes <= 0:
            raise ComfyError("Output byte limit must be a positive integer.")
        self.max_output_bytes = max_output_bytes
        self._owned_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False)

    async def close(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def __aenter__(self) -> "ComfyClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def _request(self, method: str, route: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, self.base_url + route, **kwargs)
        except httpx.RequestError as exc:
            message = "ComfyUI is unreachable. Check its address and start the existing server."
            if method == "POST" and route == "/prompt":
                message = "ComfyUI submission could not be confirmed. Check the upstream queue before resubmitting; no automatic retry was made."
            raise ComfyError(message, details={"type": type(exc).__name__, "route": route, "submission_uncertain": method == "POST" and route == "/prompt"}) from exc
        if response.status_code >= 300:
            try:
                details = response.json()
            except ValueError:
                details = {"response": response.text[:2000]}
            raise ComfyError(f"ComfyUI returned HTTP {response.status_code} for {route}.", response.status_code, details)
        return response

    async def _json(self, method: str, route: str, **kwargs: Any) -> dict:
        response = await self._request(method, route, **kwargs)
        try:
            data = response.json()
        except ValueError as exc:
            raise ComfyError("ComfyUI returned an invalid JSON response.", details={"route": route}) from exc
        if not isinstance(data, dict):
            raise ComfyError("ComfyUI response must be an object.", details={"route": route})
        return data

    async def system_stats(self) -> dict:
        return await self._json("GET", "/system_stats")

    async def object_info(self) -> dict:
        return await self._json("GET", "/object_info")

    async def queue(self) -> dict:
        return await self._json("GET", "/queue")

    async def history(self, prompt_id: str) -> dict:
        if not isinstance(prompt_id, str) or not prompt_id or len(prompt_id) > 200:
            raise ComfyError("A valid prompt ID is required.")
        return await self._json("GET", "/history/" + quote(prompt_id, safe=""))

    async def submit(self, prompt: dict, client_id: str | None = None) -> dict:
        if workflow_format(prompt) != "api":
            raise ComfyError("Only API-format prompt exports can be submitted to ComfyUI.")
        payload = {"prompt": deepcopy(prompt), "client_id": client_id or str(uuid.uuid4())}
        result = await self._json("POST", "/prompt", json=payload)
        if result.get("error") or not isinstance(result.get("prompt_id"), str) or not result["prompt_id"]:
            raise ComfyError("ComfyUI did not accept the workflow.", details=result)
        return result

    async def upload_image(self, path: Path | str, subfolder: str = "") -> dict:
        # LoadImage's installed choices enumerate input-root files only. Storage
        # supplies UUID basenames; overwrite=false also preserves upstream files.
        file_path = Path(path)
        extensions = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        mime = extensions.get(file_path.suffix.lower())
        if mime is None:
            raise ComfyError("This adapter supports image upload only (PNG, JPEG, WebP). Audio/video require a validated node-specific input adapter.")
        descriptor = _safe_descriptor(file_path.name, subfolder, "input")
        try:
            with file_path.open("rb") as stream:
                header = stream.read(16)
                valid = ((mime == "image/png" and header.startswith(b"\x89PNG\r\n\x1a\n"))
                         or (mime == "image/jpeg" and header.startswith(b"\xff\xd8\xff"))
                         or (mime == "image/webp" and header[:4] == b"RIFF" and header[8:12] == b"WEBP"))
                if not valid:
                    raise ComfyError("Image content does not match the file extension.")
                stream.seek(0)
                result = await self._json("POST", "/upload/image", files={"image": (file_path.name, stream, mime)},
                                          data={"type": "input", "subfolder": descriptor["subfolder"], "overwrite": "false"})
        except OSError as exc:
            raise ComfyError("Image file cannot be opened.", details={"type": type(exc).__name__}) from exc
        if not isinstance(result.get("name"), str):
            raise ComfyError("ComfyUI upload returned no filename.", details=result)
        _safe_descriptor(result["name"], result.get("subfolder", ""), result.get("type", "input"))
        return result

    async def upload_video(self, path: Path | str) -> dict:
        """Stage a library MP4 for the reviewed VHS_LoadVideo input adapter.

        Installed server.py's /upload/image route copies arbitrary multipart
        bytes to input storage; VHS_LoadVideo enumerates MP4s in that root.
        This checks the MP4 container signature, not codecs or video quality.
        Character ownership and the exact mapped node are checked by enqueue
        and again by the worker before calling this transport.
        """
        file_path = Path(path)
        if file_path.suffix.lower() != ".mp4":
            raise ComfyError("The reviewed video input adapter accepts MP4 files only.")
        _safe_descriptor(file_path.name, "", "input")
        try:
            with file_path.open("rb") as stream:
                header = stream.read(32)
                box_size = int.from_bytes(header[:4], "big")
                if (len(header) < 16 or header[4:8] != b"ftyp"
                        or box_size < 16 or box_size > file_path.stat().st_size
                        or header[8:12] in {b"M4A ", b"M4B ", b"M4P ", b"qt  "}):
                    raise ComfyError("Video content does not match the MP4 container extension.")
                stream.seek(0)
                result = await self._json("POST", "/upload/image", files={"image": (file_path.name, stream, "video/mp4")},
                                          data={"type": "input", "subfolder": "", "overwrite": "false"})
        except OSError as exc:
            raise ComfyError("Video file cannot be opened.", details={"type": type(exc).__name__}) from exc
        if not isinstance(result.get("name"), str):
            raise ComfyError("ComfyUI upload returned no video filename.", details=result)
        descriptor = _safe_descriptor(result["name"], result.get("subfolder", ""), result.get("type", "input"))
        if descriptor["subfolder"] or descriptor["type"] != "input" or Path(descriptor["filename"]).suffix.lower() != ".mp4":
            raise ComfyError("ComfyUI must stage the reviewed MP4 in input-root storage.")
        return result

    async def upload_file(self, path: Path | str) -> dict:
        """Stage verified image formats, or MP4 for the reviewed VHS adapter."""
        if Path(path).suffix.lower() == ".mp4":
            return await self.upload_video(path)
        return await self.upload_image(path)

    async def view(self, filename: str, subfolder: str = "", type: str = "output") -> bytes:
        params = _safe_descriptor(filename, subfolder, type)
        try:
            async with self._client.stream("GET", self.base_url + "/view", params=params) as response:
                if response.status_code >= 300:
                    raise ComfyError(f"ComfyUI returned HTTP {response.status_code} for /view.", response.status_code)
                length = response.headers.get("content-length", "")
                if length.isdigit() and int(length) > self.max_output_bytes:
                    raise ComfyError("ComfyUI output exceeds the configured download size limit.")
                output = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(output) + len(chunk) > self.max_output_bytes:
                        raise ComfyError("ComfyUI output exceeds the configured download size limit.")
                    output.extend(chunk)
                return bytes(output)
        except httpx.RequestError as exc:
            raise ComfyError("ComfyUI output could not be downloaded.", details={"type": type(exc).__name__, "route": "/view"}) from exc

    async def download_output(self, output: dict) -> bytes:
        if not isinstance(output, dict):
            raise ComfyError("Output must be a ComfyUI file descriptor.")
        return await self.view(output.get("filename", ""), output.get("subfolder", ""), output.get("type", "output"))

"""Allowlisted media storage with bounded uploads and asset-ID-only reads."""
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import warnings

from fastapi import HTTPException, UploadFile
from PIL import Image

from .db import Database, encode, now, uid

CATEGORIES = {"identity", "character_sheets", "dataset", "outfits", "references", "expressions", "poses", "loras", "audio", "videos"}
ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
Image.MAX_IMAGE_PIXELS = 50_000_000
IMAGE_FORMATS = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"), "WEBP": ("image/webp", ".webp"), "GIF": ("image/gif", ".gif"), "BMP": ("image/bmp", ".bmp")}


def safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(400, "Invalid asset storage path") from exc
    return path


def public_asset(row: dict) -> dict:
    return {k: row[k] for k in ("id", "character_id", "category", "filename", "media_type", "size_bytes", "sha256", "created_at")} | {"url": f"/api/assets/{row['id']}/file", "metadata": json.loads(row["metadata"])}


def sniff_media(path: Path, filename: str, category: str) -> tuple[str, str, dict]:
    with path.open("rb") as handle:
        head = handle.read(4096)
    if not head:
        raise HTTPException(422, "The uploaded file is empty")
    ext = Path(filename).suffix.lower()
    if category == "loras":
        if ext != ".safetensors" or len(head) < 8:
            raise HTTPException(422, "LoRA imports must use the safetensors format; executable pickle formats are not accepted")
        size = path.stat().st_size
        header_size = struct.unpack("<Q", head[:8])[0]
        if header_size < 2 or header_size > min(size - 8, 1024 * 1024):
            raise HTTPException(422, "Invalid safetensors header length")
        try:
            with path.open("rb") as handle:
                handle.seek(8)
                header = json.loads(handle.read(header_size))
            tensors = [v for k, v in header.items() if k != "__metadata__"]
            if not tensors:
                raise ValueError("No tensors")
            for tensor in tensors:
                start, end = tensor["data_offsets"]
                if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end <= size - header_size - 8:
                    raise ValueError("Invalid offsets")
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise HTTPException(422, "Invalid safetensors header") from exc
        return "application/x-safetensors", ".safetensors", {"tensor_count": len(tensors), "compatibility": "unverified"}
    is_image = head.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM")) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")
    if is_image:
        if category in {"audio", "videos"}:
            raise HTTPException(422, "File media type does not match the selected category")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as img:
                    fmt, width, height = img.format, img.width, img.height
                    if fmt not in IMAGE_FORMATS or width * height > Image.MAX_IMAGE_PIXELS:
                        raise ValueError("Unsupported image or oversized dimensions")
                    img.verify()
            media_type, suffix = IMAGE_FORMATS[fmt]
            return media_type, suffix, {"width": width, "height": height, "validation": "decoded_header_and_structure"}
        except Exception as exc:
            raise HTTPException(422, "Invalid image or image dimensions exceed 50 megapixels") from exc
    if category not in {"audio", "videos"}:
        raise HTTPException(422, "This category accepts PNG, JPEG, WEBP, GIF or BMP images")
    if category == "audio":
        if head[:4] == b"RIFF" and head[8:12] == b"WAVE" and ext == ".wav":
            return "audio/wav", ".wav", {"validation": "container_signature"}
        if (head[:3] == b"ID3" or (len(head) > 1 and head[0] == 255 and head[1] & 224 == 224)) and ext == ".mp3":
            return "audio/mpeg", ".mp3", {"validation": "container_signature"}
        if head.startswith(b"fLaC") and ext == ".flac":
            return "audio/flac", ".flac", {"validation": "container_signature"}
        if head.startswith(b"OggS") and ext == ".ogg":
            return "audio/ogg", ".ogg", {"validation": "container_signature"}
        if len(head) > 12 and head[4:8] == b"ftyp" and ext == ".m4a":
            return "audio/mp4", ".m4a", {"validation": "container_signature"}
    if category == "videos":
        if len(head) > 12 and head[4:8] == b"ftyp" and ext in {".mp4", ".mov"}:
            return ("video/mp4", ".mp4", {"validation": "container_signature"}) if ext == ".mp4" else ("video/quicktime", ".mov", {"validation": "container_signature"})
        if head.startswith(b"\x1aE\xdf\xa3") and ext == ".webm":
            return "video/webm", ".webm", {"validation": "container_signature"}
    raise HTTPException(422, "Unsupported or invalid media signature for this category")


class Storage:
    def __init__(self, root: Path, db: Database, max_bytes: int):
        self.root, self.db, self.max_bytes = root.resolve(), db, max_bytes
        (root / "tmp").mkdir(parents=True, exist_ok=True)
        (root / "characters").mkdir(exist_ok=True)
        (root / "workflows").mkdir(exist_ok=True)

    def character_dirs(self, character_id):
        for category in CATEGORIES:
            safe_path(self.root, f"characters/{character_id}/{category}").mkdir(parents=True, exist_ok=True)

    def profile(self, character: dict):
        path = safe_path(self.root, f"characters/{character['id']}/profile.json")
        if path.is_file():
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                previous = {}
            if isinstance(previous, dict):
                character = previous | character
        # Lab pointers come from the additive tables, so a normal profile PATCH
        # cannot erase an approved identity or its immutable revision history.
        lab = self.db.one("SELECT active_revision_id,principal_asset_id,default_outfit_asset_id FROM lab_characters WHERE character_id=?", (character["id"],))
        if lab:
            character = character | {"lab": lab}
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(character, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    async def save_upload(self, character_id: str, category: str, upload: UploadFile):
        if category not in CATEGORIES:
            await upload.close()
            raise HTTPException(422, {"message": "Unsupported asset category", "allowed": sorted(CATEGORIES)})
        asset_id = uid()
        temporary = self.root / "tmp" / f"{asset_id}.part"
        try:
            size = 0
            with temporary.open("xb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise HTTPException(413, "File exceeds configured upload limit")
                    handle.write(chunk)
            return self.register(temporary, character_id, category, upload.filename or "upload", asset_id)
        finally:
            temporary.unlink(missing_ok=True)
            await upload.close()

    def register(self, temporary: Path, character_id: str, category: str, filename: str, asset_id: str | None = None, metadata: dict | None = None, *, connection=None):
        if temporary.stat().st_size > self.max_bytes:
            raise HTTPException(413, "File exceeds configured upload limit")
        media_type, ext, inspected = sniff_media(temporary, filename, category)
        asset_id = asset_id or uid()
        relpath = f"characters/{character_id}/{category}/{asset_id}{ext}"
        final = safe_path(self.root, relpath)
        final.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with temporary.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        clean_name = re.sub(r"[\x00-\x1f\x7f]", "", filename.replace("\\", "/").split("/")[-1])[:200] or f"asset{ext}"
        record = {"id": asset_id, "character_id": character_id, "category": category, "filename": clean_name, "media_type": media_type, "size_bytes": temporary.stat().st_size, "relative_path": relpath, "sha256": digest.hexdigest(), "metadata": encode(inspected | (metadata or {})), "created_at": now()}
        temporary.replace(final)
        try:
            executor = connection or self.db
            executor.execute("INSERT INTO assets(id,character_id,category,filename,media_type,size_bytes,relative_path,sha256,metadata,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", tuple(record.values()))
        except BaseException:
            final.unlink(missing_ok=True)
            raise
        return public_asset(record)

    def asset(self, asset_id: str):
        if not ID_PATTERN.fullmatch(asset_id):
            raise HTTPException(404, "Asset not found")
        row = self.db.one("SELECT * FROM assets WHERE id=?", (asset_id,))
        if not row:
            raise HTTPException(404, "Asset not found")
        return row

    def asset_path(self, asset_id: str):
        row = self.asset(asset_id)
        path = safe_path(self.root, row["relative_path"])
        if not path.is_file():
            raise HTTPException(404, "Asset file is missing from storage")
        return row, path

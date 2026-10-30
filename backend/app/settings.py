"""Operator configuration; paths are never accepted from HTTP callers."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

from .model_setup import discover_comfyui_dir


def _resolve_project_root() -> Path:
    override = os.getenv("CHARACTERLOCK_APP_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _resolve_project_root()


@dataclass
class Settings:
    app_root: Path = field(default_factory=_resolve_project_root)
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("CHARACTERLOCK_DATA_DIR", str(_resolve_project_root() / "data"))).resolve())
    comfy_url: str = field(default_factory=lambda: os.getenv("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/"))
    comfy_proxy_url: str = field(default_factory=lambda: os.getenv("COMFY_BASE_URL", "http://127.0.0.1:8189").rstrip("/"))
    comfy_proxy_autostart: bool = field(default_factory=lambda: os.getenv("CHARACTERLOCK_SDK_AUTOSTART", "true").lower() not in {"0", "false", "no"})
    max_upload_bytes: int = field(default_factory=lambda: int(os.getenv("CHARACTERLOCK_MAX_UPLOAD_MB", "512")) * 1024 * 1024)
    allowed_origins: tuple[str, ...] = field(default_factory=lambda: tuple(x.strip() for x in os.getenv("CHARACTERLOCK_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000").split(",") if x.strip()))
    poll_seconds: float = 2.0
    start_worker: bool = True
    seed_presets: bool = field(default_factory=lambda: os.getenv("CHARACTERLOCK_SEED_PRESETS", "true").lower() not in {"0", "false", "no"})
    comfyui_dir: Path = field(default_factory=lambda: discover_comfyui_dir(_resolve_project_root()))
    comfy_autostart: bool = field(default_factory=lambda: os.getenv("CHARACTERLOCK_COMFYUI_AUTOSTART", "true").lower() not in {"0", "false", "no"})
    engine_startup_timeout: float = field(default_factory=lambda: float(os.getenv("CHARACTERLOCK_COMFYUI_STARTUP_TIMEOUT", "600")))
    engine_probe_seconds: float = 3.0
    engine_monitor_seconds: float = 10.0
    engine_recovery_backoff: float = 10.0

    def __post_init__(self):
        self.app_root = Path(self.app_root).resolve()
        self.data_dir = Path(self.data_dir).resolve()
        self.comfyui_dir = Path(self.comfyui_dir).resolve()
        if self.engine_startup_timeout <= 0 or self.engine_probe_seconds <= 0 or self.engine_monitor_seconds <= 0 or self.engine_recovery_backoff < 0:
            raise ValueError("Engine timing values must be positive; recovery backoff may be zero.")
        parsed = urlparse(self.comfy_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("COMFYUI_URL must be an unauthenticated loopback HTTP origin; remote instances require a future authenticated adapter.")
        if not 1 <= self.max_upload_bytes <= 4 * 1024 ** 3:
            raise ValueError("Upload limit must be between 1 byte and 4 GiB.")
        proxy = urlparse(self.comfy_proxy_url)
        if proxy.scheme != "http" or proxy.hostname not in {"127.0.0.1", "localhost", "::1"} or proxy.username or proxy.password or proxy.query or proxy.fragment or proxy.path not in {"", "/"}:
            raise ValueError("COMFY_BASE_URL must be an unauthenticated loopback HTTP origin for the official local SDK proxy.")
        if (proxy.port or 80) == (parsed.port or 80):
            raise ValueError("ComfyUI and the SDK proxy must use different local ports.")
        for origin in self.allowed_origins:
            p = urlparse(origin)
            if p.scheme != "http" or p.hostname not in {"127.0.0.1", "localhost", "::1"} or p.path or p.query or p.fragment or p.username or p.password:
                raise ValueError("Allowed browser origins must be explicit loopback HTTP origins.")

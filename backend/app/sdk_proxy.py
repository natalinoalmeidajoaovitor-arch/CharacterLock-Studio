"""Hidden official SDK proxy, supervised independently from GPU startup."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

from .db import encode
from .engine_manager import EngineManager


class SDKProxyManager(EngineManager):
    def __init__(self, settings, client, **kwargs):
        proxy_settings = replace(settings, comfy_url=settings.comfy_proxy_url,
                                 comfy_proxy_url=settings.comfy_url,
                                 comfy_autostart=settings.comfy_proxy_autostart,
                                 engine_startup_timeout=45)
        super().__init__(proxy_settings, client, **kwargs)
        self.upstream_url = settings.comfy_url
        self.log_path = settings.data_dir / "logs" / "comfy-sdk-proxy.log"
        self.record_path = settings.data_dir / "sdk-proxy-process.json"

    def set_state(self, state, message):
        super().set_state(state, message.replace("ComfyUI", "proxy do SDK"))

    async def _ready(self):
        return await self.client.proxy_health()

    def _existing_process(self):
        if self.process is not None:
            return self.process.poll() is None
        try:
            record = json.loads(self.record_path.read_text(encoding="utf-8"))
            python = Path(sys.executable).resolve()
            if (record.get("executable") != str(python) or record.get("upstream") != self.upstream_url
                    or record.get("proxy") != self.settings.comfy_url or not self.process_check(record.get("pid"), python)):
                return False
            self.pid, self.owned_process = record["pid"], True
            return True
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    def _spawn(self):
        parsed = urlsplit(self.settings.comfy_url)
        python = Path(sys.executable).resolve()
        command = [str(python), "-m", "comfy_api_proxy.cli", "run", "--comfyui", self.upstream_url,
                   "--host", parsed.hostname, "--port", str(parsed.port or 80),
                   "--state-dir", str(self.settings.data_dir / "sdk-proxy"),
                   "--max-upload-mb", str(max(1, self.settings.max_upload_bytes // (1024 * 1024)))]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        kwargs = {"cwd": str(self.settings.data_dir), "stdin": subprocess.DEVNULL,
                  "stderr": subprocess.STDOUT, "shell": False, "close_fds": True, "env": environment}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        with self.log_path.open("ab", buffering=0) as output:
            self.process = self.process_factory(command, stdout=output, **kwargs)
        self.pid, self.owned_process = self.process.pid, True
        pending = self.record_path.with_suffix(".pending")
        pending.write_text(encode({"pid": self.pid, "executable": str(python),
                                   "upstream": self.upstream_url, "proxy": self.settings.comfy_url}), encoding="utf-8")
        pending.replace(self.record_path)


class LocalEngineStack:
    """One UI status/retry for the engine and its SDK bridge."""
    def __init__(self, engine, proxy):
        self.engine, self.proxy = engine, proxy

    def start(self):
        self.engine.start()
        self.proxy.start()

    async def close(self):
        await self.proxy.close()
        await self.engine.close()

    def snapshot(self):
        engine, proxy = self.engine.snapshot(), self.proxy.snapshot()
        result = dict(engine if engine["state"] != "ready" else proxy)
        result["autostart_enabled"] = engine["autostart_enabled"] or proxy["autostart_enabled"]
        result["can_retry"] = engine["can_retry"] or proxy["can_retry"]
        result.update(comfyui=engine, sdk=proxy)
        if engine["state"] == proxy["state"] == "ready":
            result.update(state="ready", message="ComfyUI e Comfy SDK conectados ao motor local.")
        return result

    def request_start(self):
        self.engine.request_start()
        self.proxy.request_start()
        return self.snapshot()

    def confirm_ready(self):
        self.engine.confirm_ready()
        self.proxy.confirm_ready()
        return self.snapshot()

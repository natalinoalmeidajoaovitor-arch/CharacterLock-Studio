"""Hidden local ComfyUI startup, reuse and bounded recovery; no installation changes."""
import asyncio
from contextlib import suppress
import ctypes
import json
import logging
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit

from .db import encode

log = logging.getLogger("characterlock.engine")


def process_matches(pid: int, executable: Path) -> bool:
    """Read process identity. Never send Windows signals, including os.kill(pid, 0)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                return False
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                return False
            return os.path.normcase(str(Path(buffer.value).resolve())) == os.path.normcase(str(executable.resolve()))
        finally:
            kernel.CloseHandle(handle)
    try:
        return Path(f"/proc/{pid}/exe").resolve(strict=True) == executable.resolve()
    except (OSError, RuntimeError):
        return False


class EngineManager:
    def __init__(self, settings, client, process_factory=None, process_check=None, port_probe=None):
        self.settings, self.client = settings, client
        self.process_factory = process_factory or subprocess.Popen
        self.process_check = process_check or process_matches
        self.port_probe = port_probe or self._port_open
        self.process = None
        self.pid = None
        self.owned_process = False
        self.state = "detecting" if settings.comfy_autostart else "disabled"
        self.message = "Detectando o ComfyUI local." if settings.comfy_autostart else "Inicialização automática desativada pela configuração local."
        self.task = None
        self.automatic_recoveries = 0
        self.wake = asyncio.Event()
        self.lock = asyncio.Lock()
        self.log_path = settings.data_dir / "logs" / "comfyui.log"
        self.record_path = settings.data_dir / "engine-process.json"

    def snapshot(self):
        return {"state": self.state, "message": self.message, "autostart_enabled": self.settings.comfy_autostart,
                "can_retry": self.state in {"failed", "disabled"}, "owned_process": self.owned_process,
                "pid": self.pid, "log_file": self.log_path.name if self.log_path.exists() else None}

    def set_state(self, state, message):
        if self.state != state or self.message != message:
            log.info("Engine %s: %s", state, message)
        self.state, self.message = state, message

    def start(self):
        if self.settings.comfy_autostart:
            self.request_start()

    def request_start(self):
        if self.task and not self.task.done():
            self.wake.set()
            return self.snapshot()
        # An explicit retry gets a fresh budget; observing recovery never does.
        self.automatic_recoveries = 0
        self.set_state("detecting", "Detectando uma instância local antes de iniciar o motor.")
        self.task = asyncio.create_task(self.supervise(), name="characterlock-comfyui-lifecycle")
        return self.snapshot()

    def confirm_ready(self):
        """Reconcile a verified HTTP observation without starting another process."""
        if not self._existing_process():
            self.pid, self.owned_process, self.process = None, False, None
        self.set_state("ready", "ComfyUI conectado e pronto para validar workflows.")
        if self.settings.comfy_autostart and (self.task is None or self.task.done()):
            # Skip startup: the caller has already observed the healthy service.
            # Preserve the recovery budget when resuming a completed monitor.
            self.task = asyncio.create_task(self.supervise(already_ready=True), name="characterlock-comfyui-lifecycle")
        return self.snapshot()

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        # Keep the managed engine running so reopening Studio can reuse it.
        # Never terminate a reused service or an unowned PID.

    @staticmethod
    def responses_ready(stats, info):
        system = stats.get("system", {}) if isinstance(stats, dict) else {}
        return (isinstance(system, dict) and isinstance(system.get("comfyui_version"), str)
                and isinstance(system.get("python_version"), str) and isinstance(stats.get("devices"), list)
                and isinstance(info, dict) and bool(info))

    async def _ready(self):
        try:
            stats, info = await asyncio.wait_for(asyncio.gather(self.client.system_stats(), self.client.object_info()), timeout=5)
            return self.responses_ready(stats, info)
        except asyncio.CancelledError:
            raise
        except Exception:
            return False

    async def _port_open(self):
        parsed = urlsplit(self.settings.comfy_url)
        writer = None
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(parsed.hostname, parsed.port or 80), timeout=1)
            return True
        except (OSError, asyncio.TimeoutError):
            return False
        finally:
            if writer:
                writer.close()
                with suppress(OSError):
                    await writer.wait_closed()

    def _existing_process(self):
        if self.process is not None:
            return self.process.poll() is None
        try:
            record = json.loads(self.record_path.read_text(encoding="utf-8"))
            expected = self.settings.comfyui_dir / "python_embeded" / "python.exe"
            if record.get("executable") != str(expected) or not self.process_check(record.get("pid"), expected):
                return False
            self.pid = record["pid"]
            self.owned_process = True  # Recognized managed process from a prior Studio session.
            return True
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    def _spawn(self):
        directory = self.settings.comfyui_dir
        python = directory / "python_embeded" / "python.exe"
        main = directory / "ComfyUI" / "main.py"
        if not python.is_file() or not main.is_file():
            raise RuntimeError("A instalação ComfyUI Portable configurada não foi encontrada. Configure CHARACTERLOCK_COMFYUI_DIR para a instalação existente; nenhum componente será instalado automaticamente.")
        parsed = urlsplit(self.settings.comfy_url)
        host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
        command = [str(python), "-s", str(main), "--windows-standalone-build", "--disable-auto-launch", "--listen", host, "--port", str(parsed.port or 80)]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        kwargs = {"cwd": str(directory), "stdin": subprocess.DEVNULL, "stderr": subprocess.STDOUT, "shell": False, "close_fds": True, "env": environment}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        with self.log_path.open("ab", buffering=0) as output:
            output.write(b"\n--- CharacterLock Studio: starting existing ComfyUI Portable ---\n")
            self.process = self.process_factory(command, stdout=output, **kwargs)
        self.pid, self.owned_process = self.process.pid, True
        pending = self.record_path.with_suffix(".pending")
        pending.write_text(encode({"pid": self.pid, "executable": str(python)}), encoding="utf-8")
        pending.replace(self.record_path)

    async def ensure_running(self):
        async with self.lock:
            self.set_state("detecting", "Verificando se o ComfyUI local já está disponível.")
            if await self._ready():
                # Reuse any healthy local instance without spawning or replacing it.
                if not self._existing_process():
                    self.pid, self.owned_process, self.process = None, False, None
                self.set_state("ready", "ComfyUI conectado e pronto para validar workflows.")
                return True
            managed_alive = self._existing_process()
            occupied = await self.port_probe()
            if not managed_alive and not occupied:
                try:
                    self.set_state("starting", "Iniciando o ComfyUI existente em segundo plano.")
                    self._spawn()
                except Exception as exc:
                    self.set_state("failed", str(exc))
                    return False
            else:
                self.set_state("waiting", "Aguardando a instância local já em inicialização; nenhum segundo processo será aberto.")
            deadline = time.monotonic() + self.settings.engine_startup_timeout
            while time.monotonic() < deadline:
                if await self._ready():
                    self.set_state("ready", "ComfyUI conectado e pronto para validar workflows.")
                    return True
                if self.process is not None and self.process.poll() is not None:
                    self.set_state("failed", f"O ComfyUI encerrou durante a inicialização (código {self.process.returncode}). Consulte {self.log_path.name}.")
                    return False
                self.set_state("waiting", "O ComfyUI está carregando seus componentes. A aplicação continuará aguardando em segundo plano.")
                await asyncio.sleep(self.settings.engine_probe_seconds)
            self.set_state("failed", f"O ComfyUI não respondeu dentro do tempo de inicialização. Consulte {self.log_path.name}; um processo ainda ativo não será duplicado.")
            return False

    async def supervise(self, already_ready=False):
        try:
            if not already_ready and not await self.ensure_running():
                return
            misses = 0
            while True:
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=self.settings.engine_monitor_seconds)
                except asyncio.TimeoutError:
                    pass
                if await self._ready():
                    misses = 0
                    continue
                misses += 1
                if misses < 3:
                    continue
                if self.automatic_recoveries >= 1:
                    self.set_state("failed", f"A conexão com o ComfyUI foi perdida após uma recuperação automática. Consulte {self.log_path.name} e tente novamente no Studio.")
                    return
                self.automatic_recoveries += 1
                self.set_state("waiting", "Conexão perdida. Preparando uma única tentativa automática de recuperação.")
                await asyncio.sleep(self.settings.engine_recovery_backoff)
                if not await self.ensure_running():
                    return
                misses = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Unexpected engine lifecycle failure")
            self.set_state("failed", f"Não foi possível iniciar o motor local: {exc}")

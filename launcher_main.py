"""CharacterLock Studio — Windows Executable & Portable Launcher Entrypoint."""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _load_dotenv_if_present(root: Path) -> None:
    env_file = root / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("\"'")
        if k and k not in os.environ:
            os.environ[k] = v


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) != 0


def _pick_port(host: str, preferred: int) -> int:
    if _port_free(host, preferred):
        return preferred
    for candidate in range(preferred + 1, preferred + 15):
        if _port_free(host, candidate):
            return candidate
    raise RuntimeError(f"No available TCP port found in range {preferred}..{preferred + 14}")


def _open_browser_when_ready(url: str) -> None:
    import httpx

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{url}/api/health", timeout=2.0)
            if r.status_code == 200:
                webbrowser.open(url)
                return
        except Exception:
            pass
        time.sleep(0.5)


def main() -> int:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    # Intercept internal SDKProxyManager subprocess invocation (`-m comfy_api_proxy.cli ...`)
    if len(sys.argv) >= 3 and sys.argv[1] == "-m" and sys.argv[2] == "comfy_api_proxy.cli":
        from comfy_api_proxy.cli import main as proxy_main

        sys.argv = ["comfy-api-proxy", *sys.argv[3:]]
        result = proxy_main()
        return int(result) if isinstance(result, int) else 0

    root = _app_root()
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(root / "backend"))

    os.environ.setdefault("CHARACTERLOCK_APP_ROOT", str(root))
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    _load_dotenv_if_present(root)

    parser = argparse.ArgumentParser(prog="CharacterLockStudio", description="CharacterLock Studio — Local AI Character Production Studio")
    parser.add_argument("--host", default="127.0.0.1", help="Loopback bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Preferred HTTP port (default: 8000)")
    parser.add_argument("--comfyui-dir", default=None, help="Path to existing ComfyUI_windows_portable directory")
    parser.add_argument("--data-dir", default=None, help="Path to local Studio library directory")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser window automatically")
    parser.add_argument("--check-models", action="store_true", help="Inspect hardware, ComfyUI, custom nodes, and model manifest, then exit")
    parser.add_argument("--setup-models", action="store_true", help="Run interactive CharacterLock Model Setup downloader")
    parser.add_argument("--modules", default="all", help="Comma-separated modules for --setup-models / --check-models")
    parser.add_argument("--install-custom-nodes", action="store_true", help="Install missing ComfyUI custom nodes during --setup-models")
    parser.add_argument("--yes", action="store_true", help="Confirm model downloads non-interactively during --setup-models")
    args = parser.parse_args()

    if args.comfyui_dir:
        os.environ["CHARACTERLOCK_COMFYUI_DIR"] = str(Path(args.comfyui_dir).resolve())
    if args.data_dir:
        os.environ["CHARACTERLOCK_DATA_DIR"] = str(Path(args.data_dir).resolve())

    from app.model_setup import discover_comfyui_dir, inspect_environment, inspect_models_and_nodes, load_manifest, run_interactive_cli

    if args.check_models or args.setup_models:
        cli_args = ["--modules", args.modules]
        if args.comfyui_dir:
            cli_args.extend(["--comfyui-dir", args.comfyui_dir])
        if args.check_models and not args.setup_models:
            cli_args.append("--check-only")
        if args.install_custom_nodes:
            cli_args.append("--install-custom-nodes")
        if args.yes:
            cli_args.append("--yes")
        return run_interactive_cli(cli_args, app_root=root)

    if args.host not in {"127.0.0.1", "localhost"}:
        print("Error: CharacterLock Studio binds strictly to local loopback (127.0.0.1 / localhost).")
        return 2

    port = _pick_port("127.0.0.1", args.port)
    origins = {
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
    }
    existing_origins = os.getenv("CHARACTERLOCK_ALLOWED_ORIGINS", "")
    for item in existing_origins.split(","):
        if item.strip():
            origins.add(item.strip())
    os.environ["CHARACTERLOCK_ALLOWED_ORIGINS"] = ",".join(sorted(origins))

    comfy_dir = discover_comfyui_dir(root)
    env_info = inspect_environment(root, comfy_dir)
    manifest = load_manifest(root)
    model_info = inspect_models_and_nodes(manifest, comfy_dir)

    studio_url = f"http://127.0.0.1:{port}"
    print("=" * 72)
    print("  CHARACTERLOCK STUDIO v1.0.0 — Open Source Higgsfield Edition")
    print("  Create once. Keep the character. Produce everything.")
    print("=" * 72)
    if env_info["gpus"]:
        g = env_info["gpus"][0]
        print(f"  GPU            : {g['name']} ({g['vram_gb']} GB VRAM)")
    print(f"  ComfyUI        : {comfy_dir} ({'DETECTED' if env_info['comfyui']['installed'] else 'NOT DETECTED - set CHARACTERLOCK_COMFYUI_DIR'})")
    s = model_info["summary"]
    print(f"  Models         : {s['installed_models']}/{s['total_models']} verified")
    if s["missing_models"] > 0:
        print(f"  Model Setup    : {s['missing_models']} model file(s) missing ({s['missing_download_gb']} GB). Run 'Setup-Models.bat' or '--setup-models' to download.")
    print(f"  Studio URL     : {studio_url}")
    print("  Press Ctrl+C to stop CharacterLock Studio.")
    print("=" * 72)

    if not args.no_browser:
        threading.Thread(target=_open_browser_when_ready, args=(studio_url,), daemon=True).start()

    import uvicorn
    from app.main import create_app

    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())

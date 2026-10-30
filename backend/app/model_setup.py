"""CharacterLock Model Setup: hardware inspection, ComfyUI discovery, and verified resumable model downloader."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx

STUDIO_MODULES = ("character_lab", "dataset", "video_studio", "voice", "motion_swap")


def discover_comfyui_candidates(app_root: Path | None = None) -> list[Path]:
    """Return candidate ComfyUI Portable root directories in priority order."""
    candidates: list[Path] = []
    env_dir = os.getenv("CHARACTERLOCK_COMFYUI_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir))
    if app_root is not None:
        candidates.append(app_root / "ComfyUI_windows_portable")
        candidates.append(app_root.parent / "ComfyUI_windows_portable")
    home = Path.home()
    candidates.extend([
        home / "ComfyUI_windows_portable",
        Path("C:/ComfyUI_windows_portable"),
        Path("D:/ComfyUI_windows_portable"),
        home / "Documents" / "ComfyUI_windows_portable",
        home / "Desktop" / "ComfyUI_windows_portable",
        home / "Downloads" / "ComfyUI_windows_portable",
    ])
    seen = set()
    unique: list[Path] = []
    for p in candidates:
        try:
            resolved = p.resolve()
        except OSError:
            resolved = p
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def is_valid_comfyui_portable(path: Path) -> bool:
    return (path / "ComfyUI" / "main.py").is_file() or (path / "main.py").is_file()


def resolve_comfyui_base(comfyui_dir: Path) -> Path:
    """Return the root such that `<root>/ComfyUI/models/...` resolves cleanly."""
    if (comfyui_dir / "ComfyUI" / "main.py").is_file():
        return comfyui_dir
    if comfyui_dir.name.lower() == "comfyui" and (comfyui_dir / "main.py").is_file():
        return comfyui_dir.parent
    return comfyui_dir


def discover_comfyui_dir(app_root: Path | None = None) -> Path:
    candidates = discover_comfyui_candidates(app_root)
    for c in candidates:
        if is_valid_comfyui_portable(c):
            return resolve_comfyui_base(c)
    return candidates[0]


def _get_ram_bytes() -> int | None:
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return int(stat.ullTotalPhys)
    return None


def _probe_nvidia_gpu() -> list[dict[str, Any]]:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi and os.name == "nt":
        fallback = Path("C:/Windows/System32/nvidia-smi.exe")
        if fallback.is_file():
            nvidia_smi = str(fallback)
    if not nvidia_smi:
        return []
    try:
        proc = subprocess.run(
            [nvidia_smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if proc.returncode != 0:
            return []
        gpus = []
        for line in proc.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                try:
                    vram_mb = int(float(parts[1]))
                except ValueError:
                    vram_mb = None
                gpus.append({
                    "name": parts[0],
                    "vram_mb": vram_mb,
                    "vram_gb": round(vram_mb / 1024, 2) if vram_mb else None,
                    "driver_version": parts[2],
                })
        return gpus
    except Exception:
        return []


def _probe_comfyui_installation(comfyui_dir: Path) -> dict[str, Any]:
    base = resolve_comfyui_base(comfyui_dir)
    comfy_code = base / "ComfyUI"
    py_exe = base / "python_embeded" / "python.exe"
    if not py_exe.is_file():
        venv_py = comfy_code / ".venv" / "Scripts" / "python.exe"
        if venv_py.is_file():
            py_exe = venv_py
    installed = (comfy_code / "main.py").is_file()
    info: dict[str, Any] = {
        "installed": installed,
        "root_exists": base.exists(),
        "has_embedded_python": py_exe.is_file(),
        "comfyui_version": None,
        "python_version": None,
        "torch_version": None,
        "cuda_available": None,
        "installed_custom_nodes": [],
    }
    if not installed:
        return info

    # Read ComfyUI version safely without exposing personal paths
    ver_file = comfy_code / "comfyui_version.py"
    if ver_file.is_file():
        for line in ver_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "__version__" in line and "=" in line:
                info["comfyui_version"] = line.split("=", 1)[1].strip().strip("\"'")
                break

    custom_nodes_dir = comfy_code / "custom_nodes"
    if custom_nodes_dir.is_dir():
        info["installed_custom_nodes"] = sorted(
            p.name for p in custom_nodes_dir.iterdir()
            if p.is_dir() and not p.name.startswith((".", "__"))
        )

    if py_exe.is_file():
        try:
            proc = subprocess.run(
                [
                    str(py_exe),
                    "-s",
                    "-c",
                    "import json, sys; d={'py': sys.version.split()[0]}; "
                    "import torch; d['torch']=torch.__version__; d['cuda']=bool(torch.cuda.is_available()); "
                    "print(json.dumps(d))",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                parsed = json.loads(proc.stdout.strip().splitlines()[-1])
                info["python_version"] = parsed.get("py")
                info["torch_version"] = parsed.get("torch")
                info["cuda_available"] = parsed.get("cuda")
        except Exception:
            pass
    return info


def load_manifest(app_root: Path) -> dict[str, Any]:
    manifest_path = app_root / "models-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"models-manifest.json not found in {app_root}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def inspect_models_and_nodes(
    manifest: dict[str, Any],
    comfyui_dir: Path,
    selected_modules: list[str] | None = None,
) -> dict[str, Any]:
    base = resolve_comfyui_base(comfyui_dir)
    modules_filter = set(selected_modules or STUDIO_MODULES)
    comfy_info = _probe_comfyui_installation(base)
    installed_node_folders = {n.lower() for n in comfy_info["installed_custom_nodes"]}

    models_report = []
    missing_bytes = 0
    installed_count = 0
    missing_count = 0

    for item in manifest.get("models", []):
        item_modules = set(item.get("modules", []))
        if not (item_modules & modules_filter):
            continue
        target = base / Path(item["install_relpath"])
        matched_file = None
        actual_size = None
        if target.is_file() and target.stat().st_size > 0:
            matched_file = target.name
            actual_size = target.stat().st_size
        else:
            for alias in item.get("accepted_aliases", []):
                alias_path = target.parent / alias
                if alias_path.is_file() and alias_path.stat().st_size > 0:
                    matched_file = alias_path.name
                    actual_size = alias_path.stat().st_size
                    break

        is_present = matched_file is not None
        accepted_sizes = set(item.get("accepted_sizes", [])) | {item["size_bytes"]}
        size_matches = is_present and (
            actual_size in accepted_sizes or matched_file != item["filename"]
        )
        status = "installed" if (is_present and size_matches) else ("size_mismatch" if is_present else "missing")
        if status == "installed":
            installed_count += 1
        else:
            missing_count += 1
            missing_bytes += int(item["size_bytes"])

        models_report.append({
            "id": item["id"],
            "name": item["name"],
            "category": item["category"],
            "filename": item["filename"],
            "matched_filename": matched_file,
            "install_relpath": item["install_relpath"],
            "repo_id": item["repo_id"],
            "url": item["url"],
            "size_bytes": item["size_bytes"],
            "actual_size_bytes": actual_size,
            "sha256": item["sha256"],
            "license": item["license"],
            "gated": bool(item.get("gated", False)),
            "required": bool(item.get("required", True)),
            "modules": item["modules"],
            "status": status,
        })

    nodes_report = []
    for node in manifest.get("custom_nodes", []):
        node_modules = set(node.get("modules", []))
        if not (node_modules & modules_filter):
            continue
        present = node["folder"].lower() in installed_node_folders
        nodes_report.append({
            "name": node["name"],
            "folder": node["folder"],
            "git_url": node["git_url"],
            "modules": node["modules"],
            "license": node["license"],
            "pip_packages": node.get("pip_packages", []),
            "installed": present,
        })

    disk_target = base if base.exists() else Path.cwd()
    disk = shutil.disk_usage(disk_target)

    return {
        "selected_modules": sorted(modules_filter),
        "models": models_report,
        "summary": {
            "total_models": len(models_report),
            "installed_models": installed_count,
            "missing_models": missing_count,
            "missing_download_bytes": missing_bytes,
            "missing_download_gb": round(missing_bytes / (1024 ** 3), 2),
            "disk_free_bytes": disk.free,
            "disk_free_gb": round(disk.free / (1024 ** 3), 2),
            "sufficient_disk_space": disk.free > int(missing_bytes * 1.05) + 512 * 1024 * 1024,
        },
        "custom_nodes": nodes_report,
    }


def inspect_environment(app_root: Path, comfyui_dir: Path) -> dict[str, Any]:
    """Inspect local OS, GPU, VRAM, RAM, disk, ComfyUI, and downloader tools without leaking user paths."""
    ram_bytes = _get_ram_bytes()
    gpus = _probe_nvidia_gpu()
    base = resolve_comfyui_base(comfyui_dir)
    disk_target = base if base.exists() else app_root
    disk = shutil.disk_usage(disk_target)
    comfy = _probe_comfyui_installation(base)
    return {
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "ram_gb": round(ram_bytes / (1024 ** 3), 2) if ram_bytes else None,
        "gpus": gpus,
        "disk": {
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "free_gb": round(disk.free / (1024 ** 3), 2),
        },
        "comfyui": comfy,
        "tools": {
            "aria2c_available": shutil.which("aria2c") is not None,
            "git_available": shutil.which("git") is not None,
        },
    }


def compute_sha256(path: Path, progress_cb: Callable[[int, int], None] | None = None) -> str:
    digest = hashlib.sha256()
    total = path.stat().st_size
    done = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            done += len(chunk)
            if progress_cb:
                progress_cb(done, total)
    return digest.hexdigest()


def download_file_resumable(
    url: str,
    dest: Path,
    expected_size: int,
    expected_sha256: str,
    hf_token: str | None = None,
    use_aria2c: bool = True,
    log_fn: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Download with HTTP Range resume (or aria2c when installed) and verify exact byte size + SHA-256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size == expected_size:
        log_fn(f"[VERIFY] Existing file found: {dest.name} — verifying SHA-256...")
        actual_hash = compute_sha256(dest)
        if actual_hash.lower() == expected_sha256.lower():
            log_fn(f"[OK] Verified already installed: {dest.name}")
            return {"status": "already_verified", "sha256": actual_hash, "bytes": expected_size}
        log_fn(f"[WARN] Hash mismatch on existing {dest.name}; re-downloading.")

    part = dest.with_name(dest.name + ".part")
    aria2c = shutil.which("aria2c") if use_aria2c else None

    if aria2c and not hf_token:
        cmd = [
            aria2c,
            "--continue=true",
            "--max-connection-per-server=8",
            "--split=8",
            "--min-split-size=16M",
            "--dir", str(part.parent),
            "--out", part.name,
            url,
        ]
        log_fn(f"[ARIA2C] Downloading {dest.name} ({expected_size / (1024**2):.1f} MiB)...")
        res = subprocess.run(cmd, check=False)
        if res.returncode != 0:
            log_fn("[WARN] aria2c exited non-zero; falling back to built-in HTTP Range downloader.")

    headers: dict[str, str] = {"User-Agent": "CharacterLockStudio-ModelSetup/1.0"}
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"

    if not part.is_file() or part.stat().st_size < expected_size:
        existing_bytes = part.stat().st_size if part.is_file() else 0
        if existing_bytes > expected_size:
            part.unlink()
            existing_bytes = 0
        req_headers = dict(headers)
        mode = "wb"
        if existing_bytes > 0:
            req_headers["Range"] = f"bytes={existing_bytes}-"
            mode = "ab"
            log_fn(f"[RESUME] Resuming {dest.name} at {existing_bytes / (1024**2):.1f} MiB...")
        else:
            log_fn(f"[DOWNLOAD] Downloading {dest.name} ({expected_size / (1024**2):.1f} MiB)...")

        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, connect=20.0)) as client:
            with client.stream("GET", url, headers=req_headers) as resp:
                if resp.status_code in (401, 403):
                    raise PermissionError(
                        f"Access denied ({resp.status_code}) for {url}. "
                        "Accept upstream license terms on Hugging Face and set HF_TOKEN in your environment if required."
                    )
                if existing_bytes > 0 and resp.status_code == 200:
                    # Server ignored Range; restart cleanly
                    existing_bytes = 0
                    mode = "wb"
                resp.raise_for_status()
                downloaded = existing_bytes
                last_log = time.monotonic()
                with part.open(mode) as out:
                    for chunk in resp.iter_bytes(chunk_size=4 * 1024 * 1024):
                        if not chunk:
                            continue
                        out.write(chunk)
                        downloaded += len(chunk)
                        now_t = time.monotonic()
                        if now_t - last_log >= 2.0 or downloaded == expected_size:
                            pct = (downloaded / expected_size * 100.0) if expected_size else 100.0
                            log_fn(f"  -> {dest.name}: {downloaded / (1024**2):.1f} / {expected_size / (1024**2):.1f} MiB ({pct:.1f}%)")
                            last_log = now_t

    actual_size = part.stat().st_size
    if actual_size != expected_size:
        raise IOError(f"Incomplete download for {dest.name}: expected {expected_size} bytes, got {actual_size} bytes")

    log_fn(f"[VERIFY] Computing SHA-256 for {dest.name}...")
    actual_sha = compute_sha256(part)
    if actual_sha.lower() != expected_sha256.lower():
        raise ValueError(
            f"SHA-256 integrity check failed for {dest.name}: expected {expected_sha256}, got {actual_sha}"
        )

    part.replace(dest)
    log_fn(f"[SUCCESS] Installed & verified {dest.name} (SHA-256 OK)")
    return {"status": "downloaded_and_verified", "sha256": actual_sha, "bytes": actual_size}


def install_missing_custom_nodes(
    manifest: dict[str, Any],
    comfyui_dir: Path,
    selected_modules: list[str] | None = None,
    log_fn: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Clone missing custom nodes into an existing ComfyUI installation without touching existing ones."""
    base = resolve_comfyui_base(comfyui_dir)
    comfy_code = base / "ComfyUI"
    if not (comfy_code / "main.py").is_file():
        raise RuntimeError(f"ComfyUI installation not found at {base}. Install ComfyUI Portable first.")
    git_bin = shutil.which("git")
    if not git_bin:
        raise RuntimeError("Git is required to clone missing ComfyUI custom nodes.")

    custom_nodes_dir = comfy_code / "custom_nodes"
    custom_nodes_dir.mkdir(parents=True, exist_ok=True)
    py_exe = base / "python_embeded" / "python.exe"
    modules_filter = set(selected_modules or STUDIO_MODULES)

    results = []
    for node in manifest.get("custom_nodes", []):
        if not (set(node.get("modules", [])) & modules_filter):
            continue
        target = custom_nodes_dir / node["folder"]
        if target.exists():
            log_fn(f"[SKIP] Custom node already present: {node['folder']}")
            results.append({"folder": node["folder"], "status": "already_present"})
            continue
        log_fn(f"[CLONE] Cloning {node['name']} from {node['git_url']}...")
        subprocess.run([git_bin, "clone", "--depth", "1", node["git_url"], str(target)], check=True)
        req_txt = target / "requirements.txt"
        if py_exe.is_file() and req_txt.is_file():
            log_fn(f"[PIP] Installing requirements for {node['folder']}...")
            subprocess.run([str(py_exe), "-s", "-m", "pip", "install", "-r", str(req_txt)], check=False)
        for pkg in node.get("pip_packages", []):
            if py_exe.is_file():
                log_fn(f"[PIP] Installing package '{pkg}' (--no-deps) for {node['folder']}...")
                subprocess.run([str(py_exe), "-s", "-m", "pip", "install", "--no-deps", pkg], check=False)
        results.append({"folder": node["folder"], "status": "installed"})
    return results


def run_interactive_cli(argv: list[str] | None = None, app_root: Path | None = None) -> int:
    import argparse

    root = app_root or (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2])
    parser = argparse.ArgumentParser(prog="CharacterLock Model Setup", description="Inspect environment and download verified ComfyUI models modularly.")
    parser.add_argument("--comfyui-dir", type=str, default=None, help="Path to ComfyUI_windows_portable root directory.")
    parser.add_argument("--modules", type=str, default="all", help="Comma-separated modules: character_lab,dataset,video_studio,voice,motion_swap or 'all'.")
    parser.add_argument("--check-only", action="store_true", help="Inspect hardware, ComfyUI, custom nodes, and models without downloading.")
    parser.add_argument("--verify-installed", action="store_true", help="Verify full SHA-256 hashes of already installed models.")
    parser.add_argument("--install-custom-nodes", action="store_true", help="Clone any missing ComfyUI custom nodes for selected modules.")
    parser.add_argument("--yes", action="store_true", help="Confirm downloads non-interactively.")
    args = parser.parse_args(argv)

    comfy_dir = resolve_comfyui_base(Path(args.comfyui_dir)) if args.comfyui_dir else discover_comfyui_dir(root)
    selected = list(STUDIO_MODULES) if args.modules.strip().lower() == "all" else [
        m.strip() for m in args.modules.split(",") if m.strip() in STUDIO_MODULES
    ]
    if not selected:
        print(f"Error: no valid modules selected. Choose from: {', '.join(STUDIO_MODULES)}")
        return 2

    manifest = load_manifest(root)
    env = inspect_environment(root, comfy_dir)
    report = inspect_models_and_nodes(manifest, comfy_dir, selected)

    print("=" * 72)
    print("  CHARACTERLOCK MODEL SETUP — Environment & Dependency Check")
    print("=" * 72)
    print(f"  OS            : {env['os']['system']} {env['os']['release']} ({env['os']['machine']})")
    print(f"  System RAM    : {env['ram_gb']} GB")
    if env["gpus"]:
        for gpu in env["gpus"]:
            print(f"  GPU           : {gpu['name']} ({gpu['vram_gb']} GB VRAM, Driver {gpu['driver_version']})")
    else:
        print("  GPU           : No NVIDIA GPU detected via nvidia-smi")
    print(f"  ComfyUI Dir   : {comfy_dir} ({'FOUND' if env['comfyui']['installed'] else 'NOT FOUND'})")
    if env["comfyui"]["installed"]:
        print(f"  ComfyUI Ver   : {env['comfyui']['comfyui_version']} | Python {env['comfyui']['python_version']} | Torch {env['comfyui']['torch_version']} (CUDA={env['comfyui']['cuda_available']})")
    print(f"  Disk Free     : {report['summary']['disk_free_gb']} GB")
    print(f"  Modules       : {', '.join(report['selected_modules'])}")
    print("-" * 72)
    print("  MODELS STATUS:")
    for m in report["models"]:
        size_mb = m["size_bytes"] / (1024 ** 2)
        tag = "OK     " if m["status"] == "installed" else "MISSING"
        alias_note = f" (via {m['matched_filename']})" if m["matched_filename"] and m["matched_filename"] != m["filename"] else ""
        print(f"    [{tag}] {m['filename']}{alias_note} ({size_mb:.1f} MiB) [{','.join(m['modules'])}]")
    print("-" * 72)
    print("  CUSTOM NODES STATUS:")
    for n in report["custom_nodes"]:
        tag = "OK     " if n["installed"] else "MISSING"
        print(f"    [{tag}] {n['folder']} ({n['git_url']})")
    print("-" * 72)
    s = report["summary"]
    print(f"  Installed: {s['installed_models']}/{s['total_models']} models | Missing download: {s['missing_download_gb']} GB")
    print("=" * 72)

    if args.verify_installed:
        for m in report["models"]:
            if m["status"] == "installed" and m["matched_filename"] == m["filename"]:
                target = comfy_dir / Path(m["install_relpath"])
                print(f"[SHA256] Checking {target.name}...")
                actual = compute_sha256(target)
                if actual.lower() != m["sha256"].lower():
                    print(f"  [FAIL] {target.name}: expected {m['sha256']}, got {actual}")
                    return 1
                print(f"  [PASS] {target.name}")

    if args.check_only:
        return 0

    if args.install_custom_nodes:
        install_missing_custom_nodes(manifest, comfy_dir, selected)

    missing = [m for m in report["models"] if m["status"] != "installed"]
    if not missing:
        print("\nAll required models for the selected modules are already installed!")
        return 0

    if not s["sufficient_disk_space"]:
        print(f"\nError: Insufficient free disk space ({s['disk_free_gb']} GB free, {s['missing_download_gb']} GB required).")
        return 1

    if not args.yes:
        ans = input(f"\nDownload {len(missing)} missing model file(s) ({s['missing_download_gb']} GB) into '{comfy_dir}'? [y/N]: ").strip().lower()
        if ans not in {"y", "yes"}:
            print("Download cancelled by user. No files were downloaded.")
            return 0

    hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    for m in missing:
        dest = comfy_dir / Path(m["install_relpath"])
        download_file_resumable(
            url=m["url"],
            dest=dest,
            expected_size=int(m["size_bytes"]),
            expected_sha256=m["sha256"],
            hf_token=hf_token,
        )

    print("\nCharacterLock Model Setup completed and verified all selected models!")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_interactive_cli())

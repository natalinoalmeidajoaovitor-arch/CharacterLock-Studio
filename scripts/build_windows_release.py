"""Reproducible builder for CharacterLockStudio.exe and CharacterLockStudio-Windows-x64.zip."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_OUT = REPO_ROOT.parent / "dist_package"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def build() -> int:
    frontend_dist = REPO_ROOT / "frontend" / "dist" / "index.html"
    if not frontend_dist.is_file():
        raise RuntimeError("Frontend bundle (frontend/dist/index.html) not found. Build frontend before packaging.")

    build_root = REPO_ROOT.parent / "pyinstaller_work"
    venv_dir = REPO_ROOT.parent / "build_venv"
    py_exe = venv_dir / "Scripts" / "python.exe"

    if not py_exe.is_file():
        print("[1/4] Creating isolated packaging virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        subprocess.run([str(py_exe), "-m", "pip", "install", "--upgrade", "pip"], check=True)
        subprocess.run([str(py_exe), "-m", "pip", "install", "-r", str(REPO_ROOT / "backend" / "requirements.txt"), "pyinstaller"], check=True)

    if build_root.exists():
        shutil.rmtree(build_root)
    if RELEASE_OUT.exists():
        shutil.rmtree(RELEASE_OUT)
    build_root.mkdir(parents=True, exist_ok=True)
    RELEASE_OUT.mkdir(parents=True, exist_ok=True)

    print("[2/4] Compiling CharacterLockStudio.exe with PyInstaller...")
    pyinstaller_cmd = [
        str(py_exe),
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name", "CharacterLockStudio",
        "--paths", str(REPO_ROOT / "backend"),
        "--collect-submodules", "app",
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "comfy_sdk",
        "--collect-submodules", "comfy_low",
        "--collect-submodules", "comfy_api_proxy",
        "--copy-metadata", "comfy-sdk",
        "--copy-metadata", "comfy-api-proxy",
        "--collect-submodules", "aiohttp",
        "--collect-submodules", "multipart",
        "--collect-submodules", "python_multipart",
        "--distpath", str(build_root / "dist"),
        "--workpath", str(build_root / "work"),
        "--specpath", str(build_root),
        str(REPO_ROOT / "launcher_main.py"),
    ]
    subprocess.run(pyinstaller_cmd, check=True)

    bundle_dir = build_root / "dist" / "CharacterLockStudio"
    exe_path = bundle_dir / "CharacterLockStudio.exe"
    if not exe_path.is_file():
        raise RuntimeError(f"Expected executable not produced: {exe_path}")

    print("[3/4] Staging portable Windows x64 distribution directory (clean library)...")
    stage_dir = RELEASE_OUT / "CharacterLockStudio"
    shutil.copytree(bundle_dir, stage_dir)

    # Copy prebuilt frontend SPA, redistributable workflow presets, model manifest, licenses, and helpers
    shutil.copytree(REPO_ROOT / "frontend" / "dist", stage_dir / "frontend" / "dist")
    shutil.copytree(REPO_ROOT / "workflows" / "presets", stage_dir / "workflows" / "presets")
    for fname in ("models-manifest.json", "Setup-Models.bat", "LICENSE", "THIRD_PARTY_LICENSES.md", ".env.example"):
        shutil.copy2(REPO_ROOT / fname, stage_dir / fname)

    (stage_dir / "README-WINDOWS.txt").write_text(
        "========================================================================\r\n"
        "  CharacterLock Studio v1.0.0 — Open Source Higgsfield Edition\r\n"
        "  Create once. Keep the character. Produce everything.\r\n"
        "========================================================================\r\n\r\n"
        "QUICK START (WINDOWS x64):\r\n\r\n"
        "1. COMFYUI PORTABLE:\r\n"
        "   Ensure ComfyUI Portable (ComfyUI_windows_portable) is located at\r\n"
        "   %USERPROFILE%\\ComfyUI_windows_portable or C:\\ComfyUI_windows_portable.\r\n"
        "   (If yours is in another folder, copy .env.example to .env and set\r\n"
        "   CHARACTERLOCK_COMFYUI_DIR=D:\\Your\\Path\\ComfyUI_windows_portable)\r\n\r\n"
        "2. MODEL & CUSTOM NODE SETUP (FIRST RUN):\r\n"
        "   Double-click 'Setup-Models.bat' (or run 'CharacterLockStudio.exe --setup-models')\r\n"
        "   to inspect your GPU/VRAM and download models modularly with SHA-256 verification.\r\n\r\n"
        "3. LAUNCH CHARACTERLOCK STUDIO:\r\n"
        "   Double-click 'CharacterLockStudio.exe'.\r\n"
        "   The Studio starts with a clean local library, seeds all 16 validated API\r\n"
        "   workflows, connects to ComfyUI + Comfy SDK, and opens http://127.0.0.1:8000.\r\n\r\n"
        "LICENSE:\r\n"
        "   Application code: MIT License (see LICENSE).\r\n"
        "   Third-party nodes & model weights: see THIRD_PARTY_LICENSES.md.\r\n",
        encoding="utf-8",
    )

    # Empty data folder marker so user sees clean portable layout; DB created on first boot
    (stage_dir / "data").mkdir(exist_ok=True)

    zip_path = RELEASE_OUT / "CharacterLockStudio-Windows-x64.zip"
    print(f"[4/4] Compressing {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in sorted(stage_dir.rglob("*")):
            rel = item.relative_to(RELEASE_OUT)
            if item.is_dir():
                continue
            zf.write(item, rel.as_posix())

    # Verify ZIP integrity
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad is not None:
            raise RuntimeError(f"Corrupt entry in ZIP: {bad}")

    digest = sha256_file(zip_path)
    sha_path = RELEASE_OUT / "CharacterLockStudio-Windows-x64.zip.sha256"
    sha_path.write_text(f"{digest}  CharacterLockStudio-Windows-x64.zip\n", encoding="utf-8")

    size_mb = zip_path.stat().st_size / (1024 ** 2)
    print("=" * 72)
    print(f"  PACKAGE READY : {zip_path}")
    print(f"  SIZE          : {zip_path.stat().st_size} bytes ({size_mb:.2f} MiB)")
    print(f"  SHA-256       : {digest}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(build())

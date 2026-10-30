# Installation & Model Setup Guide

CharacterLock Studio runs **100% locally on Windows x64** on top of an existing **ComfyUI Portable** installation (`ComfyUI_windows_portable`). You can run it either from the standalone Windows executable (`CharacterLockStudio.exe`) or directly from source.

---

## Tested Hardware & Software Environment

- **Operating System:** Windows 10 / Windows 11 (x64)
- **Validated Reference GPU:** NVIDIA GeForce RTX 5060 Ti **16 GB VRAM** (CUDA 13.0 / PyTorch 2.14)
- **System RAM:** 16 GB minimum tested (32 GB recommended when switching rapidly between Qwen 2.1 and MiniMax H3)
- **Disk Space:**
  - Application (`CharacterLockStudio-Windows-x64.zip` extracted): ~150 MB
  - Character Lab + Dataset models (Qwen Image 2.1): ~13.3 GB
  - Voice Studio models (OmniVoice): ~3.1 GB
  - Video Studio + Motion Swap models (MiniMax H3 + Qwen3-VL 32B GGUF + VAEs + LoRAs): ~40.3 GB
  - Full 5-module model suite: ~57 GB

---

## Option A — Standalone Windows Executable (Recommended)

No Python, Node.js, React, or PowerShell configuration is required to run the Studio UI and backend.

1. **Install or reuse ComfyUI Portable:**
   - If you already have `ComfyUI_windows_portable` at `%USERPROFILE%\ComfyUI_windows_portable` or `C:\ComfyUI_windows_portable`, CharacterLock Studio detects and reuses it automatically without modifying or reinstalling it.
   - If you do not have ComfyUI Portable yet, download the official release from https://github.com/comfyanonymous/ComfyUI/releases and extract `ComfyUI_windows_portable` to `C:\ComfyUI_windows_portable` (or `%USERPROFILE%\ComfyUI_windows_portable`).
   - If your ComfyUI folder is in a custom location, create a `.env` file next to `CharacterLockStudio.exe` with:
     ```ini
     CHARACTERLOCK_COMFYUI_DIR=D:\Path\To\ComfyUI_windows_portable
     ```

2. **Extract `CharacterLockStudio-Windows-x64.zip`:**
   - Download `CharacterLockStudio-Windows-x64.zip` from [GitHub Releases](https://github.com/CharacterLock-Studio) and extract it to any folder (e.g., `C:\CharacterLockStudio`).

3. **Run `Setup-Models.bat` (CharacterLock Model Setup):**
   - Double-click `Setup-Models.bat` (or run `CharacterLockStudio.exe --setup-models`).
   - It inspects your GPU, VRAM, RAM, free disk space, ComfyUI installation, custom nodes, and installed weights against [`models-manifest.json`](../models-manifest.json).
   - You can install models **modularly** so you only download the studios you need:
     ```bat
     REM Check environment & models without downloading anything:
     CharacterLockStudio.exe --check-models

     REM Install missing ComfyUI custom nodes + models for Character Lab & Voice Studio only:
     CharacterLockStudio.exe --setup-models --modules character_lab,voice --install-custom-nodes

     REM Install the complete 5-module studio suite:
     CharacterLockStudio.exe --setup-models --modules all --install-custom-nodes
     ```
   - Downloads support automatic HTTP `Range` resume (`aria2c` accelerated when installed) and verify **exact byte length + SHA-256 hash** before finalizing each file.

4. **Launch `CharacterLockStudio.exe`:**
   - Double-click `CharacterLockStudio.exe`.
   - It starts the local Studio server (`http://127.0.0.1:8000`), connects to (or starts) ComfyUI (`127.0.0.1:8188`) and the official Comfy SDK proxy (`127.0.0.1:8189`), seeds all 16 studio API workflows on first boot, and opens the Studio in your browser.

---

## Option B — Running from Source (Developers)

### Prerequisites
- Python 3.11+
- Node.js 20+ (with `pnpm` or `npm`)
- Git
- ComfyUI Portable (`ComfyUI_windows_portable`)

### Steps
```powershell
git clone https://github.com/<owner>/CharacterLock-Studio.git
cd CharacterLock-Studio

# 1. Create .venv, install Python backend + Comfy SDK deps, and build React frontend:
.\scripts\setup.ps1

# 2. Inspect hardware, ComfyUI custom nodes, and model manifest:
.\.venv\Scripts\python.exe scripts\model_setup.py --check-only

# 3. Optional: install missing custom nodes & download models for selected modules:
.\.venv\Scripts\python.exe scripts\model_setup.py --modules all --install-custom-nodes

# 4. Launch CharacterLock Studio on http://127.0.0.1:8000:
.\scripts\open-studio.ps1
```

---

## Manual Model & Custom Node Placement (Fallback Reference)

If you prefer to manage ComfyUI custom nodes and model files manually without running `model_setup.py`, consult [`models-manifest.json`](../models-manifest.json) for the exact Hugging Face URLs, SHA-256 hashes, and target paths:

- `ComfyUI/models/diffusion_models/`
  - `qwen_image_2.1_int8_convrot.safetensors`
  - `Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors`
- `ComfyUI/models/text_encoders/`
  - `qwen3vl_8b_w4a8.safetensors`
  - `qwen3vl_32b_minimax_h3-Q2_K_M.gguf` (or `qwen3vl-32B-MiniMax-H3-Q2_K.gguf`)
- `ComfyUI/models/vae/`
  - `qwen_image_2.1_vae_bf16.safetensors`
  - `minimax_h3_video_vae_int8_convrot.safetensors`
  - `minimax_h3_video_vae_fp16.safetensors`
  - `minimax_h3_audio_vae_fp32.safetensors`
- `ComfyUI/models/loras/`
  - `h3-realism-people-t2v-i2v-r2v.safetensors`
  - `minimax_h3_fl2v_lightx2v_turbo_8step_v1.0_resized_avg_rank_24_bf16.safetensors`
  - `h3_character_swap_pro4500_1000.safetensors`
- `ComfyUI/models/omnivoice/`
  - `model.safetensors`, `config.json`, `tokenizer.json`, `tokenizer_config.json`
  - `audio_tokenizer/model.safetensors`, `audio_tokenizer/config.json`, `audio_tokenizer/preprocessor_config.json`

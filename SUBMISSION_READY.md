# Competition Submission Kit — Open Source Higgsfield (Comfy.org)

- **Official Competition Portal:** https://comfy.org/open-source-higgsfield
- **Deadline:** October 30, 2026 — 09:00 PT (13:00 BRT)
- **Release Tag:** `v1.0.0` (`CharacterLock Studio v1.0.0 — Open Source Higgsfield Edition`)

> **Note:** CharacterLock Studio does **not** submit the competition Typeform automatically. Review the fields below, publish your social media announcement post to obtain the **Social Post URL**, and submit manually at https://comfy.org/open-source-higgsfield.

---

## Form Fields (Ready to Copy & Paste — English)

### Project Name
```text
CharacterLock Studio
```

### Tagline
```text
Create once. Keep the character. Produce everything.
```

### Short Description
```text
CharacterLock Studio is an open-source, local-first AI character production studio built on ComfyUI and the official Comfy SDK. Define a character once with a 9-view Character Sheet (Qwen Image 2.1), curate a persistent multi-angle Dataset, synthesize expressive multilingual speech (OmniVoice), generate identity-consistent scenes (MiniMax H3), and transfer real human performances onto your locked character via Motion Swap (MiniMax H3 Ref2VA + Character Swap LoRA) — orchestrated locally on 16 GB consumer GPUs with automatic VRAM management.
```

### GitHub URL
```text
https://github.com/natalinoalmeidajoaovitor-arch/CharacterLock-Studio
```

### Release URL (Windows x64 Executable + Checksums)
```text
https://github.com/natalinoalmeidajoaovitor-arch/CharacterLock-Studio/releases/tag/v1.0.0
```

### Demo URL (< 2 Minutes Real Product Walkthrough — 68.25s, 1080p)
```text
https://github.com/natalinoalmeidajoaovitor-arch/CharacterLock-Studio/releases/download/v1.0.0/characterlock-studio-demo.mp4
```
*(Also available directly in the repository at `examples/characterlock-studio-demo.mp4`, or upload `examples/characterlock-studio-demo.mp4` natively to YouTube / X when posting.)*

### Social Post URL
```text
[PENDING USER ACTION — Publish your post on X / Twitter, LinkedIn, or Reddit attaching examples/characterlock-studio-demo.mp4 and the GitHub URL, then paste the live post link here]
```

### Technology
```text
- Core Engine & Orchestration: ComfyUI (local execution) + Official Comfy SDK (comfy-sdk 0.5.0 & comfy-api-proxy 0.1.6) + AIModelMemoryManager (automatic inter-stage VRAM unloading & thermal/memory supervision for 16 GB GPUs).
- Character Lab & 9-View Sheet: Qwen Image 2.1 (qwen_image_edit_2511_bf16 + Lightning 4-step LoRA + Multi-Angle Character Sheet LoRA).
- Character Dataset Studio: MATRIX Qwen multi-expression & multi-angle dataset generation with persistent SQLite + filesystem asset indexing.
- Video Studio: MiniMax H3 14B INT8 + ConvRot INT8 Video VAE + UMT5-XXL FP8 for identity-locked cinematic video synthesis.
- Voice Studio: OmniVoice multilingual zero-shot voice cloning & expressive speech synthesis bound to each character profile.
- Motion Swap Studio: MiniMax H3 Ref2VA + Character Swap LoRA + native aspect-preserving reference preparation, transferring real actor body/facial performance while preserving original camera framing, scene lighting, and secondary subjects.
- Application Stack: Python 3.12 / FastAPI async backend, React 19 + Vite dark-studio SPA, standalone Windows x64 PyInstaller bundle (CharacterLockStudio.exe), and modular SHA-256 resumable model downloader (models-manifest.json).
```

### Open Source License
```text
MIT License (application source code, UI, backend, launcher, downloader, and redistributable API workflow presets). Third-party ComfyUI custom nodes and upstream model weights remain governed by their respective upstream licenses, documented in THIRD_PARTY_LICENSES.md.
```

### Installation
```text
Option A — Windows x64 Standalone Release (No Python or Node.js install required):
1. Install or keep an existing ComfyUI Portable folder (ComfyUI_windows_portable) with an NVIDIA CUDA GPU (16 GB+ VRAM recommended; verified on RTX 5060 Ti 16 GB).
2. Download and extract CharacterLockStudio-Windows-x64.zip from GitHub Releases to any directory.
3. Run Setup-Models.bat (or CharacterLockStudio.exe --setup-models) to verify hardware, install required ComfyUI custom nodes, and download selected studio model weights modularly (~36.2 GB full studio) with HTTP Range resume and SHA-256 verification.
4. Launch CharacterLockStudio.exe — seeds all 16 redistributable ComfyUI API workflows into a clean local library, supervises ComfyUI + Comfy SDK Proxy, and opens http://127.0.0.1:8000.

Option B — Run from Source:
1. git clone https://github.com/natalinoalmeidajoaovitor-arch/CharacterLock-Studio.git && cd CharacterLock-Studio
2. powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
3. python scripts\model_setup.py
4. powershell -ExecutionPolicy Bypass -File scripts\open-studio.ps1
```

### Innovation
```text
Cloud character-video platforms lock creators behind proprietary subscriptions and disconnected single-shot tools. CharacterLock Studio turns ComfyUI + Comfy SDK into a cohesive, 100% local character-centric production studio where character identity is a first-class persistent entity:

1. End-to-End Persistent Identity Pipeline: A single character profile unifies a 9-view Character Sheet, curated multi-angle Dataset references, cloned OmniVoice vocal identity, MiniMax H3 video scenes, and Motion Swap actor replacement without manual node wiring.
2. Scene-Faithful Motion Swap on 16 GB Consumer Hardware: Solves reference aspect-distortion and framing collapse in MiniMax H3 Ref2VA Character Swap so creators can replace only the target performer in multi-person scenes while preserving camera geometry, background lighting, and natural body gestures.
3. Zero-Node-Graph UX Powered by Official Comfy SDK: Supervises ComfyUI and comfy-api-proxy behind a studio-grade interface while AIModelMemoryManager dynamically unloads heavy diffusion/video/audio pipelines between stages so Qwen Image, MiniMax H3, and OmniVoice coexist reliably on a single 16 GB GPU.
```

---

## Suggested Social Announcement Copy (X / LinkedIn)

```text
Introducing CharacterLock Studio v1.0.0 — an open-source, 100% local AI character production studio built on @ComfyUI & the official Comfy SDK for #OpenSourceHiggsfield!

Create once. Keep the character. Produce everything:
- 9-View Character Sheet (Qwen Image 2.1)
- Persistent Multi-Angle Dataset
- Identity-Locked Video Studio (MiniMax H3)
- Neural Voice Studio (OmniVoice)
- Scene-Preserving Motion Swap (MiniMax H3 Ref2VA)

Runs locally on a 16 GB GPU (tested on RTX 5060 Ti 16 GB) with a standalone Windows executable + MIT license.

GitHub & Windows Release: https://github.com/natalinoalmeidajoaovitor-arch/CharacterLock-Studio
```

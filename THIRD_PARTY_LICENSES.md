# Third-Party Licenses & Model Notices

**CharacterLock Studio** original source code (frontend, backend, launcher, model setup configurator, and redistributable workflow parameter mappings) is licensed under the **MIT License** (see [`LICENSE`](LICENSE)).

> **Important:** External runtimes, ComfyUI custom nodes, diffusion checkpoints, text encoders, VAEs, voice synthesis weights, and LoRAs are **not** bundled inside the Git repository or the Windows release archive (`CharacterLockStudio-Windows-x64.zip`). They are separate components governed by their own respective upstream licenses and terms of use. Do not assume that the MIT License of CharacterLock Studio automatically grants commercial rights to third-party model weights.

---

## 1. Local AI Engine & SDK

| Component | Upstream Repository | License | Usage in CharacterLock Studio |
| :--- | :--- | :--- | :--- |
| **ComfyUI** | https://github.com/comfyanonymous/ComfyUI | GPL-3.0 | External local inference server (`http://127.0.0.1:8188`), invoked via HTTP/WebSocket API as an independent process. |
| **Comfy SDK (`comfy-sdk` & `comfy-api-proxy`)** | https://pypi.org/project/comfy-sdk/ | Apache-2.0 / MIT | Official local job submission, status tracking, and WebSocket proxy (`http://127.0.0.1:8189`). |

---

## 2. Application Runtime Libraries

| Component | License | Role |
| :--- | :--- | :--- |
| **React & React DOM** | MIT | Studio frontend user interface |
| **Vite & TypeScript** | MIT / Apache-2.0 | Frontend build toolchain |
| **FastAPI & Starlette** | MIT / BSD-3-Clause | Local loopback HTTP & WebSocket API |
| **Uvicorn** | BSD-3-Clause | ASGI local server |
| **Pydantic** | MIT | Strict schema validation |
| **HTTPX & Websockets** | BSD-3-Clause | Async HTTP Range downloader & engine communication |
| **Pillow (PIL)** | HPND (MIT-like) | Image header verification and dimension inspection |

---

## 3. ComfyUI Custom Nodes (Installed Externally in ComfyUI)

CharacterLock Studio connects to an existing ComfyUI installation (`ComfyUI_windows_portable`) where the following custom nodes execute the studio workflows:

| Custom Node | Upstream Repository | License | Studio Modules |
| :--- | :--- | :--- | :--- |
| **MATRIX-LAB-Nodes** | https://github.com/JsonMatrixLab/MATRIX-LAB-Nodes | Upstream Repository Terms | Character Lab, Dataset |
| **ComfyUI-Fantastic-MiniMaxH3-PromptBuilder** | https://github.com/Adudeguyman/ComfyUI-Fantastic-MiniMaxH3-PromptBuilder | Upstream Repository Terms | Character Lab, Dataset, Video Studio, Motion Swap |
| **ComfyUI-GGUF** | https://github.com/city96/ComfyUI-GGUF | Apache-2.0 | Video Studio, Motion Swap |
| **ComfyUI-KJNodes** | https://github.com/kijai/ComfyUI-KJNodes | GPL-3.0 | Character Lab, Dataset, Video Studio, Motion Swap |
| **ComfyUI-VideoHelperSuite** | https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite | GPL-3.0 | Video Studio, Motion Swap |
| **rgthree-comfy** | https://github.com/rgthree/rgthree-comfy | MIT | Motion Swap |
| **ComfyUI-Omnivoice** | https://github.com/wildminder/ComfyUI-Omnivoice | Apache-2.0 / Upstream Terms | Voice Studio |

---

## 4. Model Weights & LoRAs (Downloaded On-Demand by User)

When using `CharacterLock Model Setup` (`Setup-Models.bat` or `python scripts/model_setup.py`), files are downloaded directly from their official Hugging Face repositories only after user confirmation:

| Model / LoRA | Official Repository | Upstream License / Terms | Studio Modules |
| :--- | :--- | :--- | :--- |
| **Qwen Image 2.1 (`qwen_image_2.1_int8_convrot`, `qwen_image_2.1_vae_bf16`)** | `Comfy-Org/Qwen-Image-2.1` | Apache-2.0 | Character Lab, Dataset |
| **Qwen3-VL 8B (`qwen3vl_8b_w4a8`)** | `Comfy-Org/Qwen-Image-2.1` | Apache-2.0 | Character Lab, Dataset |
| **MiniMax H3 Singularity Ref2VA (`Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8`)** | `WarmBloodAban/Minimax-h3_Singularity` | Upstream MiniMax H3 Derivative Terms — verify commercial restrictions on Hugging Face before commercial deployment | Video Studio, Motion Swap |
| **MiniMax H3 Video & Audio VAEs** | `Comfy-Org/MiniMax-H3` | Upstream MiniMax H3 Terms | Video Studio, Motion Swap |
| **Qwen3-VL 32B MiniMax H3 GGUF** | `unsloth/MiniMax-H3-GGUF` | Upstream MiniMax H3 / Qwen Terms | Video Studio, Motion Swap |
| **MiniMax H3 Realism People LoRA** | `fal/MiniMax-H3-Realism-People-LoRA` | Upstream fal / MiniMax H3 LoRA Terms | Video Studio, Motion Swap |
| **MiniMax H3 LightX2V Turbo 8-Step LoRA** | `Kijai/MiniMax-H3_comfy` | Apache-2.0 / Upstream MiniMax H3 Terms | Video Studio, Motion Swap |
| **MiniMax H3 Character Swap LoRA (`h3_character_swap_pro4500_1000`)** | `akatz-ai/MiniMax-H3-Character-Swap-LoRA` | Apache-2.0 / Upstream MiniMax H3 Terms | Motion Swap |
| **OmniVoice (`k2-fsa/OmniVoice`)** | `k2-fsa/OmniVoice` | Apache-2.0 | Voice Studio |

---

## 5. Ethical & Consent Policy

CharacterLock Studio enforces explicit consent confirmation (`consent_confirmed=true`) across character creation, reference uploads, and generation requests. Users are solely responsible for ensuring they hold appropriate rights and consent for any likeness, image, video, or voice imported into their local library.

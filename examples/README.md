# CharacterLock Studio — Curated Real Examples

Every file in this folder is an authentic, unedited generation produced locally by **CharacterLock Studio** running on Windows with an **NVIDIA GeForce RTX 5060 Ti (16 GB VRAM)**, **ComfyUI Portable**, and the official **Comfy SDK**.

## Included Showcase Files

| File | Studio Module | Model / Pipeline | Description |
| :--- | :--- | :--- | :--- |
| `characterlock-studio-demo.mp4` | Full Studio | End-to-End Pipeline | Complete `<120s` showcase walkthrough of CharacterLock Studio (1920x1080 MP4 with OmniVoice & Motion Swap audio). |
| `motion-swap-before-after.mp4` | Motion Swap | MiniMax H3 Ref2VA + `h3_character_swap_pro4500_1000` LoRA | Synchronized side-by-side comparison: original two-speaker studio video (left) vs. Clara Hayes character transfer (right), preserving exact framing, camera, left speaker, and orange background. |
| `clara-hayes-motion-swap-5s.mp4` | Motion Swap | `minimax-h3-motion-swap-5s` | Raw 5-second Motion Swap output video generated locally. |
| `clara-hayes-character-sheet-9view.png` | Character Lab | Qwen Image 2.1 (`qwen21-sheet-9view-description`) | 9-view Character Sheet created from Clara Hayes's identity description. |
| `clara-hayes-identity-portrait.png` | Character Lab | Qwen Image 2.1 | Approved primary face/upper-body portrait (`<Picture 1>`) reused automatically across Dataset, Video Studio, and Motion Swap. |
| `dataset/clara-hayes-01..05-*.png` | Dataset | MATRIX Qwen 2.1 (`matrix-qwen21-dataset-quick5`) | Consistent multi-angle and expression dataset generated from the approved Character Sheet anchors. |
| `clara-hayes-video-studio-minimax-h3.mp4` | Video Studio | MiniMax H3 Realism + Turbo 8 (`minimax-h3-video-realism-turbo8`) | Reference-to-video scene generated directly from Clara Hayes's approved identity portrait. |
| `clara-hayes-omnivoice-en.mp3` | Voice Studio | OmniVoice (`omnivoice-local-narration`) | English voice narration synthesized locally via OmniVoice auto-voice. |
| `sofia-reis-character-sheet-9view.png` | Character Lab | Qwen Image 2.1 (`qwen21-sheet-9view-reference`) | Second character identity demonstrating multi-character library management. |
| `sofia-reis-omnivoice-narration.mp3` | Voice Studio | OmniVoice (`omnivoice-local-narration`) | Portuguese voice narration synthesized locally via OmniVoice. |

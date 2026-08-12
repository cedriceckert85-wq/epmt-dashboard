"""LoL Clip Lab — Local Edit Studio (V2, test edition).

Runs entirely on ONE PC from an already-downloaded VOD. No streaming, no
network, no OBS, no Tailscale. Its only job is the creative core: pull
context out of a match VOD (transcript + audio reactions + optional game
events), find the funny / hype / clutch / callback moments, and produce an
EDIT SHEET — punchline-aware cut points plus caption / zoom / SFX
suggestions — that you review and cut.

Tuned for an AMD box (Ryzen 7 5800X3D + Radeon RX 9070 XT): Whisper runs on
CPU by default (no CUDA needed), rendering uses AMD AMF or CPU x264 (no
NVENC needed).
"""
__version__ = "2.0.0-local"

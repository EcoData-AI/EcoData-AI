"""GAIA's voice layer — Milestone 3, first slice: push-to-talk STT + TTS.

Mirrors `gaia.llm` and `gaia.tools` deliberately: a small provider ABC
(`base.py`), a registry that is the single place engines are known
(`registry.py`), one module per engine. See `base.py`'s docstring for why
this stays a peer of those two families rather than folding into either.
"""

from __future__ import annotations

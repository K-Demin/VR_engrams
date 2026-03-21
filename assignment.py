from __future__ import annotations

import hashlib
import random
from typing import Iterable

_SESSION_RANDOM_ASSIGNMENTS: dict[tuple[str, tuple[str, ...], int | None], str] = {}


def _normalize_allowed(allowed: Iterable[str]) -> list[str]:
    scenes = [str(scene) for scene in allowed]
    if not scenes:
        raise ValueError("allowed must contain at least one scene")
    return scenes


def assign_target_scene(
    mouse_id: str,
    strategy: str,
    seed: int | None,
    allowed: list[str] | tuple[str, ...] = ["A", "B"],
) -> str:
    """
    Resolve target-scene assignment.

    Supported strategies:
    - deterministic hash-based assignment per mouse ID (default aliases supported)
    - seeded random assignment recorded once per process session
    """
    scenes = _normalize_allowed(allowed)
    strategy_name = (strategy or "deterministic_hash").strip().lower()

    if strategy_name in {
        "deterministic_hash",
        "hash",
        "blocked_by_mouse_id",
        "mouse_hash",
        "default",
    }:
        digest = hashlib.sha256(str(mouse_id).encode("utf-8")).digest()
        return scenes[int.from_bytes(digest[:8], "big") % len(scenes)]

    if strategy_name in {"seeded_random_session", "seeded_random_once", "seeded_random"}:
        cache_key = (strategy_name, tuple(scenes), seed)
        if cache_key not in _SESSION_RANDOM_ASSIGNMENTS:
            rng = random.Random(seed)
            _SESSION_RANDOM_ASSIGNMENTS[cache_key] = rng.choice(scenes)
        return _SESSION_RANDOM_ASSIGNMENTS[cache_key]

    raise ValueError(f"Unsupported scene assignment strategy: {strategy}")

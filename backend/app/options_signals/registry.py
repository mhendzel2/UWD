from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).resolve().parent


def load_feature_registry() -> dict[str, Any]:
    path = _ROOT / "feature_registry.json"
    return json.loads(path.read_text())


def load_signal_registry() -> dict[str, Any]:
    path = _ROOT / "signal_registry.json"
    return json.loads(path.read_text())


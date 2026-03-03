from __future__ import annotations

import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")

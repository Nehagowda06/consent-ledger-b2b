from __future__ import annotations

import json
from typing import Any

from fastapi.exceptions import RequestValidationError


def _validation_error(message: str) -> RequestValidationError:
    return RequestValidationError(
        [{"loc": ("body",), "msg": message, "type": "value_error.jsondecode"}]
    )


def validate_strict_json_object(raw: bytes) -> dict[str, Any]:
    def _object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise _validation_error("Duplicate JSON keys are not allowed")
            obj[key] = value
        return obj

    try:
        # LTS invariant: duplicate JSON keys are rejected to keep canonical
        # verification semantics deterministic across parsers.
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_pairs_hook)
    except RequestValidationError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise _validation_error("Invalid JSON payload")

    if not isinstance(parsed, dict):
        raise _validation_error("JSON body must be an object")
    return parsed

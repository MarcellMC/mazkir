"""Schema-validation pre-hook.

Validates tool input against the JSON Schema declared in the tool registry
entry. Catches failure modes that Claude SDK's loose schema enforcement lets
through, in particular:

- Missing required fields
- additionalProperties violations
- Wrong types (e.g. JSON-encoded string passed where object is expected)
"""

from typing import Any, Optional

import jsonschema

from src.services.tool_response import ErrorCode, err


def validate_schema(params: dict, ctx: Any) -> Optional[dict]:
    """Validate `params` against `ctx['tool']['schema']['input_schema']`.

    Returns None on success, an error response on failure.

    `ctx` must contain `tool` mapping with the tool registry entry. Hooks
    that want to ignore validation simply aren't registered.
    """
    tool = ctx["tool"]
    schema = tool["schema"]["input_schema"]
    try:
        jsonschema.validate(params, schema)
    except jsonschema.ValidationError as e:
        return err(
            ErrorCode.SCHEMA_INVALID,
            f"Input schema violation: {e.message}",
            details={
                "path": list(e.absolute_path),
                "schema_path": list(e.schema_path),
            },
        )
    return None

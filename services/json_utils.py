"""
Parse JSON do LLM tra ve mot cach "de tinh".

LLM hay tra ve chuoi co ky tu xuong dong that nam trong string literal
(vi du dot_code, code) -> json.loads mac dinh bao
"Invalid control character at: line N column M".
Module nay boc fence, cat lay object, va don dep truoc khi parse.
"""
import json
import re
from typing import Any, Dict

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _escape_control_chars(text: str) -> str:
    """Escape cac ky tu dieu khien tho nam ben trong string literal."""
    out = []
    in_string = False
    escaped = False
    for char in text:
        if in_string and not escaped and char < " ":
            out.append(_ESCAPES.get(char, "\\u%04x" % ord(char)))
            continue
        out.append(char)
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            in_string = not in_string
    return "".join(out)


def _attempts(text: str):
    cleaned = _FENCE.sub("", text.strip())
    yield cleaned

    start, end = cleaned.find("{"), cleaned.rfind("}")
    candidate = cleaned[start : end + 1] if start != -1 and end > start else cleaned
    if candidate != cleaned:
        yield candidate

    yield _escape_control_chars(candidate)
    yield _TRAILING_COMMA.sub(r"\1", _escape_control_chars(candidate))


def parse_json_loose(text: str) -> Dict[str, Any]:
    """Tra ve dict, hoac raise ValueError kem thong bao doc duoc."""
    last_error: Exception | None = None
    for candidate in _attempts(text):
        if not candidate.strip():
            continue
        try:
            # strict=False: cho phep ky tu dieu khien tho trong string.
            value = json.loads(candidate, strict=False)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(value, dict):
            raise ValueError("AI response must be a JSON object")
        return value

    raise ValueError("AI response is not valid JSON (%s)" % last_error)

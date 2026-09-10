"""Extract bounded, public-facing prose from ordinary assistant text blocks only."""

from __future__ import annotations

import re

from customer_signal.observability.langfuse import sanitize_trace_value

_PRIVATE_MARKUP = re.compile(r"<(?:think|thinking|reasoning)\b|```|\bSELECT\b[\s\S]*\bFROM\b", re.I)
_CUSTOMER_ID = re.compile(r"customer[_-][a-z0-9_-]+", re.I)
_CREDENTIAL = re.compile(
    r"\b(?:Bearer\s+\S+|(?:api[_-]?key|secret|password|token)\s*[:=]\s*\S+|sk-[a-z0-9_-]{12,})",
    re.I,
)


def public_model_text(content: object) -> str | None:
    """Never stringify tool calls, metadata, thought/reasoning blocks or provider objects."""
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [
            block["text"] for block in content
            if isinstance(block, dict) and block.get("type") == "text"
            and not block.get("thought") and not block.get("reasoning")
            and isinstance(block.get("text"), str)
        ]
    else:
        return None
    text = "\n\n".join(part.strip() for part in parts if part.strip())
    if not text or text.startswith(("{", "[")) or _PRIVATE_MARKUP.search(text):
        return None
    text = _CREDENTIAL.sub("[인증 정보 숨김]", text)
    text = _CUSTOMER_ID.sub("[고객 식별자 숨김]", text)
    text = sanitize_trace_value(text)
    return text if len(text) <= 1000 else text[:999].rstrip() + "…"

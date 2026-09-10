"""Opaque HMAC-signed cursors for derived exploration result pages."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_CURSOR_VERSION = "1"
_MAX_CURSOR_BYTES = 16_384
_SIGNATURE_BYTES = hashlib.sha256().digest_size


class CursorValidationError(ValueError):
    """A cursor is malformed, forged, stale, or belongs to another query."""


class CursorPayload(BaseModel):
    """Server-owned lineage bound into every derived-result cursor."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal["1"] = _CURSOR_VERSION
    run_id: str = Field(min_length=1, max_length=128)
    generation: int = Field(strict=True, ge=0)
    query_fingerprint: str = Field(min_length=16, max_length=128)
    snapshot_id: str = Field(min_length=16, max_length=128)
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    result_kind: str = Field(min_length=1, max_length=64)
    query_ref: str = Field(min_length=1, max_length=128)
    result_ref: str = Field(min_length=1, max_length=128)
    page_index: int = Field(strict=True, ge=1)
    page_size: int = Field(default=50, strict=True, ge=1, le=200)
    last_sort_key: str = Field(min_length=1, max_length=8_192)

    @field_validator("source_ids", mode="before")
    @classmethod
    def freeze_source_ids(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("source_ids")
    @classmethod
    def validate_source_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(value)) or len(value) != len(set(value)):
            raise ValueError("cursor source_ids must be sorted and unique")
        return value


def canonical_json(value: object) -> str:
    """Return stable, type-preserving JSON used by keys and fingerprints."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    )


def query_fingerprint(value: object) -> str:
    """Hash a normalized Tool input after its transport-only cursor is removed."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python", exclude={"cursor"}, exclude_none=False)
    elif isinstance(value, Mapping):
        value = {key: item for key, item in value.items() if key != "cursor"}
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def snapshot_fingerprint(snapshot_tokens: Mapping[str, str]) -> str:
    """Hash sorted source snapshot tokens without exposing them to the Agent."""

    return hashlib.sha256(
        canonical_json(sorted(snapshot_tokens.items())).encode("utf-8")
    ).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise TypeError("naive datetime is not canonical JSON")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(f"value of type {type(value).__name__} is not JSON serializable")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not value or any(character.isspace() for character in value):
        raise CursorValidationError("cursor encoding is invalid")
    try:
        raw = value.encode("ascii")
        padded = raw + b"=" * (-len(raw) % 4)
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as error:
        raise CursorValidationError("cursor encoding is invalid") from error
    if _b64encode(decoded) != value:
        raise CursorValidationError("cursor encoding is not canonical")
    return decoded


class CursorCodec:
    """Encode and validate opaque cursors with a process-provided HMAC key."""

    def __init__(self, secret: bytes) -> None:
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("cursor secret must contain at least 32 bytes")
        self._secret = bytes(secret)

    def encode(self, payload: CursorPayload) -> str:
        body = canonical_json(
            payload.model_dump(mode="json", exclude_none=True)
        ).encode("utf-8")
        supplied = hmac.new(self._secret, body, hashlib.sha256).digest()
        token = f"{_b64encode(body)}.{_b64encode(supplied)}"
        if len(token.encode("ascii")) > _MAX_CURSOR_BYTES:
            raise CursorValidationError("cursor exceeds the maximum encoded size")
        return token

    def decode(self, token: str) -> CursorPayload:
        if not isinstance(token, str) or len(token.encode("utf-8")) > _MAX_CURSOR_BYTES:
            raise CursorValidationError("cursor is invalid or too large")
        if token.count(".") != 1:
            raise CursorValidationError("cursor must contain exactly two segments")
        encoded_body, encoded_signature = token.split(".", 1)
        body = _b64decode(encoded_body)
        supplied = _b64decode(encoded_signature)
        if len(supplied) != _SIGNATURE_BYTES:
            raise CursorValidationError("cursor signature is invalid")
        expected = hmac.new(self._secret, body, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected):
            raise CursorValidationError("cursor signature is invalid")
        try:
            json.loads(body)
            payload = CursorPayload.model_validate_json(body)
        except (json.JSONDecodeError, ValueError) as error:
            raise CursorValidationError("cursor payload is invalid") from error
        if canonical_json(payload.model_dump(mode="json", exclude_none=True)).encode(
            "utf-8"
        ) != body:
            raise CursorValidationError("cursor payload is not canonical")
        return payload

    def decode_and_validate(
        self,
        token: str,
        *,
        run_id: str,
        generation: int,
        query_fingerprint: str,
        snapshot_id: str,
        source_ids: Sequence[str],
        result_kind: str,
        page_size: int | None = None,
    ) -> CursorPayload:
        payload = self.decode(token)
        expected_sources = tuple(sorted(source_ids))
        checks: tuple[tuple[bool, str], ...] = (
            (payload.run_id == run_id, "cursor belongs to a foreign run"),
            (payload.generation == generation, "cursor generation is stale"),
            (
                payload.query_fingerprint == query_fingerprint,
                "cursor query fingerprint does not match this request",
            ),
            (
                payload.snapshot_id == snapshot_id,
                "cursor snapshot does not match the active data snapshot",
            ),
            (
                payload.source_ids == expected_sources,
                "cursor source selection does not match this request",
            ),
            (
                payload.result_kind == result_kind,
                "cursor result kind does not match this Tool",
            ),
            (
                page_size is None or payload.page_size == page_size,
                "cursor page size does not match this request",
            ),
        )
        for valid, message in checks:
            if not valid:
                raise CursorValidationError(message)
        return payload


__all__ = [
    "CursorCodec",
    "CursorPayload",
    "CursorValidationError",
    "canonical_json",
    "query_fingerprint",
    "snapshot_fingerprint",
]

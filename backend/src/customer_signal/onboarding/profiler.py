"""Bounded schema profiling over repeatable streaming table readers."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal
from numbers import Integral, Real
from pathlib import Path
import re
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from customer_signal.onboarding.table_pages import open_table_page_reader

MAX_ROWS = 10_000
_SIGNED_INTEGER = re.compile(r"^[+-]?\d+$")
_DECIMAL_NUMBER = re.compile(
    r"^[+-]?(?:\d+\.\d*|\.\d+|\d+[eE][+-]?\d+|\d+\.\d*[eE][+-]?\d+)$"
)


class ColumnProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    dtype: str
    null_count: int
    distinct_count: int
    top_values: list[str] = Field(default_factory=list)


class TableProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    row_count: int
    sampled_row_count: int = 0
    is_sampled: bool = False
    columns: list[ColumnProfile]


def load_rows(path: Path) -> tuple[list[str], list[tuple]]:
    """Compatibility loader retaining the original 10,000-row policy."""

    reader = open_table_page_reader(path)
    columns: list[str] | None = None
    rows: list[tuple] = []
    for _, mapping in reader.iter_rows():
        if columns is None:
            columns = list(mapping)
        rows.append(tuple(mapping[column] for column in columns))
        if len(rows) > MAX_ROWS:
            break
    if len(rows) > MAX_ROWS:
        raise ValueError(f"table exceeds the onboarding bound of {MAX_ROWS} rows")
    if not rows:
        raise ValueError("table has no rows to onboard")
    assert columns is not None
    return columns, rows


def profile_table(
    path: Path,
    *,
    max_top_values: int = 8,
    max_sample_rows: int = MAX_ROWS,
) -> TableProfile:
    """Count every row while bounding in-memory per-column statistics."""

    if (
        isinstance(max_top_values, bool)
        or not isinstance(max_top_values, int)
        or max_top_values < 1
    ):
        raise ValueError("max_top_values must be a positive integer")
    if (
        isinstance(max_sample_rows, bool)
        or not isinstance(max_sample_rows, int)
        or max_sample_rows < 1
    ):
        raise ValueError("max_sample_rows must be a positive integer")

    reader = open_table_page_reader(path)
    columns: list[str] | None = None
    sampled_rows: list[tuple[object, ...]] = []
    row_count = 0
    for _, mapping in reader.iter_rows():
        if columns is None:
            columns = list(mapping)
        if row_count < max_sample_rows:
            sampled_rows.append(tuple(mapping[column] for column in columns))
        row_count += 1
    if row_count == 0 or columns is None:
        raise ValueError("table has no rows to onboard")

    profiles: list[ColumnProfile] = []
    for index, name in enumerate(columns):
        values = [row[index] for row in sampled_rows]
        present = [value for value in values if value is not None]
        counter = Counter(str(value) for value in present)
        dtype = _profile_dtype(present) if present else "unknown"
        profiles.append(
            ColumnProfile(
                name=name,
                dtype=dtype,
                null_count=len(values) - len(present),
                distinct_count=len(counter),
                top_values=[value for value, _ in counter.most_common(max_top_values)],
            )
        )
    return TableProfile(
        path=str(path),
        row_count=row_count,
        sampled_row_count=len(sampled_rows),
        is_sampled=row_count > len(sampled_rows),
        columns=profiles,
    )


def _profile_dtype(values: list[object]) -> str:
    if all(isinstance(item, bool) for item in values):
        return "bool"
    if all(isinstance(item, Integral) and not isinstance(item, bool) for item in values):
        return "int"
    if all(
        isinstance(item, (Real, Decimal)) and not isinstance(item, bool)
        for item in values
    ):
        return "float"
    if all(isinstance(item, str) for item in values):
        strings = cast(list[str], values)
        if all(item.casefold() in {"true", "false"} for item in strings):
            return "bool"
        if all(_SIGNED_INTEGER.fullmatch(item) for item in strings):
            return "int"
        if all(
            _SIGNED_INTEGER.fullmatch(item) or _DECIMAL_NUMBER.fullmatch(item)
            for item in strings
        ):
            return "float"
        if all(_is_iso_datetime(item) for item in strings):
            return "datetime"
    return type(values[0]).__name__


def _is_iso_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


__all__ = ["ColumnProfile", "MAX_ROWS", "TableProfile", "load_rows", "profile_table"]

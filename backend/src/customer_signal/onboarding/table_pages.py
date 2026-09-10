"""Repeatable streaming row readers for supported onboarding table formats."""

from __future__ import annotations

import csv
from collections.abc import Iterator, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Protocol, runtime_checkable

import duckdb


class UnsupportedTableFormatError(ValueError):
    """The table extension has no bounded streaming reader."""

    def __init__(self, suffix: str) -> None:
        super().__init__(
            f"unsupported table format: {suffix or '<none>'} "
            "(use .csv, .parquet, or .pq)"
        )


@runtime_checkable
class TablePageReader(Protocol):
    """Re-openable table reader preserving zero-based physical row ordinals."""

    def snapshot_token(self) -> str: ...

    def iter_rows(self) -> Iterator[tuple[int, Mapping[str, object]]]: ...


def _file_digest(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"table file not found: {path}")
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_csv_scalar(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return value


class CsvTablePageReader:
    """Stream lexical CSV values, normalizing only empty cells to ``None``."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def snapshot_token(self) -> str:
        return _file_digest(self._path)

    def iter_rows(self) -> Iterator[tuple[int, Mapping[str, object]]]:
        if not self._path.is_file():
            raise FileNotFoundError(f"table file not found: {self._path}")
        with self._path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                return
            for ordinal, row in enumerate(reader):
                yield ordinal, {
                    name: _normalize_csv_scalar(row.get(name)) for name in reader.fieldnames
                }


class ParquetTablePageReader:
    """Stream Parquet batches with DuckDB, without a PyArrow dependency."""

    def __init__(self, path: Path, *, batch_size: int = 512) -> None:
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        self._path = path
        self._batch_size = batch_size

    def snapshot_token(self) -> str:
        return _file_digest(self._path)

    def iter_rows(self) -> Iterator[tuple[int, Mapping[str, object]]]:
        if not self._path.is_file():
            raise FileNotFoundError(f"table file not found: {self._path}")
        connection = duckdb.connect(":memory:")
        try:
            schema = connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(self._path)]
            ).fetchall()
            projections = []
            for name, dtype, *_ in schema:
                identifier = f'"{name.replace(chr(34), chr(34) * 2)}"'
                if dtype == "TIMESTAMP WITH TIME ZONE":
                    projections.append(f"CAST({identifier} AS VARCHAR) AS {identifier}")
                else:
                    projections.append(identifier)
            cursor = connection.execute(
                f"SELECT {', '.join(projections)} FROM read_parquet(?)",
                [str(self._path)],
            )
            columns = [item[0] for item in cursor.description]
            ordinal = 0
            while rows := cursor.fetchmany(self._batch_size):
                for row in rows:
                    yield ordinal, dict(zip(columns, row, strict=True))
                    ordinal += 1
        finally:
            connection.close()


def open_table_page_reader(path: Path) -> TablePageReader:
    """Select the native streaming reader for ``path``."""

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return CsvTablePageReader(path)
    if suffix in {".parquet", ".pq"}:
        return ParquetTablePageReader(path)
    raise UnsupportedTableFormatError(suffix)


__all__ = [
    "CsvTablePageReader",
    "ParquetTablePageReader",
    "TablePageReader",
    "UnsupportedTableFormatError",
    "open_table_page_reader",
]

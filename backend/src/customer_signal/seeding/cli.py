"""CLI for exporting the deterministic two-week hackathon seed dataset."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from customer_signal.seeding.exporter import export_bundle
from customer_signal.seeding.generator import generate_seed_bundle
from customer_signal.seeding.models import SeedConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate validated table-shaped data for the two-week hackathon demo."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bundle = generate_seed_bundle(SeedConfig(seed=args.seed))
    try:
        result = export_bundle(bundle, args.output, force=args.force)
    except FileExistsError as error:
        print(str(error), file=sys.stderr)
        return 2
    row_count = sum(len(rows) for rows in bundle.tables.values())
    print(f"Seeded {row_count} rows under {result.manifest_path.parent}")
    print(f"Validation checks: {len(result.validation.checks)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

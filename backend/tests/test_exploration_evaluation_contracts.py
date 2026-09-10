from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from customer_signal.exploration.evaluation_contracts import ExplorationEvaluationRubric


RUBRIC_PATH = Path("data/seeding/hackathon-2week/exploration-evaluation-rubric.json")
RUNTIME_PACKAGE = Path("backend/src/customer_signal/exploration")
POST_TERMINAL_MODULES = frozenset({"evaluator.py", "evaluation_cli.py"})


def _runtime_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(RUNTIME_PACKAGE.rglob("*.py"))
        if path.relative_to(RUNTIME_PACKAGE).as_posix() not in POST_TERMINAL_MODULES
    )


def test_live_rubric_locks_threshold_and_required_patterns() -> None:
    rubric = ExplorationEvaluationRubric.model_validate_json(RUBRIC_PATH.read_text())

    assert rubric.minimum_score == 11
    assert rubric.maximum_score == 14
    assert {pattern.pattern_id for pattern in rubric.required_patterns} == {
        "vas_navigation",
        "payment_consent",
    }
    assert sum(item.max_points for item in rubric.criteria) == 14
    assert all(item.structured_predicates for item in rubric.criteria)


def test_every_criterion_declares_structured_provenance_requirements() -> None:
    rubric = ExplorationEvaluationRubric.model_validate_json(RUBRIC_PATH.read_text())

    for criterion in rubric.criteria:
        assert criterion.minimum_complete_result_refs >= 0
        assert criterion.require_scan_complete is True
        assert criterion.required_source_group_ids
        assert criterion.required_tool_names
        assert all(predicate.kind != "free_text" for predicate in criterion.structured_predicates)
    assert any(item.required_modes == ("sequence",) for item in rubric.criteria)
    assert any(item.required_modes == ("funnel",) for item in rubric.criteria)
    assert any(item.require_evidence for item in rubric.criteria)
    assert any(item.require_recommendation for item in rubric.criteria)


def test_rubric_rejects_score_sum_or_unknown_pattern() -> None:
    rubric = ExplorationEvaluationRubric.model_validate_json(RUBRIC_PATH.read_text())
    payload = rubric.model_dump(mode="json")
    payload["maximum_score"] = 99
    with pytest.raises(ValidationError, match="maximum_score"):
        ExplorationEvaluationRubric.model_validate(payload)

    payload = rubric.model_dump(mode="json")
    payload["required_patterns"][0]["criterion_ids"] = ["criterion-does-not-exist"]
    with pytest.raises(ValidationError, match="criterion_ids"):
        ExplorationEvaluationRubric.model_validate(payload)


def test_runtime_does_not_import_oracle_or_rubric() -> None:
    runtime_files = _runtime_files()
    runtime_sources = "\n".join(path.read_text() for path in runtime_files)

    assert runtime_files
    assert all(RUNTIME_PACKAGE in path.parents for path in runtime_files)
    assert "daily_kpis" not in runtime_sources
    assert "exploration-evaluation-rubric" not in runtime_sources

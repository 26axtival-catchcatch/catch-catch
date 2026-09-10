from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pytest

from customer_signal.onboarding.adapter import load_onboarded_adapters
from customer_signal.domain.sources import EventScope
from customer_signal.seeding.cli import main as seed_main
from customer_signal.seeding.exporter import export_bundle
from customer_signal.seeding.generator import generate_seed_bundle
from customer_signal.seeding.models import SeedConfig, TABLE_COLUMNS
from customer_signal.seeding.validation import SeedValidationError, validate_bundle


def test_seed_contract_locks_window_and_selected_schema() -> None:
    config = SeedConfig()

    assert config.start_date == date(2026, 9, 4)
    assert config.intervention_at == datetime(2026, 9, 11, 9, 0)
    assert config.end_date == date(2026, 9, 17)
    assert set(TABLE_COLUMNS) == {
        "L0UR_FEEDBACK",
        "L0UR_SEARCH_HISTORY",
        "L1BAT_CUST_BLNG_AND_BNFT_SUM",
        "L1CM_CRM_MSG_SEND_H",
        "L1DA_GA_REP_CHNL_BEHV_L",
        "L1DA_RMNG_USE_MMLY_INTG_H",
        "L1RA_VOC_STT_DTL_H",
        "L2ZI_MBL_VAS_ENTR_INFO_DALY_H",
    }
    assert "ABTEST_ID" in TABLE_COLUMNS["L1DA_GA_REP_CHNL_BEHV_L"]


def test_vas_baseline_cohort_and_journey_are_discoverable() -> None:
    bundle = generate_seed_bundle()
    ga_rows = bundle.tables["L1DA_GA_REP_CHNL_BEHV_L"]
    baseline = [row for row in ga_rows if row["P_YYYYMMDD"] <= "2026-09-10"]
    wandering = {row["CUST_NO"] for row in baseline if row["EVET_ACT_CATG_NM"] == "vas_wandering"}
    unreachable = {
        row["CUST_NO"] for row in baseline if row["EVET_ACT_LABE_NM"] == "vas_unreachable"
    }
    favorites = {row["CUST_NO"] for row in baseline if row["EVET_ACT_NM"] == "favorite_set"}

    assert len(wandering) == 340
    assert len(unreachable) == 97
    assert len(favorites & wandering) == 84

    by_session: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in baseline:
        by_session[str(row["SESN_ID"])].append(row)
    sample = next(rows for rows in by_session.values() if str(rows[0]["CUST_NO"]) in favorites)
    ordered = sorted(sample, key=lambda row: str(row["LOG_DTTM"]))
    assert ordered[-1]["EVET_ACT_NM"] == "favorite_set"
    assert any(row["REP_CHNL_MENU_NM"] == "부가서비스 조회/해지" for row in ordered[:-1])


def test_vas_baseline_links_search_feedback_voc_and_subscription_profiles() -> None:
    tables = generate_seed_bundle().tables
    searches = [
        row
        for row in tables["L0UR_SEARCH_HISTORY"]
        if row["REWRITE_SEARCH_QUERY"] == "부가서비스 조회/해지"
        and row["P_YYYYMMDD"] <= "2026-09-10"
    ]
    feedback = [row for row in tables["L0UR_FEEDBACK"] if row["OPTION"] == "바로가기 없음"]
    voc = [
        row
        for row in tables["L1RA_VOC_STT_DTL_H"]
        if row["CNSL_THMA_NM"] == "부가서비스 조회/해지" and row["P_YYYYMMDD"] <= "2026-09-10"
    ]
    profiles = tables["L2ZI_MBL_VAS_ENTR_INFO_DALY_H"]

    assert len({row["CZ_LNK_KEY"] for row in searches}) == 180
    assert len({row["CZ_LNK_KEY"] for row in feedback}) == 90
    assert len({row["CZ_LNK_KEY"] for row in voc}) == 61
    assert all(
        row["SEARCH_RESULT_REFERENCE_TEMPLATE_NAME"] == "VAS_GUIDE_NO_CTA" for row in searches
    )

    searches_by_run = {row["RUN_ID"]: row for row in searches}
    assert all(row["RUN_ID"] in searches_by_run for row in feedback)
    assert all(
        row["CZ_LNK_KEY"] == searches_by_run[row["RUN_ID"]]["CZ_LNK_KEY"] for row in feedback
    )

    service_counts: dict[str, int] = defaultdict(int)
    for row in profiles:
        service_counts[str(row["CUST_NO"])] += 1
    baseline_customers = {
        row["CUST_NO"]
        for row in tables["L1DA_GA_REP_CHNL_BEHV_L"]
        if row["EVET_ACT_CATG_NM"] == "vas_wandering"
    }
    assert all(service_counts[str(customer)] >= 3 for customer in baseline_customers)


def test_payment_baseline_locks_abandonment_shape() -> None:
    rows = generate_seed_bundle().tables["L1DA_GA_REP_CHNL_BEHV_L"]
    baseline = [row for row in rows if row["P_YYYYMMDD"] <= "2026-09-10"]
    incomplete = {
        row["CUST_NO"] for row in baseline if row["EVET_ACT_LABE_NM"] == "payment_incomplete"
    }
    consent_exits = {
        row["SESN_ID"] for row in baseline if row["EVET_ACT_NM"] == "consent_sheet_closed"
    }
    incomplete_sessions = {
        row["SESN_ID"] for row in baseline if row["EVET_ACT_LABE_NM"] == "payment_incomplete"
    }

    assert len(incomplete) == 210
    assert len(incomplete_sessions) == 567
    assert len(incomplete_sessions) / len(incomplete) == 2.7
    assert 0.81 <= len(consent_exits) / len(incomplete_sessions) <= 0.83


def test_payment_baseline_links_controls_search_feedback_voc_and_billing() -> None:
    tables = generate_seed_bundle().tables
    ga_rows = tables["L1DA_GA_REP_CHNL_BEHV_L"]
    completed = {
        row["CUST_NO"]
        for row in ga_rows
        if row["EVET_ACT_NM"] == "limit_change_completed" and row["P_YYYYMMDD"] <= "2026-09-10"
    }
    payment_searches = [
        row
        for row in tables["L0UR_SEARCH_HISTORY"]
        if row["REWRITE_SEARCH_QUERY"] == "소액결제 한도 변경" and row["P_YYYYMMDD"] <= "2026-09-10"
    ]
    payment_feedback = [
        row for row in tables["L0UR_FEEDBACK"] if row["OPTION"] == "실제 화면과 다름"
    ]
    payment_voc = [
        row
        for row in tables["L1RA_VOC_STT_DTL_H"]
        if row["CNSL_THMA_NM"] == "소액결제 한도" and row["P_YYYYMMDD"] <= "2026-09-10"
    ]
    payment_billing = [
        row
        for row in tables["L1BAT_CUST_BLNG_AND_BNFT_SUM"]
        if str(row["CZ_LNK_KEY"]).startswith("21")
    ]

    assert len(completed) == 90
    assert len({row["CZ_LNK_KEY"] for row in payment_searches}) == 150
    assert len({row["CZ_LNK_KEY"] for row in payment_feedback}) == 100
    assert len({row["CZ_LNK_KEY"] for row in payment_voc}) == 74
    assert len(payment_billing) == 300
    assert sum(row["SMLS_STLM_AMT"] > 0 for row in payment_billing) == 210
    assert len({row["YY10_AGELV_ID"] for row in payment_billing}) >= 4


def test_validation_proves_post_intervention_improvement() -> None:
    report = validate_bundle(generate_seed_bundle())

    assert report.valid is True
    assert len(report.daily_kpis) == 14
    last = report.daily_kpis[-1]
    assert last["exposure_rate"] == 1.0
    assert last["vas_direct_reach_rate"] >= 0.65
    assert last["vas_unreachable_rate"] <= 0.15
    assert last["payment_completion_rate"] >= 0.65
    assert last["payment_consent_exit_rate"] <= 0.35
    assert last["payment_average_attempts"] <= 1.6
    assert report.checks["foreign_keys"] == "passed"
    assert report.checks["baseline_cohorts"] == "passed"
    assert report.checks["three_day_trend"] == "passed"
    assert report.checks["temporal_order"] == "passed"
    assert report.checks["control_stability"] == "passed"


def test_export_is_reproducible_and_requires_force(tmp_path: Path) -> None:
    target = tmp_path / "seed"

    first = export_bundle(generate_seed_bundle(), target)
    assert first.manifest_path.exists()
    with pytest.raises(FileExistsError):
        export_bundle(generate_seed_bundle(), target)
    second = export_bundle(generate_seed_bundle(), target, force=True)

    assert first.checksums == second.checksums


def test_reseeding_preserves_separate_evaluation_rubric(tmp_path: Path) -> None:
    target = tmp_path / "seed"
    export_bundle(generate_seed_bundle(), target)
    rubric = target / "exploration-evaluation-rubric.json"
    original = '{"rubric_version": "1"}\n'
    rubric.write_text(original)
    export_bundle(generate_seed_bundle(), target, force=True)
    assert rubric.read_text() == original
    assert not any("rubric" in str(p) for p in (target / "onboarded-sources").rglob("*"))


def test_exported_registry_loads_in_the_application(tmp_path: Path) -> None:
    target = tmp_path / "seed"
    export_bundle(generate_seed_bundle(), target)

    adapters = load_onboarded_adapters(target / "onboarded-sources")

    assert {adapter.describe().source_id for adapter in adapters} == {
        "hackathon_app_behavior",
        "hackathon_search_history",
        "hackathon_search_feedback",
        "hackathon_voc",
        "hackathon_vas_subscription",
        "hackathon_billing_profile",
        "hackathon_crm_campaign",
        "hackathon_roaming_usage",
    }


def test_cli_requires_force_for_existing_output(tmp_path: Path) -> None:
    target = tmp_path / "seed"

    assert seed_main(["--output", str(target), "--seed", "20260831"]) == 0
    assert seed_main(["--output", str(target), "--seed", "20260831"]) == 2
    assert seed_main(["--output", str(target), "--seed", "20260831", "--force"]) == 0


def test_vas_two_sources_miss_quiet_customers_revealed_by_app_and_profiles() -> None:
    tables = generate_seed_bundle().tables
    visible = {
        str(row["CZ_LNK_KEY"])
        for table in ("L0UR_SEARCH_HISTORY", "L1RA_VOC_STT_DTL_H")
        for row in tables[table]
        if row["P_YYYYMMDD"] < "2026-09-11"
    }
    app = [
        r
        for r in tables["L1DA_GA_REP_CHNL_BEHV_L"]
        if r["P_YYYYMMDD"] < "2026-09-11" and r["EVET_ACT_CATG_NM"] == "vas_wandering"
    ]
    quiet = {str(r["CUST_NO"]) for r in app} - visible
    unreachable = {
        str(r["CUST_NO"]) for r in app if r["EVET_ACT_LABE_NM"] == "vas_unreachable"
    } & quiet
    assert len(quiet) == 160
    assert len(unreachable) == 16
    assert all(
        sum(r["CUST_NO"] == customer for r in tables["L2ZI_MBL_VAS_ENTR_INFO_DALY_H"]) == 3
        for customer in quiet
    )


def test_vas_crm_campaign_explains_google_one_change_search_demand() -> None:
    bundle = generate_seed_bundle()
    tables = bundle.tables
    boundary = "2026-09-11"
    messages = tables["L1CM_CRM_MSG_SEND_H"]
    recipients = {str(row["CZ_LNK_KEY"]) for row in messages}
    google_one_subscribers = {
        str(row["CUST_NO"])
        for row in tables["L2ZI_MBL_VAS_ENTR_INFO_DALY_H"]
        if row["PROD_CD"] == "VAS-GOOGLEONE-100"
        and row["SVC_STTS_CD"] == "A"
        and row["SRVL_YN"] == "Y"
    }
    searches = [
        row
        for row in tables["L0UR_SEARCH_HISTORY"]
        if row["P_YYYYMMDD"] < boundary and row["REWRITE_SEARCH_QUERY"] == "부가서비스 조회/해지"
    ]
    searchers = {str(row["CZ_LNK_KEY"]) for row in searches}
    change_searchers = {
        str(row["CZ_LNK_KEY"])
        for row in searches
        if "구글원" in str(row["SEARCH_QUERY"])
        and ("변경" in str(row["SEARCH_QUERY"]) or "바꾸" in str(row["SEARCH_QUERY"]))
    }
    baseline_app_customers = {
        str(row["CZ_LNK_KEY"])
        for row in tables["L1DA_GA_REP_CHNL_BEHV_L"]
        if row["P_YYYYMMDD"] < boundary and row["EVET_ACT_CATG_NM"] == "vas_wandering"
    }

    assert len(messages) == len(recipients) == 240
    assert recipients == google_one_subscribers
    assert {row["SEND_RESULT_CD"] for row in messages} == {"DELIVERED"}
    assert len(recipients & searchers) == len(change_searchers) == 160
    assert len((baseline_app_customers - recipients) & searchers) == 20
    assert (160 / 240) / (20 / 100) > 3
    sent_at = {
        str(row["CZ_LNK_KEY"]): datetime.fromisoformat(str(row["SEND_DTTM"])) for row in messages
    }
    assert all(
        datetime.fromisoformat(str(row["CREATED_AT"])) > sent_at[str(row["CZ_LNK_KEY"])]
        for row in searches
        if str(row["CZ_LNK_KEY"]) in recipients
    )
    report = validate_bundle(bundle)
    campaign_day = next(row for row in report.daily_kpis if row["date"] == "2026-09-07")
    baseline_end = next(row for row in report.daily_kpis if row["date"] == "2026-09-10")
    assert campaign_day["vas_crm_delivered_count"] == 240
    assert campaign_day["vas_google_one_change_search_customer_count"] > 0
    assert baseline_end["vas_crm_recipient_change_search_rate_cumulative"] == 0.6667
    assert all(
        0.0 <= float(value) <= 1.0
        for row in report.daily_kpis
        for metric, value in row.items()
        if metric.endswith("_rate")
    )


def _roaming_pattern(tables):
    exits = {
        r["CUST_NO"]
        for r in tables["L1DA_GA_REP_CHNL_BEHV_L"]
        if r["EVET_ACT_NM"] == "roaming_plan_selection_exited"
    }
    agent_signups = {
        r["CUST_NO"]
        for r in tables["L1RA_VOC_STT_DTL_H"]
        if r["CSLR_PRSS_CNTN"] == "상담원 로밍 가입 처리 완료"
    }
    return [
        r
        for r in tables["L1DA_RMNG_USE_MMLY_INTG_H"]
        if r["CUST_NO"] in exits & agent_signups and r["SPPS_ENTR_STUS_CD"] == "A"
    ]


def test_roaming_pattern_requires_app_voc_and_subscription_context() -> None:
    tables = generate_seed_bundle().tables
    roaming = tables["L1DA_RMNG_USE_MMLY_INTG_H"]
    customers = {r["CUST_NO"] for r in roaming}
    searches = [r for r in tables["L0UR_SEARCH_HISTORY"] if str(r["CZ_LNK_KEY"]) in customers]
    assert len(roaming) == len(customers) == len(searches) == 280
    assert {r["SEARCH_QUERY"] for r in searches} == {"로밍 요금제 추천"}
    assert {r["STATUS"] for r in searches} == {"completed"}
    voc = [r for r in tables["L1RA_VOC_STT_DTL_H"] if r["CUST_NO"] in customers]
    assert len(voc) == 112
    assert {r["CNSL_ALL_SMRY_CNTN"] for r in voc} == {"로밍 요금제 안내 후 가입 처리 완료"}
    patterns = _roaming_pattern(tables)
    assert sum(r["DPTR_DT"] < "20260911" for r in patterns) == 56
    assert sum(r["DPTR_DT"] >= "20260911" for r in patterns) == 28
    assert sum(r["DPTR_DT"] == "20260917" for r in patterns) == 1
    assert all(r["SPPS_STRT_DT"] == r["DPTR_DT"] for r in roaming)
    targets = {r["CUST_NO"] for r in patterns}
    # Direct consultation signups are not abandonment of plan comparison.
    assert len({r["CUST_NO"] for r in voc} - targets) == 28
    for profile in patterns:
        app = sorted(
            [r for r in tables["L1DA_GA_REP_CHNL_BEHV_L"] if r["CUST_NO"] == profile["CUST_NO"]],
            key=lambda r: r["LOG_DTTM"],
        )
        details = [r for r in app if r["EVET_ACT_NM"] == "roaming_plan_detail_viewed"]
        assert len({r["REP_CHNL_MENU_NM"] for r in details}) == 3
        assert app[-1]["EVET_ACT_NM"] == "roaming_plan_selection_exited"
        call = next(r for r in voc if r["CUST_NO"] == profile["CUST_NO"])
        assert call["ENTR_NO"] == profile["ENTR_NO"]
        assert (
            datetime.strptime(app[-1]["LOG_DTTM"], "%Y%m%d%H%M%S")
            < datetime.fromisoformat(call["CALL_CRTE_DTTM"])
            < datetime.fromisoformat(profile["BQ_LOAD_DTTM"])
        )


def test_roaming_export_preserves_analysis_fields_and_customer_links(tmp_path: Path) -> None:
    target = tmp_path / "seed"
    export_bundle(generate_seed_bundle(), target)
    adapters = {
        a.describe().source_id: a for a in load_onboarded_adapters(target / "onboarded-sources")
    }

    def events(source):
        return adapters[source].load_events(
            EventScope(
                source_ids=[source],
                start_at=datetime.fromisoformat("2026-09-04T00:00:00+09:00"),
                end_at=datetime.fromisoformat("2026-09-11T00:00:00+09:00"),
                max_events=10000,
            )
        )

    exits = {
        e.canonical_customer_id
        for e in events("hackathon_app_behavior")
        if e.action == "roaming_plan_selection_exited"
    }
    signups = {
        e.canonical_customer_id
        for e in events("hackathon_voc")
        if e.dimensions["resolution"] == "상담원 로밍 가입 처리 완료"
    }
    roaming = events("hackathon_roaming_usage")
    assert len(roaming) == 140
    assert len(signups) == 70
    assert (
        sum(e.canonical_customer_id in exits & signups and e.outcome == "A" for e in roaming) == 56
    )
    billing_ids = {e.canonical_customer_id for e in events("hackathon_billing_profile")}
    assert {e.canonical_customer_id for e in roaming} <= billing_ids


@pytest.mark.parametrize(
    "mutation", ["date", "month", "identity", "usage", "late_start", "call_order", "signup"]
)
def test_validation_rejects_broken_roaming_contract(mutation: str) -> None:
    bundle = generate_seed_bundle()
    row = bundle.tables["L1DA_RMNG_USE_MMLY_INTG_H"][0]
    if mutation == "date":
        row["BQ_LOAD_DTTM"] = "2026-08-31T21:00:00"
    elif mutation == "month":
        row["P_YYYYMM"] = 202608
    elif mutation == "identity":
        row["ENTR_NO"] = "UNKNOWN"
    elif mutation == "late_start":
        row["SPPS_STRT_DT"] = "20260930"
    elif mutation == "call_order":
        call = next(
            r for r in bundle.tables["L1RA_VOC_STT_DTL_H"] if r["CNSL_THMA_NM"] == "해외 로밍 이용"
        )
        call["CALL_CRTE_DTTM"] = call["P_YYYYMMDD"] + "T08:00:00"
    elif mutation == "signup":
        _roaming_pattern(bundle.tables)[0]["SPPS_ENTR_STUS_CD"] = "C"
    else:
        row["DATA_USAG"] = -1
    with pytest.raises(SeedValidationError):
        validate_bundle(bundle)


def test_selected_columns_exist_in_supplied_schema() -> None:
    root = Path(__file__).resolve().parents[2] / "docs" / "seeding" / "tables"
    for table, columns in TABLE_COLUMNS.items():
        schema = (root / table).read_text()
        physical = {
            line.split("|")[2].strip()
            for line in schema.splitlines()
            if "|" in line and len(line.split("|")) > 2
        }
        physical |= {line.split("\t")[1].strip() for line in schema.splitlines() if "\t" in line}
        assert set(columns) <= physical, (table, set(columns) - physical)


def test_subscription_duration_matches_snapshot_after_retiming() -> None:
    for row in generate_seed_bundle().tables["L2ZI_MBL_VAS_ENTR_INFO_DALY_H"]:
        snapshot = date.fromisoformat(row["P_YYYYMMDD"])
        started = date.fromisoformat(row["SVC_STRT_DT"])
        assert row["PROD_ENTR_DAYS"] == (snapshot - started).days
        assert (
            row["PROD_ENTR_MMCT"]
            == (snapshot.year - started.year) * 12 + snapshot.month - started.month
        )

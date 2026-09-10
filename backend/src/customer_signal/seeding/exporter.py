"""Atomic CSV and onboarding-registry export for hackathon seed data."""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from customer_signal.onboarding.adapter import load_onboarded_adapters
from customer_signal.onboarding.spec import (
    DimensionSpec,
    FieldRule,
    IdentitySpec,
    MeasureSpec,
    SourceMappingSpec,
)
from customer_signal.seeding.models import SeedBundle, TABLE_COLUMNS
from customer_signal.seeding.validation import ValidationReport, validate_bundle


@dataclass(frozen=True, slots=True)
class ExportResult:
    manifest_path: Path
    checksums: dict[str, str]
    validation: ValidationReport


_TABLE_SOURCE_IDS = {
    "L1DA_GA_REP_CHNL_BEHV_L": "hackathon_app_behavior",
    "L0UR_SEARCH_HISTORY": "hackathon_search_history",
    "L0UR_FEEDBACK": "hackathon_search_feedback",
    "L1CM_CRM_MSG_SEND_H": "hackathon_crm_campaign",
    "L1RA_VOC_STT_DTL_H": "hackathon_voc",
    "L2ZI_MBL_VAS_ENTR_INFO_DALY_H": "hackathon_vas_subscription",
    "L1BAT_CUST_BLNG_AND_BNFT_SUM": "hackathon_billing_profile",
    "L1DA_RMNG_USE_MMLY_INTG_H": "hackathon_roaming_usage",
}


def _identity() -> IdentitySpec:
    return IdentitySpec(
        namespace="synthetic_customer",
        customer_column="CZ_LNK_KEY",
        link_method="exact",
        confidence=1.0,
    )


def _customer_number_identity() -> IdentitySpec:
    return IdentitySpec(
        namespace="synthetic_customer",
        customer_column="CUST_NO",
        link_method="exact",
        confidence=1.0,
    )


def _source_specs() -> dict[str, SourceMappingSpec]:
    return {
        "L1DA_GA_REP_CHNL_BEHV_L": SourceMappingSpec(
            source_id="hackathon_app_behavior",
            label="해커톤 앱 행동",
            description="메뉴 탐색, 소액결제 단계, 로밍 요금제 탐색의 합성 행동 로그",
            timestamp_column="BQ_LOAD_DTTM",
            timezone="Asia/Seoul",
            event_type=FieldRule(column="EVET_NM"),
            action=FieldRule(column="EVET_ACT_NM"),
            topic=FieldRule(column="EVET_ACT_CATG_NM"),
            outcome=FieldRule(column="EVET_ACT_LABE_NM"),
            text=FieldRule(column="REP_CHNL_MENU_NM"),
            identity=_customer_number_identity(),
            dimensions={
                "abtest_id": DimensionSpec(
                    column="ABTEST_ID",
                    semantic_type="category",
                    description="개선안 노출 구분",
                ),
                "session_id": DimensionSpec(
                    column="SESN_ID",
                    semantic_type="identifier",
                    description="합성 앱 세션 식별자",
                ),
                "menu": DimensionSpec(
                    column="REP_CHNL_MENU_NM",
                    semantic_type="category",
                    description="대표 메뉴",
                ),
            },
            measures={
                "page_stay_seconds": MeasureSpec(
                    column="PAGE_STAY_TM",
                    semantic_type="integer",
                    description="페이지 체류 시간",
                    unit="seconds",
                ),
                "session_stay_seconds": MeasureSpec(
                    column="SESN_STAY_TM",
                    semantic_type="integer",
                    description="세션 체류 시간",
                    unit="seconds",
                ),
            },
            status="approved",
        ),
        "L0UR_SEARCH_HISTORY": SourceMappingSpec(
            source_id="hackathon_search_history",
            label="해커톤 AI 검색 이력",
            description="부가서비스, 소액결제, 로밍 개선 전후의 합성 검색 이력",
            timestamp_column="CREATED_AT",
            timezone="Asia/Seoul",
            event_type=FieldRule(const="search"),
            action=FieldRule(
                column="SEARCH_QUERY_TYPE",
                value_map={"initial": "search", "repeat": "repeat_search"},
            ),
            topic=FieldRule(column="REWRITE_SEARCH_QUERY"),
            outcome=FieldRule(column="STATUS"),
            text=FieldRule(column="SEARCH_QUERY"),
            identity=_identity(),
            dimensions={
                "template": DimensionSpec(
                    column="SEARCH_RESULT_REFERENCE_TEMPLATE_NAME",
                    semantic_type="category",
                    description="검색 응답 템플릿",
                ),
                "query_type": DimensionSpec(
                    column="SEARCH_QUERY_TYPE",
                    semantic_type="category",
                    description="최초 또는 반복 검색 구분",
                ),
            },
            measures={
                "latency_ms": MeasureSpec(
                    column="FIRST_RESPONSE_LATENCY_MS",
                    semantic_type="number",
                    description="최초 응답 지연",
                    unit="milliseconds",
                )
            },
            status="approved",
        ),
        "L0UR_FEEDBACK": SourceMappingSpec(
            source_id="hackathon_search_feedback",
            label="해커톤 AI 검색 피드백",
            description="검색 결과의 합성 긍정·부정 피드백",
            timestamp_column="BQ_LOAD_DTTM",
            timezone="Asia/Seoul",
            event_type=FieldRule(const="feedback"),
            action=FieldRule(const="rate_search"),
            topic=FieldRule(column="OPTION"),
            outcome=FieldRule(column="FEEDBACK_TYPE"),
            text=FieldRule(column="REASON"),
            identity=_identity(),
            dimensions={
                "reason": DimensionSpec(
                    column="REASON",
                    semantic_type="text",
                    description="합성 피드백 사유",
                )
            },
            status="approved",
        ),
        "L1CM_CRM_MSG_SEND_H": SourceMappingSpec(
            source_id="hackathon_crm_campaign",
            label="해커톤 CRM 캠페인 발송",
            description="구글 원 부가서비스 기능 변경 안내를 발송한 합성 CRM 이력",
            timestamp_column="SEND_DTTM",
            timezone="Asia/Seoul",
            event_type=FieldRule(const="crm_message"),
            action=FieldRule(const="send_campaign_message"),
            topic=FieldRule(column="TARGET_PROD_NM"),
            outcome=FieldRule(column="SEND_RESULT_CD"),
            text=FieldRule(column="MESSAGE_CNTN"),
            identity=_identity(),
            dimensions={
                "campaign_id": DimensionSpec(
                    column="CAMPAIGN_ID",
                    semantic_type="identifier",
                    description="CRM 캠페인 식별자",
                ),
                "campaign_name": DimensionSpec(
                    column="CAMPAIGN_NM",
                    semantic_type="category",
                    description="CRM 캠페인명",
                ),
                "channel": DimensionSpec(
                    column="CHANNEL_CD",
                    semantic_type="category",
                    description="메시지 발송 채널",
                ),
                "target_segment": DimensionSpec(
                    column="TARGET_SEGMENT_NM",
                    semantic_type="category",
                    description="캠페인 대상 고객군",
                ),
                "target_product_code": DimensionSpec(
                    column="TARGET_PROD_CD",
                    semantic_type="category",
                    description="캠페인 대상 부가서비스 상품 코드",
                ),
                "feature": DimensionSpec(
                    column="FEATURE_NM",
                    semantic_type="category",
                    description="안내한 신규 기능",
                ),
            },
            status="approved",
        ),
        "L1RA_VOC_STT_DTL_H": SourceMappingSpec(
            source_id="hackathon_voc",
            label="해커톤 VOC",
            description="앱 실패 이후 고객센터로 이동한 합성 상담 이력",
            timestamp_column="CALL_CRTE_DTTM",
            timezone="Asia/Seoul",
            event_type=FieldRule(const="voc"),
            action=FieldRule(const="contact_customer_service"),
            topic=FieldRule(column="CNSL_THMA_NM"),
            outcome=FieldRule(column="CUST_SNMT_NM"),
            text=FieldRule(column="CNSL_ALL_SMRY_CNTN"),
            identity=_identity(),
            dimensions={
                "subject": DimensionSpec(
                    column="CNSL_SBJC_TIT_NM",
                    semantic_type="category",
                    description="상담 주제",
                ),
                "resolution": DimensionSpec(
                    column="CSLR_PRSS_CNTN",
                    semantic_type="category",
                    description="상담 처리 내용",
                ),
            },
            measures={
                "consult_seconds": MeasureSpec(
                    column="CUST_CNSL_TM",
                    semantic_type="integer",
                    description="상담 시간",
                    unit="seconds",
                )
            },
            status="approved",
        ),
        "L2ZI_MBL_VAS_ENTR_INFO_DALY_H": SourceMappingSpec(
            source_id="hackathon_vas_subscription",
            label="해커톤 부가서비스 가입",
            description="장기 가입 고객의 합성 부가서비스 일별 이력",
            timestamp_column="BQ_LOAD_DTTM",
            timezone="Asia/Seoul",
            event_type=FieldRule(const="subscription"),
            action=FieldRule(column="SVC_STTS_CD"),
            topic=FieldRule(column="PROD_NM"),
            outcome=FieldRule(column="SRVL_YN"),
            text=FieldRule(column="PROD_NM"),
            identity=_customer_number_identity(),
            dimensions={
                "product_code": DimensionSpec(
                    column="PROD_CD",
                    semantic_type="category",
                    description="부가서비스 상품 코드",
                )
            },
            measures={
                "amount_krw": MeasureSpec(
                    column="VAT_INCL_ALL_AMT",
                    semantic_type="integer",
                    description="부가세 포함 금액",
                    unit="KRW",
                ),
                "subscription_days": MeasureSpec(
                    column="PROD_ENTR_DAYS",
                    semantic_type="integer",
                    description="상품 가입 일수",
                    unit="days",
                ),
            },
            status="approved",
        ),
        "L1BAT_CUST_BLNG_AND_BNFT_SUM": SourceMappingSpec(
            source_id="hackathon_billing_profile",
            label="해커톤 고객 빌링 프로필",
            description="부가서비스와 소액결제 이용 여부를 담은 합성 월 프로필",
            timestamp_column="DP_LOAD_DTTM",
            timezone="Asia/Seoul",
            event_type=FieldRule(const="billing_profile"),
            action=FieldRule(const="review_profile"),
            topic=FieldRule(column="PP_NM"),
            outcome=FieldRule(column="ENTR_STTS_CD"),
            text=FieldRule(column="PP_NM"),
            identity=_identity(),
            dimensions={
                "age_band": DimensionSpec(
                    column="YY10_AGELV_ID",
                    semantic_type="category",
                    description="10년 연령대",
                ),
                "sex": DimensionSpec(
                    column="SEX_DV_CD",
                    semantic_type="category",
                    description="합성 성별 구분",
                ),
            },
            measures={
                "vas_amount_krw": MeasureSpec(
                    column="SPPS_AMT",
                    semantic_type="integer",
                    description="부가서비스 금액",
                    unit="KRW",
                ),
                "micropayment_amount_krw": MeasureSpec(
                    column="SMLS_STLM_AMT",
                    semantic_type="integer",
                    description="소액결제 금액",
                    unit="KRW",
                ),
            },
            status="approved",
        ),
        "L1DA_RMNG_USE_MMLY_INTG_H": SourceMappingSpec(
            source_id="hackathon_roaming_usage",
            label="해커톤 로밍 이용",
            description="출국일 적재 시점까지의 합성 월 누적 로밍 이용과 상품 가입 정보",
            timestamp_column="BQ_LOAD_DTTM",
            timezone="Asia/Seoul",
            event_type=FieldRule(const="roaming_usage_snapshot"),
            action=FieldRule(const="review_roaming_usage"),
            topic=FieldRule(const="해외 로밍 이용"),
            outcome=FieldRule(column="SPPS_ENTR_STUS_CD"),
            text=FieldRule(column="SPPS_NM"),
            identity=_customer_number_identity(),
            dimensions={
                name: DimensionSpec(
                    column=column, semantic_type="category", description=description
                )
                for name, column, description in (
                    ("country", "RMNG_NATN_NM", "로밍 국가"),
                    ("departure_date", "DPTR_DT", "출국일 YYYYMMDD"),
                    ("return_date", "HMCML_DT", "귀국일 YYYYMMDD, 미귀국은 빈 값"),
                    ("service_start_date", "SPPS_STRT_DT", "상품 시작일 YYYYMMDD"),
                    ("service_end_date", "SPPS_END_DT", "상품 종료일 YYYYMMDD"),
                    ("product_code", "SPPS_CD", "로밍 상품 코드"),
                    ("billing_month", "P_YYYYMM", "누적 집계 기준월 YYYYMM"),
                    ("rating_start_date", "RTNG_STRT_DT", "실제 과금 시작일, 미시작은 빈 값"),
                )
            },
            measures={
                "data_usage": MeasureSpec(
                    column="DATA_USAG",
                    semantic_type="number",
                    description="적재 시점까지 합성 데이터 사용량",
                    unit="bytes",
                ),
                "plan_use_days": MeasureSpec(
                    column="PP_USE_DAYS",
                    semantic_type="integer",
                    description="적재 시점까지 상품 사용 일수",
                    unit="days",
                ),
                "abroad_stay_days": MeasureSpec(
                    column="ABRD_STAY_DAYS",
                    semantic_type="integer",
                    description="적재 시점까지 해외 체류 일수",
                    unit="days",
                ),
            },
            status="approved",
        ),
    }


def _write_csv(path: Path, fieldnames: tuple[str, ...] | list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _checksum(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_registry(root: Path, csv_paths: dict[str, Path]) -> None:
    registry = root / "onboarded-sources"
    specs = _source_specs()
    for table_name, source_id in _TABLE_SOURCE_IDS.items():
        directory = registry / source_id
        directory.mkdir(parents=True)
        (directory / "spec.json").write_text(
            specs[table_name].model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        shutil.copy2(csv_paths[table_name], directory / "data.csv")
    adapters = load_onboarded_adapters(registry)
    if {adapter.describe().source_id for adapter in adapters} != set(_TABLE_SOURCE_IDS.values()):
        raise ValueError("exported onboarding registry did not load all eight sources")


def _manifest(
    bundle: SeedBundle,
    report: ValidationReport,
    checksums: dict[str, str],
) -> dict[str, object]:
    return {
        "schema_version": 3,
        "seed": bundle.config.seed,
        "period": {
            "start": bundle.config.start_date.isoformat(),
            "end": bundle.config.end_date.isoformat(),
            "timezone": "Asia/Seoul",
        },
        "intervention_at": bundle.config.intervention_at.isoformat(timespec="seconds"),
        "exposure_rates": list(bundle.config.exposure_rates),
        "row_counts": {table_name: len(rows) for table_name, rows in sorted(bundle.tables.items())},
        "baseline_cohorts": {
            "vas_wandering_customers": 340,
            "vas_favorite_customers": 84,
            "vas_voc_customers": 61,
            "vas_unreachable_customers": 97,
            "payment_incomplete_customers": 210,
            "payment_average_attempts": 2.7,
            "payment_consent_exit_share": 0.82,
            "payment_voc_customers": 74,
            "vas_customers_absent_from_search_and_voc": 160,
            "vas_unreachable_absent_from_search_and_voc": 16,
            "vas_google_one_crm_recipients": 240,
            "vas_google_one_change_search_customers": 160,
            "vas_nonrecipient_search_customers": 20,
            "roaming_customers": 140,
            "roaming_browse_exit_agent_signup_customers": 56,
            "roaming_agent_signup_customers": 70,
            "roaming_direct_consultation_customers": 14,
        },
        "exploration_cases": {
            "limited_sources": ["hackathon_search_history", "hackathon_voc"],
            "vas_expanded_sources": ["hackathon_app_behavior", "hackathon_vas_subscription"],
            "vas_context_source": "hackathon_crm_campaign",
            "roaming_expanded_sources": ["hackathon_app_behavior", "hackathon_roaming_usage"],
            "roaming_snapshot_semantics": "month_to_date_as_of_departure_day_load",
        },
        "checks": report.checks,
        "first_day_kpis": report.daily_kpis[0],
        "last_day_kpis": report.daily_kpis[-1],
        "checksums": checksums,
    }


def _replace_directory(temp_root: Path, target: Path, *, force: bool) -> None:
    if target.exists() and not force:
        raise FileExistsError(f"seed output already exists: {target}")
    backup: Path | None = None
    try:
        if target.exists():
            backup = target.with_name(f".{target.name}.backup-{uuid4().hex}")
            os.replace(target, backup)
        os.replace(temp_root, target)
    except Exception:
        if backup is not None and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    else:
        if backup is not None:
            shutil.rmtree(backup)


def export_bundle(bundle: SeedBundle, target: Path, *, force: bool = False) -> ExportResult:
    """Validate and atomically export one deterministic seed bundle."""

    report = validate_bundle(bundle)
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        raise FileExistsError(f"seed output already exists: {target}")
    temp_root = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        csv_paths: dict[str, Path] = {}
        for table_name, columns in TABLE_COLUMNS.items():
            path = temp_root / f"{table_name}.csv"
            _write_csv(path, columns, bundle.tables[table_name])
            csv_paths[table_name] = path
        kpi_path = temp_root / "daily_kpis.csv"
        kpi_columns = list(report.daily_kpis[0])
        _write_csv(kpi_path, kpi_columns, report.daily_kpis)
        _write_registry(temp_root, csv_paths)
        checksums = {
            path.name: _checksum(path)
            for path in sorted([*csv_paths.values(), kpi_path], key=lambda item: item.name)
        }
        manifest_path = temp_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                _manifest(bundle, report, checksums),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        # This evaluator-owned file is not generated data or an agent Source.
        rubric = target / "exploration-evaluation-rubric.json"
        if rubric.is_file():
            shutil.copy2(rubric, temp_root / rubric.name)
        _replace_directory(temp_root, target, force=force)
    except Exception:
        if temp_root.exists():
            shutil.rmtree(temp_root)
        raise
    return ExportResult(
        manifest_path=target / "manifest.json",
        checksums=checksums,
        validation=report,
    )


__all__ = ["ExportResult", "export_bundle"]

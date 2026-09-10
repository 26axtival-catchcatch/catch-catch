"""Scenario-first row generation for the two-week hackathon dataset."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from customer_signal.seeding.models import SeedBundle, SeedConfig, TABLE_COLUMNS, TableRow


_VAS_REACHABLE_PATH = (
    "마이",
    "요금제 조회/변경",
    "마이",
    "멤버십",
    "마이",
    "가입정보",
    "부가서비스 조회/해지",
)
_VAS_UNREACHABLE_PATH = (
    "홈",
    "전체메뉴",
    "마이",
    "요금제 조회/변경",
    "마이",
    "데이터 충전",
    "마이",
    "전체메뉴",
)
_VAS_QUERIES = (
    "부가서비스 해지",
    "부가서비스 끄기",
    "안 쓰는 서비스 빼기",
    "내가 가입한 부가서비스",
    "부가서비스 확인",
    "부가서비스 변경",
)
_VAS_PRODUCTS = (
    ("VAS-SAFE-01", "스팸 차단", 3300),
    ("VAS-MEDIA-02", "미디어팩", 7700),
    ("VAS-RING-03", "통화연결음", 1100),
)
_VAS_GOOGLE_ONE_PRODUCT = ("VAS-GOOGLEONE-100", "구글 원 100GB", 2400)
_VAS_GOOGLE_ONE_CHANGE_QUERIES = (
    "구글원 저장공간 변경",
    "구글원 100GB에서 200GB 변경",
    "구글원 옵션 바꾸기",
    "구글원 부가서비스 변경",
    "구글원 용량 변경 방법",
    "구글원 200GB로 변경",
)
_VAS_CRM_CHANGE_SEARCHER_INDICES = frozenset(range(1, 161))
_VAS_CRM_RECIPIENT_INDICES = frozenset(range(1, 161)) | frozenset(range(181, 261))
_VAS_CRM_CAMPAIGN_DAY_OFFSET = 3
_PAYMENT_QUERIES = (
    "소액결제 한도 늘리기",
    "결제 한도 변경",
    "한도 올리는 법",
    "한도 변경 안 됨",
    "결제 한도 변경 오류",
    "한도 변경 왜 안돼",
)
_VAS_POST_DIRECT = (16, 20, 19, 26, 29, 35, 37)
_VAS_POST_UNREACHABLE = (14, 12, 13, 9, 8, 6, 5)
_VAS_POST_FAVORITES = (12, 10, 9, 7, 6, 5, 4)
_VAS_POST_REPEATS = (28, 24, 20, 16, 12, 10, 8)
_VAS_POST_NEGATIVE_FEEDBACK = (20, 18, 15, 12, 9, 7, 5)
_VAS_POST_VOC = (9, 8, 7, 6, 5, 4, 3)
_PAYMENT_POST_COMPLETED = (14, 18, 17, 24, 27, 29, 30)
_PAYMENT_POST_CONSENT_EXITS = (20, 17, 13, 9, 7, 5, 3)
_PAYMENT_POST_RETRIES = (20, 17, 14, 10, 7, 5, 2)
_PAYMENT_POST_REPEAT_SEARCHES = (18, 15, 13, 10, 7, 5, 3)
_PAYMENT_POST_NEGATIVE_FEEDBACK = (15, 13, 11, 9, 7, 5, 3)
_PAYMENT_POST_VOC = (14, 12, 10, 8, 6, 5, 4)


@dataclass(frozen=True, slots=True)
class _CustomerIdentity:
    cz_link_key: int
    customer_no: str
    entry_no: str


def _identity(case: str, phase: str, index: int) -> _CustomerIdentity:
    serial = f"{index:04d}"
    case_digit = {"vas": "1", "payment": "2", "roaming": "3"}[case]
    phase_digit = "1" if phase == "baseline" else "2"
    cz_link_key = int(f"{case_digit}{phase_digit}{serial}")
    return _CustomerIdentity(
        cz_link_key=cz_link_key,
        customer_no=str(cz_link_key),
        entry_no=f"ENTR-{case.upper()}-{phase.upper()}-{serial}",
    )


def _empty_tables() -> dict[str, list[TableRow]]:
    return {table_name: [] for table_name in TABLE_COLUMNS}


def _menu_levels(menu: str) -> tuple[str, str, str]:
    if menu.startswith("로밍"):
        return "해외로밍", "로밍 이용", menu
    if menu in {"홈", "전체메뉴"}:
        return menu, "", ""
    if menu == "마이":
        return "마이", "", ""
    if menu in {"요금제 조회/변경", "멤버십", "요금/납부", "데이터 충전"}:
        return "마이", menu, ""
    if menu == "가입정보":
        return "마이", "가입정보", ""
    if menu == "결제 한도 설정/변경":
        return "마이", "요금/납부", "결제 한도 설정/변경"
    return "마이", "가입정보", "부가서비스 조회/해지"


def _ga_row(
    *,
    identity: _CustomerIdentity,
    occurred_at: datetime,
    session_id: str,
    session_stay: int,
    event_name: str,
    action: str,
    category: str,
    label: str,
    page_stay: int,
    menu: str,
    abtest_id: str,
    ga_link_key: int,
) -> TableRow:
    level1, level2, level3 = _menu_levels(menu)
    loaded_at = occurred_at + timedelta(hours=2)
    return {
        "CZ_LNK_KEY": identity.cz_link_key,
        "P_YYYYMMDD": occurred_at.date().isoformat(),
        "GA_LNK_KEY": ga_link_key,
        "BASE_DT": occurred_at.strftime("%Y%m%d"),
        "CLT_ID": f"CLT-{identity.cz_link_key}",
        "SESN_ID": session_id,
        "PTPN_SESN_TM": session_stay,
        "CUST_NO": identity.customer_no,
        "ENTR_NO": identity.entry_no,
        "LOG_DTTM": occurred_at.strftime("%Y%m%d%H%M%S"),
        "SESN_STAY_TM": session_stay,
        "EVET_NM": event_name,
        "EVET_ACT_NM": action,
        "EVET_ACT_CATG_NM": category,
        "EVET_ACT_LABE_NM": label,
        "PAGE_STAY_TM": page_stay,
        "REP_CHNL_MENU_NM": menu,
        "REP_CHNL_MENU_LVL1_NM": level1,
        "REP_CHNL_MENU_LVL2_NM": level2,
        "REP_CHNL_MENU_LVL3_NM": level3,
        "ABTEST_ID": abtest_id,
        "BQ_LOAD_DTTM": loaded_at.isoformat(timespec="seconds"),
        "BQ_LOAD_USER_ID": "synthetic-seeder",
    }


def _add_vas_baseline(rows: list[TableRow], config: SeedConfig, rng: random.Random) -> None:
    favorite_indices = set(range(1, 85))
    unreachable_indices = set(range(100, 197))
    for index in range(1, 341):
        identity = _identity("vas", "baseline", index)
        original_day = config.start_date + timedelta(days=(index - 1) % 7)
        campaign_day = config.start_date + timedelta(days=_VAS_CRM_CAMPAIGN_DAY_OFFSET)
        day = (
            max(original_day, campaign_day)
            if index in _VAS_CRM_CHANGE_SEARCHER_INDICES
            else original_day
        )
        started_at = datetime.combine(day, time(hour=9 + index % 8, minute=index % 6 * 5))
        session_id = f"SESN-VAS-B-{index:04d}"
        session_stay = rng.randint(60, 180)
        path = _VAS_UNREACHABLE_PATH if index in unreachable_indices else _VAS_REACHABLE_PATH
        cursor = started_at
        for step, menu in enumerate(path, start=1):
            page_stay = rng.randint(1, 4)
            is_last = step == len(path)
            label = "vas_unreachable" if is_last and index in unreachable_indices else "navigating"
            rows.append(
                _ga_row(
                    identity=identity,
                    occurred_at=cursor,
                    session_id=session_id,
                    session_stay=session_stay,
                    event_name="page_view",
                    action="menu_view",
                    category="vas_wandering",
                    label=label,
                    page_stay=page_stay,
                    menu=menu,
                    abtest_id="CONTROL",
                    ga_link_key=identity.cz_link_key * 100 + step,
                )
            )
            cursor += timedelta(seconds=page_stay + rng.randint(5, 12))
        if index in favorite_indices:
            rows.append(
                _ga_row(
                    identity=identity,
                    occurred_at=cursor,
                    session_id=session_id,
                    session_stay=session_stay,
                    event_name="click",
                    action="favorite_set",
                    category="vas_wandering",
                    label="favorite_completed",
                    page_stay=1,
                    menu="부가서비스 조회/해지",
                    abtest_id="CONTROL",
                    ga_link_key=identity.cz_link_key * 100 + 99,
                )
            )


def _add_vas_search_context(tables: dict[str, list[TableRow]], config: SeedConfig) -> None:
    search_rows = tables["L0UR_SEARCH_HISTORY"]
    feedback_rows = tables["L0UR_FEEDBACK"]
    for index in range(1, 181):
        identity = _identity("vas", "baseline", index)
        original_day = config.start_date + timedelta(days=(index - 1) % 7)
        campaign_day = config.start_date + timedelta(days=_VAS_CRM_CAMPAIGN_DAY_OFFSET)
        # CRM 수신 고객의 검색은 캠페인 발송 이후로 모아, 제한 Source에서는 검색 급증만
        # 보이고 CRM Source를 추가했을 때 발송 시점과 변경 의도를 연결할 수 있게 한다.
        day = (
            max(original_day, campaign_day)
            if index in _VAS_CRM_CHANGE_SEARCHER_INDICES
            else original_day
        )
        attempts = 2 if index <= 120 else 1
        for attempt in range(1, attempts + 1):
            created_at = datetime.combine(day, time(18, 0)) + timedelta(minutes=attempt * 10)
            run_id = f"RUN-VAS-B-{index:04d}-{attempt}"
            failed = index <= 120
            query = (
                _VAS_GOOGLE_ONE_CHANGE_QUERIES[
                    (index + attempt) % len(_VAS_GOOGLE_ONE_CHANGE_QUERIES)
                ]
                if index in _VAS_CRM_CHANGE_SEARCHER_INDICES
                else _VAS_QUERIES[(index + attempt) % len(_VAS_QUERIES)]
            )
            search_rows.append(
                {
                    "CZ_LNK_KEY": identity.cz_link_key,
                    "P_YYYYMMDD": day.isoformat(),
                    "ID": 100_000 + index * 10 + attempt,
                    "THREAD_ID": f"THREAD-VAS-B-{index:04d}",
                    "RUN_ID": run_id,
                    "SEARCH_QUERY": query,
                    "SEARCH_RESULT": "가입정보 메뉴에서 부가서비스를 확인할 수 있습니다.",
                    "CREATED_AT": created_at.isoformat(timespec="seconds"),
                    "STATUS": "failed" if failed else "completed",
                    "FIRST_RESPONSE_LATENCY_MS": 650.0 + (index % 7) * 35,
                    "WAS_CACHE_HIT": attempt > 1,
                    "SEARCH_QUERY_TYPE": "repeat" if attempt > 1 else "initial",
                    "REWRITE_SEARCH_QUERY": "부가서비스 조회/해지",
                    "SEARCH_RESULT_REFERENCE_TEMPLATE_NAME": "VAS_GUIDE_NO_CTA",
                    "IS_FALLBACK_SEARCH_RESULT": "N",
                    "BQ_LOAD_DTTM": (created_at + timedelta(hours=2)).isoformat(timespec="seconds"),
                    "BQ_LOAD_USER_ID": "synthetic-seeder",
                }
            )
        if index <= 90:
            run_id = f"RUN-VAS-B-{index:04d}-{attempts}"
            feedback_at = datetime.combine(day, time(18, 0)) + timedelta(minutes=attempts * 10 + 2)
            feedback_rows.append(
                {
                    "CZ_LNK_KEY": identity.cz_link_key,
                    "P_YYYYMMDD": day.isoformat(),
                    "ID": 110_000 + index,
                    "RUN_ID": run_id,
                    "FEEDBACK_TYPE": "negative",
                    "REASON": "답변은 맞지만 이동 방법을 모르겠음",
                    "OPTION": "바로가기 없음",
                    "BQ_LOAD_DTTM": (feedback_at + timedelta(hours=2)).isoformat(
                        timespec="seconds"
                    ),
                    "BQ_LOAD_USER_ID": "synthetic-seeder",
                }
            )


def _add_vas_voc_context(tables: dict[str, list[TableRow]], config: SeedConfig) -> None:
    voc_rows = tables["L1RA_VOC_STT_DTL_H"]
    for index in range(60, 121):
        identity = _identity("vas", "baseline", index)
        original_day = config.start_date + timedelta(days=(index - 1) % 7)
        campaign_day = config.start_date + timedelta(days=_VAS_CRM_CAMPAIGN_DAY_OFFSET)
        day = max(original_day, campaign_day)
        occurred_at = datetime.combine(day, time(20, index % 60))
        voc_rows.append(
            {
                "P_YYYYMMDD": day.isoformat(),
                "CZ_LNK_KEY": identity.cz_link_key,
                "BASE_DT": day.strftime("%Y%m%d"),
                "CALL_ID": f"CALL-VAS-B-{index:04d}",
                "CALL_CRTE_DTTM": occurred_at.isoformat(timespec="seconds"),
                "CUST_CNSL_TM": 240 + index % 180,
                "STT_TXT_CNTN": "부가서비스를 해지하려는데 메뉴를 못 찾겠어요.",
                "INQU_CNTN": "부가서비스 조회/해지 메뉴 위치 문의",
                "CSLR_PRSS_CNTN": "상담원이 가입 서비스 확인 후 해지 처리",
                "CNSL_ALL_SMRY_CNTN": "어디서 해지하는지 몰라 상담원에게 문의함",
                "CUST_SNMT_NM": "불편",
                "CNSL_SBJC_TIT_NM": "부가서비스 해지",
                "CNSL_SCLS_CD": "VAS-MENU-01",
                "CNSL_THMA_NM": "부가서비스 조회/해지",
                "ENTR_NO": identity.entry_no,
                "CUST_NO": identity.customer_no,
                "BQ_LOAD_DTTM": (occurred_at + timedelta(hours=2)).isoformat(timespec="seconds"),
                "BQ_LOAD_USER_ID": "synthetic-seeder",
            }
        )


def _billing_row(
    identity: _CustomerIdentity,
    *,
    snapshot_day: date,
    age: int,
    service_amount: int,
    micropayment_amount: int,
) -> TableRow:
    return {
        "CZ_LNK_KEY": identity.cz_link_key,
        "BASE_YYMM": snapshot_day.strftime("%Y%m"),
        "BILL_ACNT_NO": f"BILL-{identity.cz_link_key}",
        "ENTR_NO": identity.entry_no,
        "CUST_NO": identity.customer_no,
        "YY10_AGELV_ID": age // 10,
        "CUST_AGE": age,
        "PP_CD": "5G-STD-01",
        "PP_NM": "5G 스탠다드",
        "ENTR_STTS_CD": "A",
        "FRST_ENTR_DT": "20230801",
        "SPPS_AMT": service_amount,
        "SMLS_STLM_AMT": micropayment_amount,
        "TOT_BILL_AMT": 75_000 + service_amount + micropayment_amount,
        "DP_LOAD_DTTM": f"{snapshot_day.isoformat()}T23:00:00",
        "DP_LOAD_USER_ID": "synthetic-seeder",
        "SEX_DV_CD": "M" if identity.cz_link_key % 2 else "F",
    }


def _add_vas_profiles(tables: dict[str, list[TableRow]], config: SeedConfig) -> None:
    profile_rows = tables["L2ZI_MBL_VAS_ENTR_INFO_DALY_H"]
    billing_rows = tables["L1BAT_CUST_BLNG_AND_BNFT_SUM"]
    for index in range(1, 341):
        identity = _identity("vas", "baseline", index)
        day = config.start_date + timedelta(days=(index - 1) % 7)
        products = (
            (_VAS_PRODUCTS[0], _VAS_GOOGLE_ONE_PRODUCT, _VAS_PRODUCTS[2])
            if index in _VAS_CRM_RECIPIENT_INDICES
            else _VAS_PRODUCTS
        )
        for sequence, (product_code, product_name, amount) in enumerate(products, start=1):
            profile_rows.append(
                {
                    "P_YYYYMMDD": day.isoformat(),
                    "BASE_YYMM": day.strftime("%Y%m"),
                    "ENTR_NO": identity.entry_no,
                    "ENTR_SVC_SEQNO": f"{identity.entry_no}-{sequence}",
                    "CUST_NO": identity.customer_no,
                    "PROD_CD": product_code,
                    "PROD_NM": product_name,
                    "BUY_PRC_YN": "Y" if amount else "N",
                    "VAT_INCL_ALL_AMT": amount,
                    "SVC_STTS_CD": "A",
                    "SVC_STRT_DT": "2023-08-01",
                    "SVC_END_DT": "9999-12-31",
                    "SRVL_YN": "Y",
                    "EXPY_YN": "N",
                    "PROD_ENTR_DAYS": (day - date(2023, 8, 1)).days,
                    "PROD_ENTR_MMCT": (day.year - 2023) * 12 + day.month - 8,
                    "ATRC_CHNL_DIVS_NM": "디지털",
                    "EXPY_CHNL_DIVS_NM": "",
                    "BQ_LOAD_DTTM": f"{day.isoformat()}T23:00:00",
                    "BQ_LOAD_USER_ID": "synthetic-seeder",
                }
            )
        billing_rows.append(
            _billing_row(
                identity,
                snapshot_day=day,
                age=25 + index % 36,
                service_amount=sum(product[2] for product in products),
                micropayment_amount=0,
            )
        )


def _add_vas_crm_campaign(tables: dict[str, list[TableRow]], config: SeedConfig) -> None:
    """Add one delivered CRM campaign to Google One subscribers in the baseline cohort."""

    rows = tables["L1CM_CRM_MSG_SEND_H"]
    campaign_day = config.start_date + timedelta(days=_VAS_CRM_CAMPAIGN_DAY_OFFSET)
    sent_at = datetime.combine(campaign_day, time(8, 0))
    for index in sorted(_VAS_CRM_RECIPIENT_INDICES):
        identity = _identity("vas", "baseline", index)
        rows.append(
            {
                "P_YYYYMMDD": campaign_day.isoformat(),
                "CZ_LNK_KEY": identity.cz_link_key,
                "BASE_DT": campaign_day.strftime("%Y%m%d"),
                "MESSAGE_ID": f"CRM-G1-20260907-{index:04d}",
                "CAMPAIGN_ID": "CMP-G1-OPTION-202609",
                "CAMPAIGN_NM": "구글 원 세부 옵션 변경 기능 안내",
                "MESSAGE_TEMPLATE_ID": "SMS-G1-OPTION-CHANGE-V1",
                "SEND_DTTM": sent_at.isoformat(timespec="seconds"),
                "CHANNEL_CD": "SMS",
                "SEND_RESULT_CD": "DELIVERED",
                "TARGET_SEGMENT_NM": "구글 원 100GB 부가서비스 가입자",
                "TARGET_PROD_CD": _VAS_GOOGLE_ONE_PRODUCT[0],
                "TARGET_PROD_NM": _VAS_GOOGLE_ONE_PRODUCT[1],
                "FEATURE_NM": "구글 원 저장공간 옵션 변경",
                "MESSAGE_CNTN": (
                    "구글 원 이용 고객님, 9월부터 저장공간 옵션을 변경할 수 있습니다. "
                    "자세한 내용은 U+ 앱에서 확인해 주세요."
                ),
                "ENTR_NO": identity.entry_no,
                "CUST_NO": identity.customer_no,
                "BQ_LOAD_DTTM": (sent_at + timedelta(hours=2)).isoformat(timespec="seconds"),
                "BQ_LOAD_USER_ID": "synthetic-seeder",
            }
        )


def _add_payment_baseline(rows: list[TableRow], config: SeedConfig, rng: random.Random) -> None:
    session_counter = 0
    for index in range(1, 211):
        identity = _identity("payment", "baseline", index)
        attempt_count = 3 if index <= 147 else 2
        base_day = config.start_date + timedelta(days=(index - 1) % 4)
        for attempt in range(1, attempt_count + 1):
            session_counter += 1
            day_offset = (0, 1, 3)[attempt - 1]
            day = base_day + timedelta(days=day_offset)
            cursor = datetime.combine(
                day,
                time(hour=10 + index % 7, minute=attempt * 5),
            )
            session_id = f"SESN-PAY-B-{index:04d}-{attempt}"
            session_stay = rng.randint(20, 60)
            consent_exit = session_counter <= 465
            actions = [
                "limit_page_entered",
                "limit_slider_changed",
                "consent_sheet_shown",
            ]
            if consent_exit:
                actions.append("consent_sheet_closed")
            else:
                actions.extend(["consent_checked", "identity_verification_failed"])
            for step, action in enumerate(actions, start=1):
                is_last = step == len(actions)
                page_stay = (
                    rng.randint(3, 10) if action == "consent_sheet_closed" else rng.randint(2, 8)
                )
                rows.append(
                    _ga_row(
                        identity=identity,
                        occurred_at=cursor,
                        session_id=session_id,
                        session_stay=session_stay,
                        event_name="interaction",
                        action=action,
                        category="payment_limit_change",
                        label="payment_incomplete" if is_last else "limit_150000",
                        page_stay=page_stay,
                        menu="결제 한도 설정/변경",
                        abtest_id="CONTROL",
                        ga_link_key=(identity.cz_link_key * 10_000 + attempt * 100 + step),
                    )
                )
                cursor += timedelta(seconds=page_stay + rng.randint(1, 4))


def _add_payment_success_controls(
    rows: list[TableRow], config: SeedConfig, rng: random.Random
) -> None:
    actions = (
        "limit_page_entered",
        "limit_slider_changed",
        "consent_sheet_shown",
        "consent_checked",
        "identity_verified",
        "limit_change_completed",
    )
    for offset in range(90):
        index = 1_001 + offset
        identity = _identity("payment", "baseline", index)
        day = config.start_date + timedelta(days=offset % 7)
        cursor = datetime.combine(day, time(hour=11 + offset % 6, minute=20))
        session_id = f"SESN-PAY-B-C-{offset + 1:04d}"
        session_stay = rng.randint(35, 75)
        for step, action in enumerate(actions, start=1):
            rows.append(
                _ga_row(
                    identity=identity,
                    occurred_at=cursor,
                    session_id=session_id,
                    session_stay=session_stay,
                    event_name="interaction",
                    action=action,
                    category="payment_limit_change",
                    label="payment_completed" if step == len(actions) else "limit_150000",
                    page_stay=rng.randint(2, 8),
                    menu="결제 한도 설정/변경",
                    abtest_id="CONTROL",
                    ga_link_key=identity.cz_link_key * 10_000 + step,
                )
            )
            cursor += timedelta(seconds=rng.randint(4, 10))


def _payment_last_attempt_day(config: SeedConfig, index: int) -> datetime:
    base_day = config.start_date + timedelta(days=(index - 1) % 4)
    offset = 3 if index <= 147 else 1
    return datetime.combine(base_day + timedelta(days=offset), time(19, 0))


def _add_payment_search_context(tables: dict[str, list[TableRow]], config: SeedConfig) -> None:
    searches = tables["L0UR_SEARCH_HISTORY"]
    feedback = tables["L0UR_FEEDBACK"]
    for index in range(1, 151):
        identity = _identity("payment", "baseline", index)
        base_time = _payment_last_attempt_day(config, index)
        for attempt in range(1, 3):
            created_at = base_time + timedelta(minutes=attempt * 10)
            run_id = f"RUN-PAY-B-{index:04d}-{attempt}"
            searches.append(
                {
                    "CZ_LNK_KEY": identity.cz_link_key,
                    "P_YYYYMMDD": created_at.date().isoformat(),
                    "ID": 200_000 + index * 10 + attempt,
                    "THREAD_ID": f"THREAD-PAY-B-{index:04d}",
                    "RUN_ID": run_id,
                    "SEARCH_QUERY": _PAYMENT_QUERIES[(index + attempt) % len(_PAYMENT_QUERIES)],
                    "SEARCH_RESULT": "한도 선택 후 동의와 본인인증을 완료해야 합니다.",
                    "CREATED_AT": created_at.isoformat(timespec="seconds"),
                    "STATUS": "failed",
                    "FIRST_RESPONSE_LATENCY_MS": 720.0 + (index % 9) * 30,
                    "WAS_CACHE_HIT": attempt > 1,
                    "SEARCH_QUERY_TYPE": "repeat" if attempt > 1 else "initial",
                    "REWRITE_SEARCH_QUERY": "소액결제 한도 변경",
                    "SEARCH_RESULT_REFERENCE_TEMPLATE_NAME": "PAYMENT_GUIDE_V1",
                    "IS_FALLBACK_SEARCH_RESULT": "N",
                    "BQ_LOAD_DTTM": (created_at + timedelta(hours=2)).isoformat(timespec="seconds"),
                    "BQ_LOAD_USER_ID": "synthetic-seeder",
                }
            )
        if index <= 100:
            feedback_at = base_time + timedelta(minutes=22)
            feedback.append(
                {
                    "CZ_LNK_KEY": identity.cz_link_key,
                    "P_YYYYMMDD": feedback_at.date().isoformat(),
                    "ID": 210_000 + index,
                    "RUN_ID": f"RUN-PAY-B-{index:04d}-2",
                    "FEEDBACK_TYPE": "negative",
                    "REASON": "안내대로 했는데 한도 변경이 완료되지 않음",
                    "OPTION": "실제 화면과 다름",
                    "BQ_LOAD_DTTM": (feedback_at + timedelta(hours=2)).isoformat(
                        timespec="seconds"
                    ),
                    "BQ_LOAD_USER_ID": "synthetic-seeder",
                }
            )


def _add_payment_voc_context(tables: dict[str, list[TableRow]], config: SeedConfig) -> None:
    voc_rows = tables["L1RA_VOC_STT_DTL_H"]
    for index in range(1, 75):
        identity = _identity("payment", "baseline", index)
        occurred_at = _payment_last_attempt_day(config, index) + timedelta(hours=2)
        voc_rows.append(
            {
                "P_YYYYMMDD": occurred_at.date().isoformat(),
                "CZ_LNK_KEY": identity.cz_link_key,
                "BASE_DT": occurred_at.strftime("%Y%m%d"),
                "CALL_ID": f"CALL-PAY-B-{index:04d}",
                "CALL_CRTE_DTTM": occurred_at.isoformat(timespec="seconds"),
                "CUST_CNSL_TM": 300 + index % 150,
                "STT_TXT_CNTN": "한도 변경을 여러 번 했는데 동의 화면에서 계속 막혀요.",
                "INQU_CNTN": "소액결제 한도 변경 실패 문의",
                "CSLR_PRSS_CNTN": "상담원이 본인 확인 후 한도 변경 처리",
                "CNSL_ALL_SMRY_CNTN": "동의 단계 이후 한도 변경이 완료되지 않아 문의함",
                "CUST_SNMT_NM": "불만",
                "CNSL_SBJC_TIT_NM": "소액결제 한도 변경",
                "CNSL_SCLS_CD": "PAY-LIMIT-01",
                "CNSL_THMA_NM": "소액결제 한도",
                "ENTR_NO": identity.entry_no,
                "CUST_NO": identity.customer_no,
                "BQ_LOAD_DTTM": (occurred_at + timedelta(hours=2)).isoformat(timespec="seconds"),
                "BQ_LOAD_USER_ID": "synthetic-seeder",
            }
        )


def _add_payment_billing_profiles(tables: dict[str, list[TableRow]], config: SeedConfig) -> None:
    billing_rows = tables["L1BAT_CUST_BLNG_AND_BNFT_SUM"]
    for index in range(1, 211):
        billing_rows.append(
            _billing_row(
                _identity("payment", "baseline", index),
                snapshot_day=_payment_last_attempt_day(config, index).date(),
                age=22 + index % 40,
                service_amount=3_300 if index % 3 == 0 else 0,
                micropayment_amount=10_000 + (index % 6) * 5_000,
            )
        )
    for offset in range(90):
        billing_rows.append(
            _billing_row(
                _identity("payment", "baseline", 1_001 + offset),
                snapshot_day=config.start_date + timedelta(days=offset % 7),
                age=22 + offset % 40,
                service_amount=3_300 if offset % 3 == 0 else 0,
                micropayment_amount=0,
            )
        )


def _post_identity(case: str, day_index: int, customer_index: int) -> _CustomerIdentity:
    return _identity(case, "post", day_index * 100 + customer_index)


def _add_vas_post_ga(
    tables: dict[str, list[TableRow]], config: SeedConfig, rng: random.Random
) -> None:
    rows = tables["L1DA_GA_REP_CHNL_BEHV_L"]
    wrong_step_counts = (4, 4, 3, 3, 2, 2, 1)
    for day_index, exposure_rate in enumerate(config.exposure_rates):
        day = config.intervention_at.date() + timedelta(days=day_index)
        exposed_count = round(50 * exposure_rate)
        direct_count = _VAS_POST_DIRECT[day_index]
        unreachable_count = _VAS_POST_UNREACHABLE[day_index]
        treatment_indices = set(range(1, exposed_count + 1))
        control_indices = set(range(exposed_count + 1, 51))
        control_direct_count = min(round(len(control_indices) * 0.20), direct_count)
        treatment_direct_count = direct_count - control_direct_count
        direct_indices = set(sorted(treatment_indices)[:treatment_direct_count]) | set(
            sorted(control_indices)[:control_direct_count]
        )
        treatment_remaining = sorted(treatment_indices - direct_indices, reverse=True)
        control_remaining = sorted(control_indices - direct_indices, reverse=True)
        preferred_treatment_unreachable = max(
            0, unreachable_count - round(len(control_indices) * 0.28)
        )
        treatment_unreachable_count = min(
            preferred_treatment_unreachable,
            len(treatment_remaining),
        )
        control_unreachable_count = unreachable_count - treatment_unreachable_count
        if control_unreachable_count > len(control_remaining):
            overflow = control_unreachable_count - len(control_remaining)
            control_unreachable_count -= overflow
            treatment_unreachable_count += overflow
        unreachable_indices = set(treatment_remaining[:treatment_unreachable_count]) | set(
            control_remaining[:control_unreachable_count]
        )
        wandering_indices = [
            index
            for index in range(1, 51)
            if index not in direct_indices and index not in unreachable_indices
        ]
        favorite_indices = set(wandering_indices[: _VAS_POST_FAVORITES[day_index]])
        for index in range(1, 51):
            identity = _post_identity("vas", day_index, index)
            started_at = datetime.combine(day, time(10 + index % 7, index % 6 * 5))
            session_id = f"SESN-VAS-P-{day_index + 1}-{index:03d}"
            abtest_id = "VAS_AI_CTA_V1" if index <= exposed_count else "CONTROL"
            session_stay = rng.randint(35, 100)
            if index in direct_indices:
                rows.append(
                    _ga_row(
                        identity=identity,
                        occurred_at=started_at,
                        session_id=session_id,
                        session_stay=session_stay,
                        event_name="click",
                        action="cta_direct_open",
                        category="vas_navigation",
                        label="vas_direct_reach",
                        page_stay=rng.randint(8, 20),
                        menu="부가서비스 조회/해지",
                        abtest_id=abtest_id,
                        ga_link_key=identity.cz_link_key * 100 + 1,
                    )
                )
                continue

            if index in unreachable_indices:
                path = ("마이", "요금제 조회/변경", "마이", "전체메뉴")
            else:
                wrong_steps = wrong_step_counts[day_index]
                candidates = ("마이", "요금제 조회/변경", "마이", "가입정보")
                path = (*candidates[:wrong_steps], "부가서비스 조회/해지")
            cursor = started_at
            for step, menu in enumerate(path, start=1):
                is_last = step == len(path)
                label = "navigating"
                if is_last:
                    label = (
                        "vas_unreachable"
                        if index in unreachable_indices
                        else "vas_wandering_reached"
                    )
                page_stay = rng.randint(1, 4)
                rows.append(
                    _ga_row(
                        identity=identity,
                        occurred_at=cursor,
                        session_id=session_id,
                        session_stay=session_stay,
                        event_name="page_view",
                        action="menu_view",
                        category="vas_navigation",
                        label=label,
                        page_stay=page_stay,
                        menu=menu,
                        abtest_id=abtest_id,
                        ga_link_key=identity.cz_link_key * 100 + step,
                    )
                )
                cursor += timedelta(seconds=page_stay + rng.randint(3, 8))
            if index in favorite_indices:
                rows.append(
                    _ga_row(
                        identity=identity,
                        occurred_at=cursor,
                        session_id=session_id,
                        session_stay=session_stay,
                        event_name="click",
                        action="favorite_set",
                        category="vas_navigation",
                        label="favorite_completed",
                        page_stay=1,
                        menu="부가서비스 조회/해지",
                        abtest_id=abtest_id,
                        ga_link_key=identity.cz_link_key * 100 + 99,
                    )
                )


def _add_vas_post_context(tables: dict[str, list[TableRow]], config: SeedConfig) -> None:
    searches = tables["L0UR_SEARCH_HISTORY"]
    feedback = tables["L0UR_FEEDBACK"]
    voc = tables["L1RA_VOC_STT_DTL_H"]
    profiles = tables["L2ZI_MBL_VAS_ENTR_INFO_DALY_H"]
    billing = tables["L1BAT_CUST_BLNG_AND_BNFT_SUM"]
    for day_index, exposure_rate in enumerate(config.exposure_rates):
        day = config.intervention_at.date() + timedelta(days=day_index)
        exposed_count = round(50 * exposure_rate)
        for index in range(1, 51):
            identity = _post_identity("vas", day_index, index)
            base_time = datetime.combine(day, time(18, 0)) + timedelta(minutes=index)
            attempts = 2 if index <= _VAS_POST_REPEATS[day_index] else 1
            for attempt in range(1, attempts + 1):
                occurred_at = base_time + timedelta(minutes=attempt * 5)
                searches.append(
                    {
                        "CZ_LNK_KEY": identity.cz_link_key,
                        "P_YYYYMMDD": day.isoformat(),
                        "ID": 300_000 + day_index * 1_000 + index * 10 + attempt,
                        "THREAD_ID": f"THREAD-VAS-P-{day_index + 1}-{index:03d}",
                        "RUN_ID": f"RUN-VAS-P-{day_index + 1}-{index:03d}-{attempt}",
                        "SEARCH_QUERY": _VAS_QUERIES[(index + attempt) % len(_VAS_QUERIES)],
                        "SEARCH_RESULT": "부가서비스 조회/해지 화면으로 이동할 수 있습니다.",
                        "CREATED_AT": occurred_at.isoformat(timespec="seconds"),
                        "STATUS": "completed" if index <= exposed_count else "failed",
                        "FIRST_RESPONSE_LATENCY_MS": 520.0 + index % 8 * 20,
                        "WAS_CACHE_HIT": attempt > 1,
                        "SEARCH_QUERY_TYPE": "repeat" if attempt > 1 else "initial",
                        "REWRITE_SEARCH_QUERY": "부가서비스 조회/해지",
                        "SEARCH_RESULT_REFERENCE_TEMPLATE_NAME": (
                            "VAS_GUIDE_WITH_CTA" if index <= exposed_count else "VAS_GUIDE_NO_CTA"
                        ),
                        "IS_FALLBACK_SEARCH_RESULT": "N",
                        "BQ_LOAD_DTTM": (occurred_at + timedelta(hours=2)).isoformat(
                            timespec="seconds"
                        ),
                        "BQ_LOAD_USER_ID": "synthetic-seeder",
                    }
                )
            if index <= _VAS_POST_NEGATIVE_FEEDBACK[day_index]:
                feedback_at = base_time + timedelta(minutes=attempts * 5 + 2)
                feedback.append(
                    {
                        "CZ_LNK_KEY": identity.cz_link_key,
                        "P_YYYYMMDD": day.isoformat(),
                        "ID": 310_000 + day_index * 100 + index,
                        "RUN_ID": (f"RUN-VAS-P-{day_index + 1}-{index:03d}-{attempts}"),
                        "FEEDBACK_TYPE": "negative",
                        "REASON": "이동 안내가 충분하지 않음",
                        "OPTION": "VAS 개선 안내 불충분",
                        "BQ_LOAD_DTTM": (feedback_at + timedelta(hours=2)).isoformat(
                            timespec="seconds"
                        ),
                        "BQ_LOAD_USER_ID": "synthetic-seeder",
                    }
                )
            for sequence, (product_code, product_name, amount) in enumerate(_VAS_PRODUCTS, start=1):
                profiles.append(
                    {
                        "P_YYYYMMDD": day.isoformat(),
                        "BASE_YYMM": day.strftime("%Y%m"),
                        "ENTR_NO": identity.entry_no,
                        "ENTR_SVC_SEQNO": f"{identity.entry_no}-{sequence}",
                        "CUST_NO": identity.customer_no,
                        "PROD_CD": product_code,
                        "PROD_NM": product_name,
                        "BUY_PRC_YN": "Y",
                        "VAT_INCL_ALL_AMT": amount,
                        "SVC_STTS_CD": "A",
                        "SVC_STRT_DT": "2023-08-01",
                        "SVC_END_DT": "9999-12-31",
                        "SRVL_YN": "Y",
                        "EXPY_YN": "N",
                        "PROD_ENTR_DAYS": (day - date(2023, 8, 1)).days,
                        "PROD_ENTR_MMCT": (day.year - 2023) * 12 + day.month - 8,
                        "ATRC_CHNL_DIVS_NM": "디지털",
                        "EXPY_CHNL_DIVS_NM": "",
                        "BQ_LOAD_DTTM": f"{day.isoformat()}T23:00:00",
                        "BQ_LOAD_USER_ID": "synthetic-seeder",
                    }
                )
            billing.append(
                _billing_row(
                    identity,
                    snapshot_day=day,
                    age=25 + index % 36,
                    service_amount=sum(product[2] for product in _VAS_PRODUCTS),
                    micropayment_amount=0,
                )
            )
        for index in range(1, _VAS_POST_VOC[day_index] + 1):
            identity = _post_identity("vas", day_index, index)
            occurred_at = datetime.combine(day, time(20, index))
            voc.append(
                {
                    "P_YYYYMMDD": day.isoformat(),
                    "CZ_LNK_KEY": identity.cz_link_key,
                    "BASE_DT": day.strftime("%Y%m%d"),
                    "CALL_ID": f"CALL-VAS-P-{day_index + 1}-{index:03d}",
                    "CALL_CRTE_DTTM": occurred_at.isoformat(timespec="seconds"),
                    "CUST_CNSL_TM": 220 + index,
                    "STT_TXT_CNTN": "부가서비스 메뉴 이동 방법을 문의합니다.",
                    "INQU_CNTN": "부가서비스 조회/해지 메뉴 위치 문의",
                    "CSLR_PRSS_CNTN": "상담원이 바로가기 경로 안내",
                    "CNSL_ALL_SMRY_CNTN": "앱 메뉴 위치를 찾지 못해 문의함",
                    "CUST_SNMT_NM": "불편",
                    "CNSL_SBJC_TIT_NM": "부가서비스 해지",
                    "CNSL_SCLS_CD": "VAS-MENU-01",
                    "CNSL_THMA_NM": "부가서비스 조회/해지",
                    "ENTR_NO": identity.entry_no,
                    "CUST_NO": identity.customer_no,
                    "BQ_LOAD_DTTM": (occurred_at + timedelta(hours=2)).isoformat(
                        timespec="seconds"
                    ),
                    "BQ_LOAD_USER_ID": "synthetic-seeder",
                }
            )


def _payment_attempt_rows(
    *,
    identity: _CustomerIdentity,
    occurred_at: datetime,
    session_id: str,
    completed: bool,
    consent_exit: bool,
    abtest_id: str,
    rng: random.Random,
) -> list[TableRow]:
    actions = ["limit_page_entered", "limit_slider_changed", "consent_sheet_shown"]
    if completed:
        actions.extend(["consent_checked", "identity_verified", "limit_change_completed"])
    elif consent_exit:
        actions.append("consent_sheet_closed")
    else:
        actions.extend(["consent_checked", "identity_verification_failed"])
    rows = []
    cursor = occurred_at
    for step, action in enumerate(actions, start=1):
        is_last = step == len(actions)
        rows.append(
            _ga_row(
                identity=identity,
                occurred_at=cursor,
                session_id=session_id,
                session_stay=rng.randint(25, 70),
                event_name="interaction",
                action=action,
                category="payment_limit_change",
                label=(
                    "payment_completed"
                    if completed and is_last
                    else "payment_incomplete"
                    if not completed and is_last
                    else "limit_150000"
                ),
                page_stay=rng.randint(2, 8),
                menu="결제 한도 설정/변경",
                abtest_id=abtest_id,
                ga_link_key=identity.cz_link_key * 10_000 + int(session_id[-1]) * 100 + step,
            )
        )
        cursor += timedelta(seconds=rng.randint(4, 10))
    return rows


def _add_payment_post(
    tables: dict[str, list[TableRow]], config: SeedConfig, rng: random.Random
) -> None:
    ga_rows = tables["L1DA_GA_REP_CHNL_BEHV_L"]
    searches = tables["L0UR_SEARCH_HISTORY"]
    feedback = tables["L0UR_FEEDBACK"]
    voc = tables["L1RA_VOC_STT_DTL_H"]
    billing = tables["L1BAT_CUST_BLNG_AND_BNFT_SUM"]
    for day_index, exposure_rate in enumerate(config.exposure_rates):
        day = config.intervention_at.date() + timedelta(days=day_index)
        exposed_count = round(40 * exposure_rate)
        completed_count = _PAYMENT_POST_COMPLETED[day_index]
        treatment_indices = set(range(1, exposed_count + 1))
        control_indices = set(range(exposed_count + 1, 41))
        control_completed_count = min(round(len(control_indices) * 0.30), completed_count)
        treatment_completed_count = completed_count - control_completed_count
        completed_indices = set(sorted(treatment_indices)[:treatment_completed_count]) | set(
            sorted(control_indices)[:control_completed_count]
        )
        incomplete_indices = sorted(set(range(1, 41)) - completed_indices)
        incomplete_rank = {
            customer_index: rank for rank, customer_index in enumerate(incomplete_indices, start=1)
        }
        control_incomplete = sorted(control_indices - completed_indices)
        treatment_incomplete = sorted(treatment_indices - completed_indices)
        target_consent_exits = _PAYMENT_POST_CONSENT_EXITS[day_index]
        control_consent_count = min(round(len(control_incomplete) * 0.82), target_consent_exits)
        treatment_consent_count = target_consent_exits - control_consent_count
        if treatment_consent_count > len(treatment_incomplete):
            overflow = treatment_consent_count - len(treatment_incomplete)
            treatment_consent_count -= overflow
            control_consent_count += overflow
        consent_exit_indices = set(control_incomplete[:control_consent_count]) | set(
            treatment_incomplete[:treatment_consent_count]
        )
        incomplete_count = len(incomplete_indices)
        retry_count = min(_PAYMENT_POST_RETRIES[day_index], incomplete_count)
        for index in range(1, 41):
            identity = _post_identity("payment", day_index, index)
            completed = index in completed_indices
            incomplete_index = incomplete_rank.get(index, 0)
            consent_exit = index in consent_exit_indices
            attempts = 2 if not completed and incomplete_index <= retry_count else 1
            abtest_id = "PAYMENT_CONSENT_V1" if index <= exposed_count else "CONTROL"
            for attempt in range(1, attempts + 1):
                occurred_at = datetime.combine(day, time(9 + index % 8, minute=attempt * 8))
                ga_rows.extend(
                    _payment_attempt_rows(
                        identity=identity,
                        occurred_at=occurred_at,
                        session_id=f"SESN-PAY-P-{day_index + 1}-{index:03d}-{attempt}",
                        completed=completed,
                        consent_exit=consent_exit,
                        abtest_id=abtest_id,
                        rng=rng,
                    )
                )
            if not completed:
                repeat = incomplete_index <= _PAYMENT_POST_REPEAT_SEARCHES[day_index]
                search_attempts = 2 if repeat else 1
                base_time = datetime.combine(day, time(18, 0)) + timedelta(minutes=index)
                for search_attempt in range(1, search_attempts + 1):
                    occurred_at = base_time + timedelta(minutes=search_attempt * 5)
                    searches.append(
                        {
                            "CZ_LNK_KEY": identity.cz_link_key,
                            "P_YYYYMMDD": day.isoformat(),
                            "ID": (400_000 + day_index * 1_000 + index * 10 + search_attempt),
                            "THREAD_ID": f"THREAD-PAY-P-{day_index + 1}-{index:03d}",
                            "RUN_ID": (f"RUN-PAY-P-{day_index + 1}-{index:03d}-{search_attempt}"),
                            "SEARCH_QUERY": _PAYMENT_QUERIES[
                                (index + search_attempt) % len(_PAYMENT_QUERIES)
                            ],
                            "SEARCH_RESULT": "동의 절차와 본인인증 단계를 확인합니다.",
                            "CREATED_AT": occurred_at.isoformat(timespec="seconds"),
                            "STATUS": "completed" if index <= exposed_count else "failed",
                            "FIRST_RESPONSE_LATENCY_MS": 580.0 + index % 8 * 20,
                            "WAS_CACHE_HIT": search_attempt > 1,
                            "SEARCH_QUERY_TYPE": ("repeat" if search_attempt > 1 else "initial"),
                            "REWRITE_SEARCH_QUERY": "소액결제 한도 변경",
                            "SEARCH_RESULT_REFERENCE_TEMPLATE_NAME": "PAYMENT_GUIDE_V2",
                            "IS_FALLBACK_SEARCH_RESULT": "N",
                            "BQ_LOAD_DTTM": (occurred_at + timedelta(hours=2)).isoformat(
                                timespec="seconds"
                            ),
                            "BQ_LOAD_USER_ID": "synthetic-seeder",
                        }
                    )
                if incomplete_index <= _PAYMENT_POST_NEGATIVE_FEEDBACK[day_index]:
                    feedback_at = base_time + timedelta(minutes=search_attempts * 5 + 2)
                    feedback.append(
                        {
                            "CZ_LNK_KEY": identity.cz_link_key,
                            "P_YYYYMMDD": day.isoformat(),
                            "ID": 410_000 + day_index * 100 + index,
                            "RUN_ID": (f"RUN-PAY-P-{day_index + 1}-{index:03d}-{search_attempts}"),
                            "FEEDBACK_TYPE": "negative",
                            "REASON": "안내대로 했지만 변경을 완료하지 못함",
                            "OPTION": "소액결제 개선 안내 불충분",
                            "BQ_LOAD_DTTM": (feedback_at + timedelta(hours=2)).isoformat(
                                timespec="seconds"
                            ),
                            "BQ_LOAD_USER_ID": "synthetic-seeder",
                        }
                    )
            billing.append(
                _billing_row(
                    identity,
                    snapshot_day=day,
                    age=22 + index % 40,
                    service_amount=3_300 if index % 3 == 0 else 0,
                    micropayment_amount=10_000 + index % 6 * 5_000,
                )
            )
        for incomplete_index in range(1, _PAYMENT_POST_VOC[day_index] + 1):
            index = incomplete_indices[incomplete_index - 1]
            identity = _post_identity("payment", day_index, index)
            occurred_at = datetime.combine(day, time(20, incomplete_index))
            voc.append(
                {
                    "P_YYYYMMDD": day.isoformat(),
                    "CZ_LNK_KEY": identity.cz_link_key,
                    "BASE_DT": day.strftime("%Y%m%d"),
                    "CALL_ID": f"CALL-PAY-P-{day_index + 1}-{index:03d}",
                    "CALL_CRTE_DTTM": occurred_at.isoformat(timespec="seconds"),
                    "CUST_CNSL_TM": 260 + incomplete_index,
                    "STT_TXT_CNTN": "한도 변경 과정에서 동의 단계를 완료하지 못했어요.",
                    "INQU_CNTN": "소액결제 한도 변경 실패 문의",
                    "CSLR_PRSS_CNTN": "상담원이 동의 단계와 본인인증 안내",
                    "CNSL_ALL_SMRY_CNTN": "동의 단계 이후 변경이 완료되지 않아 문의함",
                    "CUST_SNMT_NM": "불편",
                    "CNSL_SBJC_TIT_NM": "소액결제 한도 변경",
                    "CNSL_SCLS_CD": "PAY-LIMIT-01",
                    "CNSL_THMA_NM": "소액결제 한도",
                    "ENTR_NO": identity.entry_no,
                    "CUST_NO": identity.customer_no,
                    "BQ_LOAD_DTTM": (occurred_at + timedelta(hours=2)).isoformat(
                        timespec="seconds"
                    ),
                    "BQ_LOAD_USER_ID": "synthetic-seeder",
                }
            )


def generate_seed_bundle(config: SeedConfig | None = None) -> SeedBundle:
    """Generate deterministic rows for the configured demo window."""

    resolved = config or SeedConfig()
    rng = random.Random(resolved.seed)
    tables = _empty_tables()
    _add_vas_baseline(tables["L1DA_GA_REP_CHNL_BEHV_L"], resolved, rng)
    _add_vas_search_context(tables, resolved)
    _add_vas_voc_context(tables, resolved)
    _add_vas_profiles(tables, resolved)
    _add_vas_crm_campaign(tables, resolved)
    _add_payment_baseline(tables["L1DA_GA_REP_CHNL_BEHV_L"], resolved, rng)
    _add_payment_success_controls(tables["L1DA_GA_REP_CHNL_BEHV_L"], resolved, rng)
    _add_payment_search_context(tables, resolved)
    _add_payment_voc_context(tables, resolved)
    _add_payment_billing_profiles(tables, resolved)
    _add_vas_post_ga(tables, resolved, rng)
    _add_vas_post_context(tables, resolved)
    _add_payment_post(tables, resolved, rng)
    from customer_signal.seeding.roaming import add_roaming_scenario

    add_roaming_scenario(tables, resolved, rng)
    return SeedBundle(config=resolved, tables=tables)


__all__ = ["generate_seed_bundle"]

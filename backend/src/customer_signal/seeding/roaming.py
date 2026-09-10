"""Roaming plan browsing followed by agent-assisted subscription."""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta

from customer_signal.seeding.generator import _billing_row, _ga_row, _identity
from customer_signal.seeding.models import SeedConfig, TableRows


def add_roaming_scenario(tables: TableRows, config: SeedConfig, rng: random.Random) -> None:
    """Add plan-comparison exits, agent signups, and successful app controls.

    All plans start on departure day. Monthly rows confirm registered subscriptions
    as of that evening; usage is not a failure label.
    """
    for offset in range(14):
        day = config.start_date + timedelta(days=offset)
        post_index = offset - 7
        exposure = config.exposure_rates[post_index] if post_index >= 0 else 0
        exposed = round(20 * exposure)
        handoff_count = 7 - post_index if post_index >= 0 else 8
        controls = list(range(exposed + 1, 21))
        control_handoffs = min(round(len(controls) * 0.4), handoff_count)
        handoff = set(controls[:control_handoffs]) | set(
            range(1, handoff_count - control_handoffs + 1)
        )
        remaining = [i for i in range(1, 21) if i not in handoff]
        direct_consultation = set(remaining[:2])
        compared_app_signup = set(remaining[2:4])
        # Identity order must not encode a customer's failure or treatment group.
        serials = list(range(1, 21))
        rng.shuffle(serials)
        for index, serial in enumerate(serials, start=1):
            identity = _identity(
                "roaming", "baseline" if offset < 7 else "post", (offset % 7) * 100 + serial
            )
            started_at = datetime.combine(day, time(10, serial))
            agent_signup = index in handoff | direct_consultation
            compares_plans = index in handoff | compared_app_signup
            has_usage = serial % 5 != 0
            search_at = started_at - timedelta(hours=1)
            key = identity.cz_link_key
            tables["L0UR_SEARCH_HISTORY"].append(
                {
                    "CZ_LNK_KEY": key,
                    "P_YYYYMMDD": day.isoformat(),
                    "ID": key * 10,
                    "THREAD_ID": f"THREAD-{key}",
                    "RUN_ID": f"RUN-{key}",
                    "SEARCH_QUERY": "로밍 요금제 추천",
                    "SEARCH_RESULT": "로밍 요금제의 데이터 제공량과 가격을 비교할 수 있습니다.",
                    "CREATED_AT": search_at.isoformat(timespec="seconds"),
                    "STATUS": "completed",
                    "FIRST_RESPONSE_LATENCY_MS": 650.0,
                    "WAS_CACHE_HIT": False,
                    "SEARCH_QUERY_TYPE": "initial",
                    "REWRITE_SEARCH_QUERY": "해외 로밍 이용",
                    "SEARCH_RESULT_REFERENCE_TEMPLATE_NAME": "ROAMING_GUIDE",
                    "IS_FALLBACK_SEARCH_RESULT": "N",
                    "BQ_LOAD_DTTM": (search_at + timedelta(hours=2)).isoformat(timespec="seconds"),
                    "BQ_LOAD_USER_ID": "synthetic-seeder",
                }
            )
            journey = [("roaming_plan_list_opened", "로밍 요금제 목록")]
            products = ("로밍패스 4GB", "로밍패스 8GB", "로밍패스 12GB")
            for product in products if compares_plans else products[:1]:
                journey.append(("roaming_plan_detail_viewed", product))
            final_action = (
                "roaming_plan_selection_exited"
                if index in handoff
                else "roaming_consultation_requested"
                if agent_signup
                else "roaming_signup_completed"
            )
            journey.append((final_action, "로밍 요금제 목록"))
            for step, (action, menu) in enumerate(journey):
                tables["L1DA_GA_REP_CHNL_BEHV_L"].append(
                    _ga_row(
                        identity=identity,
                        occurred_at=started_at + timedelta(seconds=step * 20),
                        session_id=f"SESN-{key}",
                        session_stay=len(journey) * 20,
                        event_name="interaction",
                        action=action,
                        category="roaming_plan_selection",
                        label="plan_browsing" if step < len(journey) - 1 else "session_ended",
                        page_stay=20,
                        menu=menu,
                        abtest_id="ROAMING_PLAN_GUIDE_V1" if index <= exposed else "CONTROL",
                        ga_link_key=key * 1000 + step,
                    )
                )
            if agent_signup:
                call_at = datetime.combine(day, time(14, serial))
                tables["L1RA_VOC_STT_DTL_H"].append(
                    {
                        "P_YYYYMMDD": day.isoformat(),
                        "CZ_LNK_KEY": key,
                        "BASE_DT": day.strftime("%Y%m%d"),
                        "CALL_ID": f"CALL-{key}",
                        "CALL_CRTE_DTTM": call_at.isoformat(timespec="seconds"),
                        "CUST_CNSL_TM": 300,
                        "STT_TXT_CNTN": "여행에 맞는 로밍 요금제를 안내받고 가입하고 싶어요.",
                        "INQU_CNTN": "로밍 요금제 안내 및 가입 요청",
                        "CSLR_PRSS_CNTN": "상담원 로밍 가입 처리 완료",
                        "CNSL_ALL_SMRY_CNTN": "로밍 요금제 안내 후 가입 처리 완료",
                        "CUST_SNMT_NM": "상담완료",
                        "CNSL_SBJC_TIT_NM": "로밍 요금제 가입",
                        "CNSL_SCLS_CD": "ROAM-PLAN-01",
                        "CNSL_THMA_NM": "해외 로밍 이용",
                        "ENTR_NO": identity.entry_no,
                        "CUST_NO": identity.customer_no,
                        "BQ_LOAD_DTTM": (call_at + timedelta(hours=2)).isoformat(
                            timespec="seconds"
                        ),
                        "BQ_LOAD_USER_ID": "synthetic-seeder",
                    }
                )
            age = 25 + serial % 36
            sex = "MALE" if key % 2 else "FEMALE"
            tables["L1DA_RMNG_USE_MMLY_INTG_H"].append(
                {
                    "CSZ_LNK_KEY": key,
                    "P_YYYYMM": int(day.strftime("%Y%m")),
                    "ENTR_NO": identity.entry_no,
                    "CUST_NO": identity.customer_no,
                    "BILL_ACNT_NO": f"BILL-{key}",
                    "PROD_NO": "SYN-ROAM-4GB",
                    "AG10_AGJU_ID": age // 10,
                    "CUST_AGE": age,
                    "SEX_DIVS_CD": sex,
                    "SEX_DIVS_NM": "남자" if sex == "MALE" else "여자",
                    "PP_CD": "5G-STD-01",
                    "PP_NM": "5G 스탠다드",
                    "ENTR_STUS_CD": "A",
                    "ENTR_STUS_NM": "개통",
                    "RMNG_NATN_NM": ("일본", "베트남", "미국", "태국")[serial % 4],
                    "DPTR_DT": day.strftime("%Y%m%d"),
                    "HMCML_DT": "",
                    "ABRD_STAY_DAYS": 0,
                    "SPPS_CD": "SYN-ROAM-4GB",
                    "SPPS_NM": "합성 로밍패스 4GB",
                    "SPPS_ENTR_STUS_CD": "A",
                    "SPPS_ENTR_STUS_NM": "개통",
                    "SPPS_FRST_ENTR_DT": day.strftime("%Y%m%d"),
                    "SPPS_STRT_DT": day.strftime("%Y%m%d"),
                    "SPPS_END_DT": "99991231",
                    "RTNG_STRT_DT": day.strftime("%Y%m%d") if has_usage else "",
                    "RTNG_END_DT": "",
                    "PP_USE_DAYS": int(has_usage),
                    "MERT_USE_DAYS": 0,
                    "DATA_USAG": 120_000_000 + serial * 1_000_000 if has_usage else 0,
                    "RMNG_LTTR_CNT": 1 if has_usage else 0,
                    "BQ_LOAD_DTTM": f"{day.isoformat()}T21:00:00",
                    "BQ_LOAD_USER_ID": "synthetic-seeder",
                }
            )
            tables["L1BAT_CUST_BLNG_AND_BNFT_SUM"].append(
                _billing_row(
                    identity,
                    snapshot_day=day,
                    age=age,
                    service_amount=0,
                    micropayment_amount=0,
                )
            )

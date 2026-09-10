"""Validation and KPI derivation for the hackathon seed bundle."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean

from customer_signal.seeding.models import SeedBundle, TABLE_COLUMNS, TableRow


class SeedValidationError(ValueError):
    """The generated seed data violates its public demo contract."""


@dataclass(frozen=True, slots=True)
class ValidationReport:
    valid: bool
    checks: dict[str, str]
    daily_kpis: list[dict[str, object]]


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _scenario_searches(searches: list[TableRow], *, day: str, topic: str) -> list[TableRow]:
    return [
        row for row in searches if row["P_YYYYMMDD"] == day and row["REWRITE_SEARCH_QUERY"] == topic
    ]


def _daily_kpis(bundle: SeedBundle) -> list[dict[str, object]]:
    ga_rows = bundle.tables["L1DA_GA_REP_CHNL_BEHV_L"]
    searches = bundle.tables["L0UR_SEARCH_HISTORY"]
    feedback = bundle.tables["L0UR_FEEDBACK"]
    voc = bundle.tables["L1RA_VOC_STT_DTL_H"]
    crm = bundle.tables["L1CM_CRM_MSG_SEND_H"]
    search_by_run = {str(row["RUN_ID"]): row for row in searches}
    roaming_pattern = _roaming_pattern_customers(bundle)
    days = [
        bundle.config.start_date + timedelta(days=offset)
        for offset in range((bundle.config.end_date - bundle.config.start_date).days + 1)
    ]
    result: list[dict[str, object]] = []
    for current in days:
        day = current.isoformat()
        day_ga = [row for row in ga_rows if row["P_YYYYMMDD"] == day]
        vas_ga = [row for row in day_ga if str(row["EVET_ACT_CATG_NM"]).startswith("vas_")]
        payment_ga = [row for row in day_ga if row["EVET_ACT_CATG_NM"] == "payment_limit_change"]
        vas_sessions = {str(row["SESN_ID"]) for row in vas_ga}
        vas_direct = {
            str(row["SESN_ID"]) for row in vas_ga if row["EVET_ACT_NM"] == "cta_direct_open"
        }
        vas_unreachable = {
            str(row["SESN_ID"]) for row in vas_ga if row["EVET_ACT_LABE_NM"] == "vas_unreachable"
        }
        vas_favorite = {
            str(row["SESN_ID"]) for row in vas_ga if row["EVET_ACT_NM"] == "favorite_set"
        }
        vas_searches = _scenario_searches(searches, day=day, topic="부가서비스 조회/해지")
        vas_repeat = {
            row["CZ_LNK_KEY"] for row in vas_searches if row["SEARCH_QUERY_TYPE"] == "repeat"
        }
        vas_feedback = {
            row["CZ_LNK_KEY"]
            for row in feedback
            if row["P_YYYYMMDD"] == day
            and row["FEEDBACK_TYPE"] == "negative"
            and str(search_by_run[str(row["RUN_ID"])]["REWRITE_SEARCH_QUERY"])
            == "부가서비스 조회/해지"
        }
        vas_voc = {
            row["CZ_LNK_KEY"]
            for row in voc
            if row["P_YYYYMMDD"] == day and row["CNSL_THMA_NM"] == "부가서비스 조회/해지"
        }
        vas_crm_delivered = {
            row["CZ_LNK_KEY"]
            for row in crm
            if row["P_YYYYMMDD"] == day and row["SEND_RESULT_CD"] == "DELIVERED"
        }
        vas_crm_change_search = {
            row["CZ_LNK_KEY"]
            for row in vas_searches
            if "구글원" in str(row["SEARCH_QUERY"])
            and ("변경" in str(row["SEARCH_QUERY"]) or "바꾸" in str(row["SEARCH_QUERY"]))
        }
        vas_crm_recipients_to_date = {
            row["CZ_LNK_KEY"]
            for row in crm
            if row["P_YYYYMMDD"] <= day and row["SEND_RESULT_CD"] == "DELIVERED"
        }
        vas_crm_change_searchers_to_date = {
            row["CZ_LNK_KEY"]
            for row in searches
            if row["P_YYYYMMDD"] <= day
            and "구글원" in str(row["SEARCH_QUERY"])
            and ("변경" in str(row["SEARCH_QUERY"]) or "바꾸" in str(row["SEARCH_QUERY"]))
        }

        payment_customers = {row["CZ_LNK_KEY"] for row in payment_ga}
        payment_completed = {
            row["CZ_LNK_KEY"]
            for row in payment_ga
            if row["EVET_ACT_NM"] == "limit_change_completed"
        }
        payment_incomplete = {
            row["CZ_LNK_KEY"]
            for row in payment_ga
            if row["EVET_ACT_LABE_NM"] == "payment_incomplete"
        }
        incomplete_sessions = {
            str(row["SESN_ID"])
            for row in payment_ga
            if row["EVET_ACT_LABE_NM"] == "payment_incomplete"
        }
        consent_exit_customers = {
            row["CZ_LNK_KEY"] for row in payment_ga if row["EVET_ACT_NM"] == "consent_sheet_closed"
        }
        payment_searches = _scenario_searches(searches, day=day, topic="소액결제 한도 변경")
        payment_repeat = {
            row["CZ_LNK_KEY"] for row in payment_searches if row["SEARCH_QUERY_TYPE"] == "repeat"
        }
        payment_feedback = {
            row["CZ_LNK_KEY"]
            for row in feedback
            if row["P_YYYYMMDD"] == day
            and row["FEEDBACK_TYPE"] == "negative"
            and str(search_by_run[str(row["RUN_ID"])]["REWRITE_SEARCH_QUERY"])
            == "소액결제 한도 변경"
        }
        payment_voc = {
            row["CZ_LNK_KEY"]
            for row in voc
            if row["P_YYYYMMDD"] == day and row["CNSL_THMA_NM"] == "소액결제 한도"
        }
        all_customers = {row["CZ_LNK_KEY"] for row in day_ga}
        exposed_customers = {row["CZ_LNK_KEY"] for row in day_ga if row["ABTEST_ID"] != "CONTROL"}
        roaming = [
            row
            for row in bundle.tables["L1DA_RMNG_USE_MMLY_INTG_H"]
            if str(row["BQ_LOAD_DTTM"])[:10] == day
        ]
        roaming_matches = sum(str(row["CUST_NO"]) in roaming_pattern for row in roaming)
        result.append(
            {
                "date": day,
                "phase": "baseline" if current < bundle.config.intervention_at.date() else "post",
                "exposure_rate": _rate(len(exposed_customers), len(all_customers)),
                "vas_session_count": len(vas_sessions),
                "vas_direct_reach_rate": _rate(len(vas_direct), len(vas_sessions)),
                "vas_unreachable_rate": _rate(len(vas_unreachable), len(vas_sessions)),
                "vas_repeat_search_rate": _rate(len(vas_repeat), len(vas_sessions)),
                "vas_negative_feedback_rate": _rate(len(vas_feedback), len(vas_sessions)),
                "vas_favorite_rate": _rate(len(vas_favorite), len(vas_sessions)),
                "vas_voc_rate": _rate(len(vas_voc), len(vas_sessions)),
                "vas_crm_delivered_count": len(vas_crm_delivered),
                "vas_google_one_change_search_customer_count": len(vas_crm_change_search),
                "vas_crm_recipient_change_search_rate_cumulative": _rate(
                    len(vas_crm_change_searchers_to_date & vas_crm_recipients_to_date),
                    len(vas_crm_recipients_to_date),
                ),
                "payment_customer_count": len(payment_customers),
                "payment_completion_rate": _rate(len(payment_completed), len(payment_customers)),
                "payment_consent_exit_rate": _rate(
                    len(consent_exit_customers), len(payment_incomplete)
                ),
                "payment_average_attempts": (
                    round(len(incomplete_sessions) / len(payment_incomplete), 4)
                    if payment_incomplete
                    else 0.0
                ),
                "payment_repeat_search_rate": _rate(len(payment_repeat), len(payment_customers)),
                "payment_negative_feedback_rate": _rate(
                    len(payment_feedback), len(payment_customers)
                ),
                "payment_voc_rate": _rate(len(payment_voc), len(payment_customers)),
                "roaming_customer_count": len(roaming),
                "roaming_browse_exit_agent_signup_count": roaming_matches,
                "roaming_browse_exit_agent_signup_rate": _rate(roaming_matches, len(roaming)),
                "roaming_usage_rate": _rate(
                    sum(row["DATA_USAG"] > 0 for row in roaming), len(roaming)
                ),
            }
        )
    return result


def _validate_schema(bundle: SeedBundle) -> None:
    if set(bundle.tables) != set(TABLE_COLUMNS):
        raise SeedValidationError("bundle must contain exactly the eight locked tables")
    for table_name, rows in bundle.tables.items():
        expected = set(TABLE_COLUMNS[table_name])
        for row in rows:
            if set(row) != expected:
                raise SeedValidationError(f"{table_name} row does not match selected schema")


def _validate_identifiers(bundle: SeedBundle) -> None:
    unique_fields = {
        "L0UR_FEEDBACK": "ID",
        "L0UR_SEARCH_HISTORY": "ID",
        "L1DA_GA_REP_CHNL_BEHV_L": "GA_LNK_KEY",
        "L1CM_CRM_MSG_SEND_H": "MESSAGE_ID",
        "L1RA_VOC_STT_DTL_H": "CALL_ID",
        "L1DA_RMNG_USE_MMLY_INTG_H": "CSZ_LNK_KEY",
    }
    for table_name, field in unique_fields.items():
        values = [row[field] for row in bundle.tables[table_name]]
        if len(values) != len(set(values)):
            raise SeedValidationError(f"{table_name}.{field} must be unique")


def _validate_dates(bundle: SeedBundle) -> None:
    start, end = bundle.config.start_date, bundle.config.end_date
    if (
        (bundle.config.intervention_at.date() - start).days != 7
        or (end - start).days != 13
        or len(bundle.config.exposure_rates) != 7
    ):
        raise SeedValidationError("seed window must have seven baseline and seven post days")
    for table, rows in bundle.tables.items():
        for row in rows:
            timestamp = str(row.get("BQ_LOAD_DTTM", row.get("DP_LOAD_DTTM")))
            try:
                loaded_at = datetime.fromisoformat(timestamp)
            except ValueError as error:
                raise SeedValidationError(f"{table} has invalid load timestamp") from error
            if not start <= loaded_at.date() <= end:
                raise SeedValidationError(f"{table} load date is outside the seed window")
            for column in ("P_YYYYMMDD", "CREATED_AT", "CALL_CRTE_DTTM", "SEND_DTTM"):
                if (
                    column in row
                    and not start.isoformat() <= str(row[column])[:10] <= end.isoformat()
                ):
                    raise SeedValidationError(f"{table}.{column} is outside the seed window")
            for column in ("BASE_YYMM", "P_YYYYMM"):
                if column in row and str(row[column]) != loaded_at.strftime("%Y%m"):
                    raise SeedValidationError(f"{table}.{column} does not match snapshot month")
            if "LOG_DTTM" in row:
                occurred = datetime.strptime(str(row["LOG_DTTM"]), "%Y%m%d%H%M%S")
                if not start <= occurred.date() <= end or occurred > loaded_at:
                    raise SeedValidationError("app occurrence is outside window or after loading")


def _validate_foreign_keys(bundle: SeedBundle) -> None:
    searches = {str(row["RUN_ID"]): row for row in bundle.tables["L0UR_SEARCH_HISTORY"]}
    for row in bundle.tables["L0UR_FEEDBACK"]:
        search = searches.get(str(row["RUN_ID"]))
        if search is None or search["CZ_LNK_KEY"] != row["CZ_LNK_KEY"]:
            raise SeedValidationError("feedback must reference a same-customer search")

    app_customers = {row["CZ_LNK_KEY"] for row in bundle.tables["L1DA_GA_REP_CHNL_BEHV_L"]}
    if any(row["CZ_LNK_KEY"] not in app_customers for row in bundle.tables["L1RA_VOC_STT_DTL_H"]):
        raise SeedValidationError("VOC must reference an app customer")
    crm = bundle.tables["L1CM_CRM_MSG_SEND_H"]
    if any(row["CZ_LNK_KEY"] not in app_customers for row in crm):
        raise SeedValidationError("CRM messages must reference an app customer")
    subscription_keys = {
        (str(row["CUST_NO"]), str(row["ENTR_NO"]), str(row["PROD_CD"]))
        for row in bundle.tables["L2ZI_MBL_VAS_ENTR_INFO_DALY_H"]
        if row["SVC_STTS_CD"] == "A" and row["SRVL_YN"] == "Y"
    }
    if any(
        (str(row["CUST_NO"]), str(row["ENTR_NO"]), str(row["TARGET_PROD_CD"]))
        not in subscription_keys
        for row in crm
    ):
        raise SeedValidationError("CRM recipients must have the targeted active subscription")
    app_keys = {
        (str(row["CUST_NO"]), str(row["ENTR_NO"]))
        for row in bundle.tables["L1DA_GA_REP_CHNL_BEHV_L"]
    }
    billing_keys = {
        (str(row["CUST_NO"]), str(row["ENTR_NO"]), str(row["BILL_ACNT_NO"]))
        for row in bundle.tables["L1BAT_CUST_BLNG_AND_BNFT_SUM"]
    }
    for row in bundle.tables["L1DA_RMNG_USE_MMLY_INTG_H"]:
        customer, entry = str(row["CUST_NO"]), str(row["ENTR_NO"])
        if (customer, entry) not in app_keys or (
            customer,
            entry,
            str(row["BILL_ACNT_NO"]),
        ) not in billing_keys:
            raise SeedValidationError("roaming must link to the same app and billing subscription")


def _validate_temporal_order(bundle: SeedBundle) -> None:
    ga_by_session: dict[str, list[TableRow]] = defaultdict(list)
    latest_app_by_customer: dict[object, datetime] = {}
    for row in bundle.tables["L1DA_GA_REP_CHNL_BEHV_L"]:
        ga_by_session[str(row["SESN_ID"])].append(row)
        occurred_at = datetime.strptime(str(row["LOG_DTTM"]), "%Y%m%d%H%M%S")
        customer = row["CZ_LNK_KEY"]
        latest_app_by_customer[customer] = max(
            latest_app_by_customer.get(customer, occurred_at), occurred_at
        )

    expected_completed = (
        "limit_page_entered",
        "limit_slider_changed",
        "consent_sheet_shown",
        "consent_checked",
        "identity_verified",
        "limit_change_completed",
    )
    for session_id, rows in ga_by_session.items():
        ordered = sorted(rows, key=lambda row: str(row["LOG_DTTM"]))
        actions = tuple(str(row["EVET_ACT_NM"]) for row in ordered)
        if "favorite_set" in actions:
            favorite_index = actions.index("favorite_set")
            if not any(
                row["REP_CHNL_MENU_NM"] == "부가서비스 조회/해지"
                for row in ordered[:favorite_index]
            ):
                raise SeedValidationError(
                    f"favorite must follow a VAS reach in session {session_id}"
                )
        if "limit_change_completed" in actions and actions != expected_completed:
            raise SeedValidationError(
                f"payment completion steps are out of order in session {session_id}"
            )

    for row in bundle.tables["L1RA_VOC_STT_DTL_H"]:
        call_at = datetime.fromisoformat(str(row["CALL_CRTE_DTTM"]))
        latest_app = latest_app_by_customer[row["CZ_LNK_KEY"]]
        if call_at <= latest_app:
            raise SeedValidationError("VOC must occur after the customer's last app event")

    crm_sent_at = {
        str(row["CZ_LNK_KEY"]): datetime.fromisoformat(str(row["SEND_DTTM"]))
        for row in bundle.tables["L1CM_CRM_MSG_SEND_H"]
    }
    for row in bundle.tables["L0UR_SEARCH_HISTORY"]:
        customer = str(row["CZ_LNK_KEY"])
        if customer in crm_sent_at and "구글원" in str(row["SEARCH_QUERY"]):
            if datetime.fromisoformat(str(row["CREATED_AT"])) <= crm_sent_at[customer]:
                raise SeedValidationError("Google One change searches must follow the CRM message")


def _validate_vas_crm_campaign(bundle: SeedBundle) -> None:
    boundary = bundle.config.intervention_at.date().isoformat()
    messages = bundle.tables["L1CM_CRM_MSG_SEND_H"]
    recipients = {str(row["CZ_LNK_KEY"]) for row in messages}
    if (
        len(messages) != 240
        or len(recipients) != 240
        or {row["CAMPAIGN_ID"] for row in messages} != {"CMP-G1-OPTION-202609"}
        or {row["SEND_RESULT_CD"] for row in messages} != {"DELIVERED"}
        or {row["TARGET_PROD_CD"] for row in messages} != {"VAS-GOOGLEONE-100"}
    ):
        raise SeedValidationError("Google One CRM campaign must have 240 delivered recipients")

    app_customers = {
        str(row["CZ_LNK_KEY"])
        for row in bundle.tables["L1DA_GA_REP_CHNL_BEHV_L"]
        if row["P_YYYYMMDD"] < boundary and row["EVET_ACT_CATG_NM"] == "vas_wandering"
    }
    searches = [
        row
        for row in bundle.tables["L0UR_SEARCH_HISTORY"]
        if row["P_YYYYMMDD"] < boundary and row["REWRITE_SEARCH_QUERY"] == "부가서비스 조회/해지"
    ]
    searchers = {str(row["CZ_LNK_KEY"]) for row in searches}
    change_searchers = {
        str(row["CZ_LNK_KEY"])
        for row in searches
        if "구글원" in str(row["SEARCH_QUERY"])
        and ("변경" in str(row["SEARCH_QUERY"]) or "바꾸" in str(row["SEARCH_QUERY"]))
    }
    recipient_searchers = recipients & searchers
    nonrecipient_searchers = (app_customers - recipients) & searchers
    if (
        len(app_customers) != 340
        or len(recipient_searchers) != 160
        or len(nonrecipient_searchers) != 20
        or change_searchers != recipient_searchers
    ):
        raise SeedValidationError(
            "CRM campaign must explain 160 Google One change searchers with a 20-customer control"
        )
    recipient_rate = len(recipient_searchers) / len(recipients)
    control_rate = len(nonrecipient_searchers) / len(app_customers - recipients)
    if recipient_rate / control_rate < 3:
        raise SeedValidationError("CRM recipient search rate must be at least three times control")


def _validate_baseline_cohorts(bundle: SeedBundle) -> None:
    rows = [
        row
        for row in bundle.tables["L1DA_GA_REP_CHNL_BEHV_L"]
        if row["P_YYYYMMDD"] < bundle.config.intervention_at.date().isoformat()
    ]
    wandering = {row["CZ_LNK_KEY"] for row in rows if row["EVET_ACT_CATG_NM"] == "vas_wandering"}
    favorites = {row["CZ_LNK_KEY"] for row in rows if row["EVET_ACT_NM"] == "favorite_set"}
    unreachable = {
        row["CZ_LNK_KEY"] for row in rows if row["EVET_ACT_LABE_NM"] == "vas_unreachable"
    }
    payment_incomplete = {
        row["CZ_LNK_KEY"] for row in rows if row["EVET_ACT_LABE_NM"] == "payment_incomplete"
    }
    payment_sessions = {
        str(row["SESN_ID"]) for row in rows if row["EVET_ACT_LABE_NM"] == "payment_incomplete"
    }
    vas_voc = {
        row["CZ_LNK_KEY"]
        for row in bundle.tables["L1RA_VOC_STT_DTL_H"]
        if row["P_YYYYMMDD"] < bundle.config.intervention_at.date().isoformat()
        and row["CNSL_THMA_NM"] == "부가서비스 조회/해지"
    }
    payment_voc = {
        row["CZ_LNK_KEY"]
        for row in bundle.tables["L1RA_VOC_STT_DTL_H"]
        if row["P_YYYYMMDD"] < bundle.config.intervention_at.date().isoformat()
        and row["CNSL_THMA_NM"] == "소액결제 한도"
    }
    expected = (340, 84, 97, 61, 210, 567, 74)
    actual = (
        len(wandering),
        len(favorites),
        len(unreachable),
        len(vas_voc),
        len(payment_incomplete),
        len(payment_sessions),
        len(payment_voc),
    )
    if actual != expected:
        raise SeedValidationError(f"baseline cohort mismatch: expected={expected}, actual={actual}")


def _moving_averages(values: list[float]) -> list[float]:
    return [fmean(values[index - 2 : index + 1]) for index in range(2, len(values))]


def _validate_three_day_trend(daily_kpis: list[dict[str, object]]) -> None:
    post = [row for row in daily_kpis if row["phase"] == "post"]
    increasing = ("vas_direct_reach_rate", "payment_completion_rate")
    decreasing = (
        "vas_unreachable_rate",
        "payment_consent_exit_rate",
        "payment_average_attempts",
    )
    for metric in increasing:
        averages = _moving_averages([float(row[metric]) for row in post])
        if any(left >= right for left, right in zip(averages, averages[1:])):
            raise SeedValidationError(f"{metric} three-day trend must increase")
    for metric in decreasing:
        averages = _moving_averages([float(row[metric]) for row in post])
        if any(left <= right for left, right in zip(averages, averages[1:])):
            raise SeedValidationError(f"{metric} three-day trend must decrease")


def _validate_goal_ranges(daily_kpis: list[dict[str, object]]) -> None:
    for row in daily_kpis:
        if any(
            not 0.0 <= float(value) <= 1.0
            for metric, value in row.items()
            if metric.endswith("_rate")
        ):
            raise SeedValidationError("daily rate KPI must stay between zero and one")
    last = daily_kpis[-1]
    conditions = (
        float(last["vas_direct_reach_rate"]) >= 0.65,
        float(last["vas_unreachable_rate"]) <= 0.15,
        float(last["vas_repeat_search_rate"]) <= 0.25,
        float(last["vas_negative_feedback_rate"]) <= 0.20,
        float(last["vas_favorite_rate"]) <= 0.15,
        float(last["vas_voc_rate"]) <= 0.10,
        float(last["payment_completion_rate"]) >= 0.65,
        float(last["payment_consent_exit_rate"]) <= 0.35,
        float(last["payment_average_attempts"]) <= 1.6,
        float(last["payment_repeat_search_rate"]) <= 0.22,
        float(last["payment_negative_feedback_rate"]) <= 0.20,
        float(last["payment_voc_rate"]) <= 0.18,
    )
    if not all(conditions):
        raise SeedValidationError("final-day KPI is outside the approved goal ranges")


def _validate_exposure(bundle: SeedBundle, daily_kpis: list[dict[str, object]]) -> None:
    post = [row for row in daily_kpis if row["phase"] == "post"]
    exposure = [float(row["exposure_rate"]) for row in post]
    if any(left >= right for left, right in zip(exposure, exposure[1:])):
        raise SeedValidationError("post-intervention exposure must increase every day")
    if exposure[-1] != 1.0:
        raise SeedValidationError("final-day exposure must be complete")
    ga_rows = bundle.tables["L1DA_GA_REP_CHNL_BEHV_L"]
    post_rows = [
        row
        for row in ga_rows
        if row["P_YYYYMMDD"] >= bundle.config.intervention_at.date().isoformat()
    ]
    if {row["ABTEST_ID"] for row in post_rows} != {
        "CONTROL",
        "VAS_AI_CTA_V1",
        "PAYMENT_CONSENT_V1",
        "ROAMING_PLAN_GUIDE_V1",
    }:
        raise SeedValidationError("post rows must contain both treatments and control")


def _validate_control_stability(bundle: SeedBundle) -> None:
    ga_rows = bundle.tables["L1DA_GA_REP_CHNL_BEHV_L"]
    vas_direct_rates: list[float] = []
    vas_unreachable_rates: list[float] = []
    payment_completion_rates: list[float] = []
    payment_consent_rates: list[float] = []
    for offset in range(6):
        day = (bundle.config.intervention_at.date() + timedelta(days=offset)).isoformat()
        controls = [
            row for row in ga_rows if row["P_YYYYMMDD"] == day and row["ABTEST_ID"] == "CONTROL"
        ]
        vas = [row for row in controls if str(row["EVET_ACT_CATG_NM"]).startswith("vas_")]
        vas_sessions = {row["SESN_ID"] for row in vas}
        vas_direct = {row["SESN_ID"] for row in vas if row["EVET_ACT_NM"] == "cta_direct_open"}
        vas_unreachable = {
            row["SESN_ID"] for row in vas if row["EVET_ACT_LABE_NM"] == "vas_unreachable"
        }
        vas_direct_rates.append(_rate(len(vas_direct), len(vas_sessions)))
        vas_unreachable_rates.append(_rate(len(vas_unreachable), len(vas_sessions)))

        payment = [row for row in controls if row["EVET_ACT_CATG_NM"] == "payment_limit_change"]
        payment_customers = {row["CZ_LNK_KEY"] for row in payment}
        completed = {
            row["CZ_LNK_KEY"] for row in payment if row["EVET_ACT_NM"] == "limit_change_completed"
        }
        incomplete = {
            row["CZ_LNK_KEY"] for row in payment if row["EVET_ACT_LABE_NM"] == "payment_incomplete"
        }
        consent = {
            row["CZ_LNK_KEY"] for row in payment if row["EVET_ACT_NM"] == "consent_sheet_closed"
        }
        payment_completion_rates.append(_rate(len(completed), len(payment_customers)))
        payment_consent_rates.append(_rate(len(consent), len(incomplete)))

    allowed_spreads = (
        (vas_direct_rates, 0.08),
        (vas_unreachable_rates, 0.12),
        (payment_completion_rates, 0.08),
        (payment_consent_rates, 0.22),
    )
    for values, maximum_spread in allowed_spreads:
        if max(values) - min(values) > maximum_spread:
            raise SeedValidationError("control KPI changed beyond the allowed noise band")

    final_day = bundle.config.end_date.isoformat()
    final_controls = {
        row["CZ_LNK_KEY"]
        for row in ga_rows
        if row["P_YYYYMMDD"] == final_day and row["ABTEST_ID"] == "CONTROL"
    }
    if final_controls:
        raise SeedValidationError("final-day rollout must not leave control customers")


def _roaming_pattern_customers(bundle: SeedBundle) -> set[str]:
    sessions: dict[str, list[TableRow]] = defaultdict(list)
    for row in bundle.tables["L1DA_GA_REP_CHNL_BEHV_L"]:
        if row["EVET_ACT_CATG_NM"] == "roaming_plan_selection":
            sessions[str(row["SESN_ID"])].append(row)
    exits: dict[tuple[str, str], datetime] = {}
    for rows in sessions.values():
        ordered = sorted(rows, key=lambda row: str(row["LOG_DTTM"]))
        details = {
            row["REP_CHNL_MENU_NM"]
            for row in ordered[:-1]
            if row["EVET_ACT_NM"] == "roaming_plan_detail_viewed"
        }
        if len(details) >= 3 and ordered[-1]["EVET_ACT_NM"] == "roaming_plan_selection_exited":
            last = ordered[-1]
            exits[(str(last["CUST_NO"]), str(last["ENTR_NO"]))] = datetime.strptime(
                str(last["LOG_DTTM"]), "%Y%m%d%H%M%S"
            )
    signups = {}
    for row in bundle.tables["L1RA_VOC_STT_DTL_H"]:
        key = (str(row["CUST_NO"]), str(row["ENTR_NO"]))
        call_at = datetime.fromisoformat(str(row["CALL_CRTE_DTTM"]))
        if (
            row["CSLR_PRSS_CNTN"] == "상담원 로밍 가입 처리 완료"
            and key in exits
            and exits[key] < call_at
        ):
            signups[key] = call_at
    return {
        str(row["CUST_NO"])
        for row in bundle.tables["L1DA_RMNG_USE_MMLY_INTG_H"]
        if (key := (str(row["CUST_NO"]), str(row["ENTR_NO"]))) in signups
        and row["SPPS_ENTR_STUS_CD"] == "A"
        and str(row["SPPS_FRST_ENTR_DT"]) == signups[key].strftime("%Y%m%d")
        and signups[key] < datetime.fromisoformat(str(row["BQ_LOAD_DTTM"]))
    }


def _validate_exploration_cases(bundle: SeedBundle, daily_kpis: list[dict[str, object]]) -> None:
    roaming = bundle.tables["L1DA_RMNG_USE_MMLY_INTG_H"]
    customers = {str(row["CUST_NO"]) for row in roaming}
    searches = [
        row for row in bundle.tables["L0UR_SEARCH_HISTORY"] if str(row["CZ_LNK_KEY"]) in customers
    ]
    if len(roaming) != 280 or len(customers) != 280 or len(searches) != 280:
        raise SeedValidationError("roaming requires 280 distinct travelers with one search each")
    if {(row["SEARCH_QUERY"], row["STATUS"], row["SEARCH_QUERY_TYPE"]) for row in searches} != {
        ("로밍 요금제 추천", "completed", "initial")
    } or {str(row["CZ_LNK_KEY"]) for row in searches} != customers:
        raise SeedValidationError("roaming searches must have the same normal response")
    for row in roaming:
        if float(row["DATA_USAG"]) < 0 or int(row["PP_USE_DAYS"]) < 0:
            raise SeedValidationError("roaming usage must be nonnegative")
        try:
            departure = datetime.strptime(str(row["DPTR_DT"]), "%Y%m%d")
            service_start = datetime.strptime(str(row["SPPS_STRT_DT"]), "%Y%m%d")
        except ValueError as error:
            raise SeedValidationError("roaming dates must use YYYYMMDD") from error
        if departure.date().isoformat() != str(row["BQ_LOAD_DTTM"])[:10]:
            raise SeedValidationError("roaming snapshot must be loaded on departure day")
        if service_start != departure:
            raise SeedValidationError("roaming service must start on departure day")
    calls = [row for row in bundle.tables["L1RA_VOC_STT_DTL_H"] if str(row["CUST_NO"]) in customers]
    if (
        len(calls) != 112
        or {row["CNSL_ALL_SMRY_CNTN"] for row in calls} != {"로밍 요금제 안내 후 가입 처리 완료"}
        or {row["CSLR_PRSS_CNTN"] for row in calls} != {"상담원 로밍 가입 처리 완료"}
    ):
        raise SeedValidationError(
            "roaming VOC must include handoffs and direct-consultation controls"
        )
    expected = [8] * 7 + [7, 6, 5, 4, 3, 2, 1]
    if [row["roaming_browse_exit_agent_signup_count"] for row in daily_kpis] != expected or any(
        row["roaming_customer_count"] != 20 for row in daily_kpis
    ):
        raise SeedValidationError("roaming joined pattern cohort does not match the demo contract")
    # Existing VAS example also contains customers invisible to search and VOC.
    boundary = bundle.config.intervention_at.date().isoformat()
    visible = {
        str(row["CZ_LNK_KEY"])
        for table in ("L0UR_SEARCH_HISTORY", "L1RA_VOC_STT_DTL_H")
        for row in bundle.tables[table]
        if row["P_YYYYMMDD"] < boundary
    }
    quiet = {
        str(row["CUST_NO"])
        for row in bundle.tables["L1DA_GA_REP_CHNL_BEHV_L"]
        if row["P_YYYYMMDD"] < boundary and row["EVET_ACT_CATG_NM"] == "vas_wandering"
    }
    if len(quiet - visible) != 160:
        raise SeedValidationError("VAS must retain 160 customers invisible to search and VOC")


def validate_bundle(bundle: SeedBundle) -> ValidationReport:
    """Validate the full seed contract and derive daily KPIs from raw rows."""

    checks: dict[str, str] = {}
    _validate_schema(bundle)
    checks["schema"] = "passed"
    _validate_dates(bundle)
    checks["date_window"] = "passed"
    _validate_identifiers(bundle)
    checks["identifiers"] = "passed"
    _validate_foreign_keys(bundle)
    checks["foreign_keys"] = "passed"
    _validate_temporal_order(bundle)
    checks["temporal_order"] = "passed"
    _validate_vas_crm_campaign(bundle)
    checks["crm_campaign"] = "passed"
    _validate_baseline_cohorts(bundle)
    checks["baseline_cohorts"] = "passed"
    daily_kpis = _daily_kpis(bundle)
    _validate_exploration_cases(bundle, daily_kpis)
    checks["exploration_cases"] = "passed"
    _validate_exposure(bundle, daily_kpis)
    checks["exposure"] = "passed"
    _validate_control_stability(bundle)
    checks["control_stability"] = "passed"
    _validate_three_day_trend(daily_kpis)
    checks["three_day_trend"] = "passed"
    _validate_goal_ranges(daily_kpis)
    checks["goal_ranges"] = "passed"
    return ValidationReport(valid=True, checks=checks, daily_kpis=daily_kpis)


__all__ = [
    "SeedValidationError",
    "ValidationReport",
    "validate_bundle",
]

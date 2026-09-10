"""Contracts shared by the hackathon seed generator and exporter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TypeAlias


TableRow: TypeAlias = dict[str, object]
TableRows: TypeAlias = dict[str, list[TableRow]]

TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "L0UR_FEEDBACK": (
        "CZ_LNK_KEY",
        "P_YYYYMMDD",
        "ID",
        "RUN_ID",
        "FEEDBACK_TYPE",
        "REASON",
        "OPTION",
        "BQ_LOAD_DTTM",
        "BQ_LOAD_USER_ID",
    ),
    "L0UR_SEARCH_HISTORY": (
        "CZ_LNK_KEY",
        "P_YYYYMMDD",
        "ID",
        "THREAD_ID",
        "RUN_ID",
        "SEARCH_QUERY",
        "SEARCH_RESULT",
        "CREATED_AT",
        "STATUS",
        "FIRST_RESPONSE_LATENCY_MS",
        "WAS_CACHE_HIT",
        "SEARCH_QUERY_TYPE",
        "REWRITE_SEARCH_QUERY",
        "SEARCH_RESULT_REFERENCE_TEMPLATE_NAME",
        "IS_FALLBACK_SEARCH_RESULT",
        "BQ_LOAD_DTTM",
        "BQ_LOAD_USER_ID",
    ),
    "L1BAT_CUST_BLNG_AND_BNFT_SUM": (
        "CZ_LNK_KEY",
        "BASE_YYMM",
        "BILL_ACNT_NO",
        "ENTR_NO",
        "CUST_NO",
        "YY10_AGELV_ID",
        "CUST_AGE",
        "PP_CD",
        "PP_NM",
        "ENTR_STTS_CD",
        "FRST_ENTR_DT",
        "SPPS_AMT",
        "SMLS_STLM_AMT",
        "TOT_BILL_AMT",
        "DP_LOAD_DTTM",
        "DP_LOAD_USER_ID",
        "SEX_DV_CD",
    ),
    "L1DA_GA_REP_CHNL_BEHV_L": (
        "CZ_LNK_KEY",
        "P_YYYYMMDD",
        "GA_LNK_KEY",
        "BASE_DT",
        "CLT_ID",
        "SESN_ID",
        "PTPN_SESN_TM",
        "CUST_NO",
        "ENTR_NO",
        "LOG_DTTM",
        "SESN_STAY_TM",
        "EVET_NM",
        "EVET_ACT_NM",
        "EVET_ACT_CATG_NM",
        "EVET_ACT_LABE_NM",
        "PAGE_STAY_TM",
        "REP_CHNL_MENU_NM",
        "REP_CHNL_MENU_LVL1_NM",
        "REP_CHNL_MENU_LVL2_NM",
        "REP_CHNL_MENU_LVL3_NM",
        "ABTEST_ID",
        "BQ_LOAD_DTTM",
        "BQ_LOAD_USER_ID",
    ),
    "L1RA_VOC_STT_DTL_H": (
        "P_YYYYMMDD",
        "CZ_LNK_KEY",
        "BASE_DT",
        "CALL_ID",
        "CALL_CRTE_DTTM",
        "CUST_CNSL_TM",
        "STT_TXT_CNTN",
        "INQU_CNTN",
        "CSLR_PRSS_CNTN",
        "CNSL_ALL_SMRY_CNTN",
        "CUST_SNMT_NM",
        "CNSL_SBJC_TIT_NM",
        "CNSL_SCLS_CD",
        "CNSL_THMA_NM",
        "ENTR_NO",
        "CUST_NO",
        "BQ_LOAD_DTTM",
        "BQ_LOAD_USER_ID",
    ),
    "L2ZI_MBL_VAS_ENTR_INFO_DALY_H": (
        "P_YYYYMMDD",
        "BASE_YYMM",
        "ENTR_NO",
        "ENTR_SVC_SEQNO",
        "CUST_NO",
        "PROD_CD",
        "PROD_NM",
        "BUY_PRC_YN",
        "VAT_INCL_ALL_AMT",
        "SVC_STTS_CD",
        "SVC_STRT_DT",
        "SVC_END_DT",
        "SRVL_YN",
        "EXPY_YN",
        "PROD_ENTR_DAYS",
        "PROD_ENTR_MMCT",
        "ATRC_CHNL_DIVS_NM",
        "EXPY_CHNL_DIVS_NM",
        "BQ_LOAD_DTTM",
        "BQ_LOAD_USER_ID",
    ),
    "L1DA_RMNG_USE_MMLY_INTG_H": (
        "CSZ_LNK_KEY",
        "P_YYYYMM",
        "ENTR_NO",
        "CUST_NO",
        "BILL_ACNT_NO",
        "PROD_NO",
        "AG10_AGJU_ID",
        "CUST_AGE",
        "SEX_DIVS_CD",
        "SEX_DIVS_NM",
        "PP_CD",
        "PP_NM",
        "ENTR_STUS_CD",
        "ENTR_STUS_NM",
        "RMNG_NATN_NM",
        "DPTR_DT",
        "HMCML_DT",
        "ABRD_STAY_DAYS",
        "SPPS_CD",
        "SPPS_NM",
        "SPPS_ENTR_STUS_CD",
        "SPPS_ENTR_STUS_NM",
        "SPPS_FRST_ENTR_DT",
        "SPPS_STRT_DT",
        "SPPS_END_DT",
        "RTNG_STRT_DT",
        "RTNG_END_DT",
        "PP_USE_DAYS",
        "MERT_USE_DAYS",
        "DATA_USAG",
        "RMNG_LTTR_CNT",
        "BQ_LOAD_DTTM",
        "BQ_LOAD_USER_ID",
    ),
}


@dataclass(frozen=True, slots=True)
class SeedConfig:
    seed: int = 20260831
    start_date: date = date(2026, 9, 4)
    intervention_at: datetime = datetime(2026, 9, 11, 9, 0)
    end_date: date = date(2026, 9, 17)
    exposure_rates: tuple[float, ...] = (0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 1.00)


@dataclass(frozen=True, slots=True)
class SeedBundle:
    config: SeedConfig
    tables: TableRows


__all__ = [
    "SeedBundle",
    "SeedConfig",
    "TABLE_COLUMNS",
    "TableRow",
    "TableRows",
]

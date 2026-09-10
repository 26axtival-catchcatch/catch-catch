# 원안 스키마와 현재 DuckDB 필드 조견표

기준일: 2026-09-10

원안 7개 테이블의 454개 필드 항목을 현재 합성 CSV와 분석용 DuckDB에 대조한 문서입니다.
로밍의 물리명이 잘린 14개 항목도 원문 표기로 포함합니다. 현재 CSV에 생성된 137개 필드는 모두 원안과 이름이 같습니다.
분석 단계에서는 매핑된 필드만 공통 이벤트 컬럼으로 변환합니다. 따라서 원안 필드명을 사용한 SQL과 분석용 SQL은 서로 호환되지 않습니다.

이 문서의 ‘미생성’은 현재 합성 데이터에서 빠졌다는 뜻입니다. 실제 운영 원천 테이블에서 컬럼을 삭제했다는 뜻은 아닙니다.
원안은 저장소의 `docs/seeding/tables/`에 남은 정의이며, 과거 실행 중이던 DB를 복구해 비교한 결과는 아닙니다.

필터링과 검색이 필요하면 [전체 필드 CSV](./duckdb-schema-comparison.csv)를 사용합니다.

- [테이블 대응과 필드 수](#테이블-대응과-필드-수)
- [전체 원안 필드 조견표](#2-전체-원안-필드-조견표)
- [생성 필드, 고정값, 타입과 값 변환](#3-원안에-없는-분석용-공통-필드와-고정값)
- [실제 파일 DuckDB 스키마](#4-실제-파일-duckdb의-전체-스키마)
- [해커톤 분석용 DuckDB 스키마](#5-해커톤-7개-source를-함께-읽었을-때의-분석용-스키마)

동반 CSV는 원안 필드당 1행이며, `table`과 `ordinal`을 합쳐 항목을 구분합니다.
물리명이 잘린 로밍 항목은 이름이 중복되므로 필드명만으로 중복을 제거하면 안 됩니다.
`original_line`은 원안 문서의 줄 번호입니다. `csv_field`가 비어 있으면 미생성,
`duckdb_fields`가 비어 있으면 분석용 컬럼에 미노출이며 구체적인 이유는 `status`와 `conversion`에 있습니다.

## 1. 저장 위치와 테이블 구조

| 구분 | 저장 위치 / 테이블 | 현재 동작 |
| --- | --- | --- |
| 원안 | `docs/seeding/tables/`의 7개 정의 | 원본 물리명, 논리명, 타입의 비교 기준 |
| 합성 원시 데이터 | `data/seeding/hackathon-2week/L*.csv` | 원래 테이블명과 선택된 필드명 유지, 전체 원안의 일부만 생성 |
| 등록 데이터 | `data/seeding/hackathon-2week/onboarded-sources/<source_id>/data.csv`와 `spec.json` | CSV 복사본과 공통 이벤트 매핑 규칙 |
| 기본 파일 DuckDB | `data/generated/customer_signal.duckdb` | 기본 데모 데이터와 시스템 테이블 5개, 해커톤 CSV 7개를 직접 저장하지 않음 |
| 분석용 메모리 DuckDB | 실행별 `events`와 Source별 뷰 | 선택된 Source와 기간의 공통 이벤트를 적재, 실행마다 생성 |
| 검증 코호트 | 필요 시 `verification_cohort_<n>` | 분석 과정에서 생성하는 고객 집합, 원안 테이블과 무관 |

### 테이블 대응과 필드 수

‘분석 변환’은 원안 필드 기준 개수입니다. 한 원안 필드가 여러 분석 컬럼으로 변환될 수 있으므로 DuckDB 컬럼 수와 다릅니다.
‘CSV만 유지’는 원시 파일에는 있지만 분석용 SQL에서 조회할 수 없는 필드입니다.

| 원안 테이블 | 분석용 뷰 | 원안 | CSV 유지 | 분석 변환 | CSV만 유지 | 필터 제외 | 미생성 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `L1DA_GA_REP_CHNL_BEHV_L` | `hackathon_app_behavior` | 118 | 23 | 10 | 12 | 1 | 95 |
| `L0UR_SEARCH_HISTORY` | `hackathon_search_history` | 20 | 17 | 8 | 9 | 0 | 3 |
| `L0UR_FEEDBACK` | `hackathon_search_feedback` | 9 | 9 | 5 | 4 | 0 | 0 |
| `L1RA_VOC_STT_DTL_H` | `hackathon_voc` | 70 | 18 | 8 | 10 | 0 | 52 |
| `L2ZI_MBL_VAS_ENTR_INFO_DALY_H` | `hackathon_vas_subscription` | 84 | 20 | 8 | 12 | 0 | 64 |
| `L1BAT_CUST_BLNG_AND_BNFT_SUM` | `hackathon_billing_profile` | 97 | 17 | 8 | 9 | 0 | 80 |
| `L1DA_RMNG_USE_MMLY_INTG_H` | `hackathon_roaming_usage` | 56 | 33 | 15 | 18 | 0 | 23 |

전체 원안 항목은 454개이며 CSV 유지 137개, 미생성 317개입니다.
CSV 유지 필드 중 분석 변환은 62개, CSV만 유지는 74개, 분석 필터 제외는 1개입니다.
로밍의 미생성 23개는 물리명 확인 가능 9개와 물리명이 잘린 14개로 구성됩니다.

모든 Source별 뷰는 `SELECT * FROM events WHERE source_id = ...` 형태입니다.
같은 실행에서는 뷰마다 같은 컬럼 집합을 가지며 다른 Source 전용 컬럼은 해당 행에서 `NULL`입니다.
`dim_*`, `measure_*` 컬럼은 실제 실행 데이터에서 수집하므로 선택 Source와 기간, 값의 존재 여부에 따라 달라집니다.

## 2. 전체 원안 필드 조견표

| 상태 | 의미 |
| --- | --- |
| 분석 필드 변환 | CSV에 원래 이름으로 유지, 분석용 DuckDB에서는 표에 적힌 이름과 타입으로 변환 |
| CSV만 유지 | CSV에는 존재하지만 공통 이벤트 매핑 없음, 분석용 DuckDB에는 미노출 |
| 분석 필터 제외 | 공통 이벤트 매핑은 존재하지만 분석 노출 필터에서 제거 |
| CSV 미생성 | 현재 합성 CSV와 분석용 DuckDB 모두에 없음 |
| 원안 물리명 잘림 / CSV 미생성 | 원안 문서의 물리명이 불완전하며 현재 생성 대상에서도 제외 |

CSV 자체에는 DB 타입이나 제약조건이 없습니다. 현재 CSV reader는 빈 문자열을 `None`, 나머지를 문자열로 읽습니다.
아래 ‘원안 타입’은 제공된 정의 그대로이며 CSV에서 해당 타입을 강제한다는 뜻은 아닙니다.
로밍의 `NUMERIC(22, ...)`처럼 정밀도가 잘린 타입도 추정하지 않았습니다.

### 2.1. 앱 행동 — `L1DA_GA_REP_CHNL_BEHV_L`

[원안 정의](./tables/L1DA_GA_REP_CHNL_BEHV_L), [현재 매핑](../../data/seeding/hackathon-2week/onboarded-sources/hackathon_app_behavior/spec.json)

| 번호 | 원안 필드명 | 논리명 | 원안 타입 | 현재 상태 | 분석용 DuckDB 필드 | DuckDB 타입 | 변환 / 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `CZ_LNK_KEY` | CSZ_연결키 | `INT64` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 2 | `P_YYYYMMDD` | 기준일(파티션키) | `DATE` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 3 | `GA_LNK_KEY` | GA연결키 | `INT64` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 4 | `BASE_DT` | 기준일자 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 5 | `CLT_ID` | 클라이언트ID | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 6 | `DMNS_CLT_ID` | 디멘젼클라이언트ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 7 | `SESN_ID` | 세션ID | `STRING` | 분석 필드 변환 | `dim_session_id` | `VARCHAR` | `dim_session_id`: 공통 이벤트 dimensions.session_id에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 8 | `PTPN_SESN_YN` | 참여세션여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 9 | `PTPN_SESN_TM` | 참여세션시간 | `NUMERIC` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 10 | `PTPN_SESN_EVET_YN` | 참여세션이벤트여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 11 | `VSTR_ID` | 방문자ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 12 | `CUST_NO` | 고객번호 | `STRING` | 분석 필드 변환 | `customer_id` | `VARCHAR` | `customer_id`: 문자열 고객키의 SHA-256 앞 24자리 + `customer_` 접두사 |
| 13 | `ENTR_NO` | 가입번호 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 14 | `DCRM_EVET_ENTR_NO` | DCRM이벤트가입번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 15 | `BUY_ENTR_NO` | 구매가입번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 16 | `PROD_NO` | 상품번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 17 | `SVC_CD` | 서비스코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 18 | `SVC_NM` | 서비스명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 19 | `PP_CD` | 요금제코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 20 | `PP_NM` | 요금제명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 21 | `YY10_AGLV_ID` | 10년연령대ID | `INT64` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 22 | `YY5_AGLV_ID` | 5년연령대ID | `INTEGER` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 23 | `SEX_DIVS_CD` | 성별구분코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 24 | `SEX_DIVS_NM` | 성별구분명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 25 | `CNVG_YN` | 결합여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 26 | `OCEM_YN` | 임직원여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 27 | `ORCO_OCMP_DIVS_NM` | 자사타사구분명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 28 | `LOG_DTTM` | 로그일시 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음; occurred_at에는 `BQ_LOAD_DTTM` 사용 |
| 29 | `CLT_BASE_VSIT_TMSC` | 클라이언트기준방문횟수 | `INT64` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 30 | `SESN_STAY_TM` | 세션체류시간 | `INT64` | 분석 필드 변환 | `measure_session_stay_seconds` | `DOUBLE` | `measure_session_stay_seconds`: 정수 파싱 후 `DOUBLE`; 단위 `seconds` |
| 31 | `LGIN_STUS_CD` | 로그인상태코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 32 | `TRM_KD_NM` | 단말유형명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 33 | `TRM_MDL_CD` | 단말모델코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 34 | `TRM_MDL_NM` | 단말모델명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 35 | `TRM_MANF_NM` | 단말제조사명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 36 | `OS_NM` | 운영체제명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 37 | `OS_VER_NM` | 운영체제버전명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 38 | `WEB_APP_DIVS_NM` | 웹APP구분명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 39 | `SITE_DIVS_NM` | 사이트구분명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 40 | `SITE_DETL_DIVS_NM` | 사이트상세구분명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 41 | `NOW_WEB_PAGE_HOST_ADDR` | 현재웹페이지호스트주소 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 42 | `NOW_WEB_PAGE_URL_ADDR` | 현재웹페이지URL주소 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 43 | `WEB_PAGE_DOC_TIT_NM` | 웹페이지문서제목명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 44 | `BFR_WEB_PAGE_URL_ADDR` | 이전웹페이지URL주소 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 45 | `STEM_ID` | 스트림ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 46 | `EVET_NM` | 이벤트명 | `STRING` | 분석 필드 변환 | `event_type` | `VARCHAR` | `event_type`: 문자열 변환 |
| 47 | `EVET_ACT_NM` | 이벤트액션명 | `STRING` | 분석 필드 변환 | `action` | `VARCHAR` | `action`: 문자열 변환 |
| 48 | `EVET_ACT_CATG_NM` | 이벤트액션카테고리명 | `STRING` | 분석 필드 변환 | `topic` | `VARCHAR` | `topic`: 문자열 변환; 제외 패턴 일치 값은 `unknown` |
| 49 | `EVET_ACT_LABE_NM` | 이벤트액션라벨명 | `STRING` | 분석 필드 변환 | `outcome` | `VARCHAR` | `outcome`: 문자열 변환; 제외 패턴 일치 값은 `unknown` |
| 50 | `PAGE_STAY_TM` | 페이지체류시간 | `INT64` | 분석 필드 변환 | `measure_page_stay_seconds` | `DOUBLE` | `measure_page_stay_seconds`: 정수 파싱 후 `DOUBLE`; 단위 `seconds` |
| 51 | `LINK_PAGE_INS_OUTS_DIVS_NM` | 링크페이지내부외부구분명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 52 | `LINK_URL_ADDR` | 링크URL주소 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 53 | `REP_CHNL_MENU_NM` | 대표채널메뉴명 | `STRING` | 분석 필드 변환 | `text`, `dim_menu` | `VARCHAR`, `VARCHAR` | `text`: 문자열 변환; `dim_menu`: 공통 이벤트 dimensions.menu에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 54 | `REP_CHNL_MENU_LVL1_NM` | 대표채널메뉴1레벨명 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 55 | `REP_CHNL_MENU_LVL2_NM` | 대표채널메뉴2레벨명 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 56 | `REP_CHNL_MENU_LVL3_NM` | 대표채널메뉴3레벨명 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 57 | `REP_CHNL_MENU_LVL4_NM` | 대표채널메뉴4레벨명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 58 | `REP_CHNL_MENU_LVL5_NM` | 대표채널메뉴5레벨명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 59 | `REP_CHNL_MENU_LVL6_NM` | 대표채널메뉴6레벨명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 60 | `REP_CHNL_MENU_LVL7_NM` | 대표채널메뉴7레벨명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 61 | `REP_CHNL_MENU_LVL8_NM` | 대표채널메뉴8레벨명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 62 | `REP_CHNL_MENU_LVL9_NM` | 대표채널메뉴9레벨명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 63 | `REP_CHNL_MENU_LVL10_NM` | 대표채널메뉴10레벨명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 64 | `INFW_DOMN_URL_ADDR` | 유입도메인URL주소 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 65 | `INFW_DOMN_HOST_ADDR` | 유입도메인호스트주소 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 66 | `INFW_DOMN_ENGN_NM` | 유입도메인엔진명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 67 | `INFW_DOMN_CATG_NM` | 유입도메인카테고리명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 68 | `INFW_SHWD_CNTN` | 유입검색어내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 69 | `INFW_CMPN_NM` | 유입캠페인명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 70 | `INFW_CMPN_AD_CNTN` | 유입캠페인광고내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 71 | `LGIN_MTHD_NM` | 로그인방법명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 72 | `SRCH_KD_NM` | 검색유형명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 73 | `BUY_ACT_DIVS_NM` | 구매액션구분명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 74 | `STLM_OPON_CNTN` | 결제옵션내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 75 | `STLM_STEP_CNTN` | 결제스텝내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 76 | `STLM_KD_NM` | 결제유형명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 77 | `BUY_ID` | 구매ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 78 | `BUY_AMT` | 구매금액 | `INT64` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 79 | `PROD_PCNT` | 상품개수 | `INT64` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 80 | `EVET_TIT_NM` | 이벤트제목명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 81 | `EVET_CLSS_NM` | 이벤트분류명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 82 | `GOAL_BEHV_FFIL_YN` | 목표행동수행여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 83 | `GA_CNC_NATN_NM` | GA접속국가명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 84 | `GA_CNC_AREA_NM` | GA접속지역명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 85 | `GA_CCW_NM` | GA시군구명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 86 | `ABTEST_ID` | 전시구좌 마케팅 인벤토리유형명 | `STRING` | 분석 필터 제외 | — | — | 공통 이벤트 dimensions.abtest_id에서 평탄화; 분석 노출 필터로 컬럼 제거 |
| 87 | `SCRN_ID` | 스크린ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 88 | `ABTEST_SECT_ID` | AB테스트섹션ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 89 | `ABTEST_FCTR_ID` | AB테스트요소ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 90 | `ABTEST_VAR_ID` | AB테스트변수ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 91 | `EXSC_EXCO_NM` | 전시구좌전시코너명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 92 | `EXSC_EXHI_ORD` | 전시구좌전시순서 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 93 | `EXSC_GRP_ID` | 전시구좌그룹ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 94 | `EXSC_MDUL_NM` | 전시구좌모듈명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 95 | `EXSC_MDUL_ID` | 전시구좌모듈ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 96 | `EXSC_CNTS_NM` | 전시구좌컨텐츠명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 97 | `EXSC_CNTS_EXHI_ORD` | 전시구좌컨텐츠전시순서 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 98 | `EXSC_BTN_NM` | 전시구좌버튼명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 99 | `EXSC_NM` | 전시구좌명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 100 | `EXSC_CMPN_ID` | 전시구좌캠페인ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 101 | `EXSC_CMPN_NM` | 전시구좌캠페인명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 102 | `EXSC_SGMT_KD_NM` | 전시구좌세그먼트유형명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 103 | `EXSC_SGMT_ID` | 전시구좌세그먼트ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 104 | `EXSC_SGMT_NM` | 전시구좌세그먼트명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 105 | `EXSC_EXCO_GRP_ID` | 전시구좌전시코너그룹ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 106 | `PMTN_EVET_ID` | 프로모션이벤트ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 107 | `PMTN_EVET_TERM` | 프로모션이벤트기간 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 108 | `JNCO_ID` | 제휴사ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 109 | `JNCO_NM` | 제휴사명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 110 | `JNCO_IDKD_NM` | 제휴사업종명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 111 | `CPN_ID` | 쿠폰ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 112 | `CPN_NM` | 쿠폰명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 113 | `NOW_PP_NM` | 현재요금제명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 114 | `CHOC_PP_NM` | 선택요금제명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 115 | `RCMD_PP_NM` | 추천요금제명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 116 | `PMM_PP_DATA_USAG` | 전월요금제데이터사용량 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 117 | `BQ_LOAD_DTTM` | BQ적재일시 | `DATETIME` | 분석 필드 변환 | `occurred_at` | `TIMESTAMP` | `occurred_at`: Asia/Seoul로 해석 후 UTC 변환, timezone 정보 제거 |
| 118 | `BQ_LOAD_USER_ID` | BQ적재사용자ID | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |

### 2.2. AI 검색 이력 — `L0UR_SEARCH_HISTORY`

[원안 정의](./tables/L0UR_SEARCH_HISTORY), [현재 매핑](../../data/seeding/hackathon-2week/onboarded-sources/hackathon_search_history/spec.json)

| 번호 | 원안 필드명 | 논리명 | 원안 타입 | 현재 상태 | 분석용 DuckDB 필드 | DuckDB 타입 | 변환 / 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `CZ_LNK_KEY` | CSZ 연결키 | `INTEGER` | 분석 필드 변환 | `customer_id` | `VARCHAR` | `customer_id`: 문자열 고객키의 SHA-256 앞 24자리 + `customer_` 접두사 |
| 2 | `P_YYYYMMDD` | 기준일(파티션키) | `DATE` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 3 | `ID` | 테이블 PK | `INTEGER` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음; `event_id` 생성에 사용하지 않음 |
| 4 | `THREAD_ID` | 검색 스레드 ID | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음; `event_id` 생성에 사용하지 않음 |
| 5 | `RUN_ID` | 검색 실행 ID | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음; `event_id` 생성에 사용하지 않음 |
| 6 | `SEARCH_QUERY` | 사용자가 입력한 검색 쿼리 | `STRING` | 분석 필드 변환 | `text` | `VARCHAR` | `text`: 문자열 변환 |
| 7 | `SEARCH_RESULT` | AI검색 응답 결과 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 8 | `CREATED_AT` | 검색 이력 생성 일시 | `DATETIME` | 분석 필드 변환 | `occurred_at` | `TIMESTAMP` | `occurred_at`: Asia/Seoul로 해석 후 UTC 변환, timezone 정보 제거 |
| 9 | `STATUS` | 검색 이력 상태 | `STRING` | 분석 필드 변환 | `outcome` | `VARCHAR` | `outcome`: 문자열 변환; 제외 패턴 일치 값은 `unknown` |
| 10 | `FIRST_RESPONSE_LATENCY_MS` | 최초 응답까지 소요된 시간 | `FLOAT` | 분석 필드 변환 | `measure_latency_ms` | `DOUBLE` | `measure_latency_ms`: 실수 파싱 후 `DOUBLE`; 단위 `milliseconds` |
| 11 | `MODIFIED_AT` | 검색 이력 수정 일시 | `DATETIME` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 12 | `WAS_CACHE_HIT` | 응답 캐시 적중 여부 | `BOOLEAN` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 13 | `SEARCH_QUERY_TYPE` | 검색 쿼리 타입 | `STRING` | 분석 필드 변환 | `action`, `dim_query_type` | `VARCHAR`, `VARCHAR` | `action`: 문자열 변환; initial → search, repeat → repeat_search; `dim_query_type`: 공통 이벤트 dimensions.query_type에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 14 | `REWRITE_SEARCH_QUERY` | 재검색 쿼리 | `STRING` | 분석 필드 변환 | `topic` | `VARCHAR` | `topic`: 문자열 변환; 제외 패턴 일치 값은 `unknown` |
| 15 | `WAS_CACHE_HIT_REWRITE_SEARCH_QUERY` | 캐시 검색 쿼리 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 16 | `SEARCH_RESULT_REFERENCE_DOCUMENTS` | 검색 결과 참고 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 17 | `SEARCH_RESULT_REFERENCE_TEMPLATE_NAME` | 참조 템플릿명 | `STRING` | 분석 필드 변환 | `dim_template` | `VARCHAR` | `dim_template`: 공통 이벤트 dimensions.template에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 18 | `IS_FALLBACK_SEARCH_RESULT` | 대체 검색 결과 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 19 | `BQ_LOAD_DTTM` | BQ적재일시 | `DATETIME` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 20 | `BQ_LOAD_USER_ID` | BQ적재사용자ID | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |

### 2.3. AI 검색 피드백 — `L0UR_FEEDBACK`

[원안 정의](./tables/L0UR_FEEDBACK), [현재 매핑](../../data/seeding/hackathon-2week/onboarded-sources/hackathon_search_feedback/spec.json)

| 번호 | 원안 필드명 | 논리명 | 원안 타입 | 현재 상태 | 분석용 DuckDB 필드 | DuckDB 타입 | 변환 / 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `CZ_LNK_KEY` | CSZ 연결키 | `INTEGER` | 분석 필드 변환 | `customer_id` | `VARCHAR` | `customer_id`: 문자열 고객키의 SHA-256 앞 24자리 + `customer_` 접두사 |
| 2 | `P_YYYYMMDD` | 기준일(파티션키) | `DATE` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 3 | `ID` | 테이블 PK | `INTEGER` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음; `event_id` 생성에 사용하지 않음 |
| 4 | `RUN_ID` | 검색 실행 ID | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음; `event_id` 생성에 사용하지 않음 |
| 5 | `FEEDBACK_TYPE` | 피드백 타입 | `STRING` | 분석 필드 변환 | `outcome` | `VARCHAR` | `outcome`: 문자열 변환; 제외 패턴 일치 값은 `unknown` |
| 6 | `REASON` | 피드백 사유 | `STRING` | 분석 필드 변환 | `text`, `dim_reason` | `VARCHAR`, `VARCHAR` | `text`: 문자열 변환; `dim_reason`: 공통 이벤트 dimensions.reason에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 7 | `OPTION` | 피드백의 세부 선택 옵션 | `STRING` | 분석 필드 변환 | `topic` | `VARCHAR` | `topic`: 문자열 변환; 제외 패턴 일치 값은 `unknown` |
| 8 | `BQ_LOAD_DTTM` | BQ적재일시 | `DATETIME` | 분석 필드 변환 | `occurred_at` | `TIMESTAMP` | `occurred_at`: Asia/Seoul로 해석 후 UTC 변환, timezone 정보 제거 |
| 9 | `BQ_LOAD_USER_ID` | BQ적재사용자ID | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |

### 2.4. VOC — `L1RA_VOC_STT_DTL_H`

[원안 정의](./tables/L1RA_VOC_STT_DTL_H), [현재 매핑](../../data/seeding/hackathon-2week/onboarded-sources/hackathon_voc/spec.json)

| 번호 | 원안 필드명 | 논리명 | 원안 타입 | 현재 상태 | 분석용 DuckDB 필드 | DuckDB 타입 | 변환 / 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `P_YYYYMMDD` | 기준일(파티션키) | `DATE` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 2 | `CZ_LNK_KEY` | CSZ연결키 | `INTEGER` | 분석 필드 변환 | `customer_id` | `VARCHAR` | `customer_id`: 문자열 고객키의 SHA-256 앞 24자리 + `customer_` 접두사 |
| 3 | `BASE_DT` | 기준일자 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 4 | `CALL_ID` | 콜ID | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음; `event_id` 생성에 사용하지 않음 |
| 5 | `AGNT_ID` | 대리인ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 6 | `CALL_CRTE_DTTM` | 콜생성일시 | `DATETIME` | 분석 필드 변환 | `occurred_at` | `TIMESTAMP` | `occurred_at`: Asia/Seoul로 해석 후 UTC 변환, timezone 정보 제거 |
| 7 | `CALL_STRT_DT` | 콜시작일자 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 8 | `CALL_STRT_TM` | 콜시작시간 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 9 | `CALL_NXT_STRT_TM` | 콜다음시작시간 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 10 | `CALL_END_DT` | 콜종료일자 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 11 | `CALL_END_TM` | 콜종료시간 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 12 | `CUST_CNSL_TM` | 고객상담시간 | `INTEGER` | 분석 필드 변환 | `measure_consult_seconds` | `DOUBLE` | `measure_consult_seconds`: 정수 파싱 후 `DOUBLE`; 단위 `seconds` |
| 13 | `CUST_CNTT_TLNO` | 고객연락전화번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 14 | `TEAM_CD` | 팀코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 15 | `TEAM_NM` | 팀명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 16 | `CSCT_CD` | 상담실코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 17 | `CSCT_NM` | 상담실명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 18 | `CNTR_CD` | 센터코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 19 | `CNTR_NM` | 센터명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 20 | `CALL_DIVS_CD` | 콜구분코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 21 | `TRRC_DIVS_CD` | 송수신구분코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 22 | `STT_TXT_CNTN` | STT텍스트내용 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 23 | `INQU_CNTN` | 문의내용 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 24 | `CSLR_PRSS_CNTN` | 상담사처리내용 | `STRING` | 분석 필드 변환 | `dim_resolution` | `VARCHAR` | `dim_resolution`: 공통 이벤트 dimensions.resolution에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 25 | `CSLR_UTRT_CNTN` | 상담사미처리내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 26 | `CNSL_ALL_SMRY_CNTN` | 상담전체요약내용 | `STRING` | 분석 필드 변환 | `text` | `VARCHAR` | `text`: 문자열 변환 |
| 27 | `CUST_SNMT_NM` | 고객감정명 | `STRING` | 분석 필드 변환 | `outcome` | `VARCHAR` | `outcome`: 문자열 변환; 제외 패턴 일치 값은 `unknown` |
| 28 | `CNSL_SBJC_TIT_NM` | 상담주제제목명 | `STRING` | 분석 필드 변환 | `dim_subject` | `VARCHAR` | `dim_subject`: 공통 이벤트 dimensions.subject에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 29 | `CSLR_PRSS_UTRT_CNTN` | 상담사처리미처리내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 30 | `CNSL_SCLS_CD` | 상담소분류코드 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 31 | `CNSL_THMA_NM` | 상담테마명 | `STRING` | 분석 필드 변환 | `topic` | `VARCHAR` | `topic`: 문자열 변환; 제외 패턴 일치 값은 `unknown` |
| 32 | `THMA_CNSL_BGN_YN` | 테마상담신규여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 33 | `CNSL_THMA_SMRY_CNTN` | 상담테마요약내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 34 | `INTG_USER_ID` | 통합사용자ID | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 35 | `SVC_CD` | 서비스코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 36 | `ENTR_NO` | 가입번호 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 37 | `CUST_NO` | 고객번호 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 38 | `CNSL_RSPO_CNT` | 상담응대건수 | `INTEGER` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 39 | `N01_CUST_RSPO_SQNO` | 01고객응대누적번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 40 | `N01_CUST_RSPO_TME` | 01고객응대시각 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 41 | `N01_CLPR_TLNO` | 01통화자전화번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 42 | `N01_RSPO_SCLS_CD` | 01응대소분류코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 43 | `N01_RSPO_SCLS_NM` | 01응대소분류명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 44 | `N01_CUST_RSPO_MEMO_CNTN` | 01고객응대메모내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 45 | `N02_CUST_RSPO_SQNO` | 02고객응대누적번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 46 | `N02_CUST_RSPO_TME` | 02고객응대시각 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 47 | `N02_CLPR_TLNO` | 02통화자전화번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 48 | `N02_RSPO_SCLS_CD` | 02응대소분류코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 49 | `N02_RSPO_SCLS_NM` | 02응대소분류명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 50 | `N02_CUST_RSPO_MEMO_CNTN` | 02고객응대메모내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 51 | `N03_CUST_RSPO_SQNO` | 03고객응대누적번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 52 | `N03_CUST_RSPO_TME` | 03고객응대시각 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 53 | `N03_CLPR_TLNO` | 03통화자전화번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 54 | `N03_RSPO_SCLS_CD` | 03응대소분류코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 55 | `N03_RSPO_SCLS_NM` | 03응대소분류명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 56 | `N03_CUST_RSPO_MEMO_CNTN` | 03고객응대메모내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 57 | `N04_CUST_RSPO_SQNO` | 04고객응대누적번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 58 | `N04_CUST_RSPO_TME` | 04고객응대시각 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 59 | `N04_CLPR_TLNO` | 04통화자전화번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 60 | `N04_RSPO_SCLS_CD` | 04응대소분류코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 61 | `N04_RSPO_SCLS_NM` | 04응대소분류명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 62 | `N04_CUST_RSPO_MEMO_CNTN` | 04고객응대메모내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 63 | `N05_CUST_RSPO_SQNO` | 05고객응대누적번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 64 | `N05_CUST_RSPO_TME` | 05고객응대시각 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 65 | `N05_CLPR_TLNO` | 05통화자전화번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 66 | `N05_RSPO_SCLS_CD` | 05응대소분류코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 67 | `N05_RSPO_SCLS_NM` | 05응대소분류명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 68 | `N05_CUST_RSPO_MEMO_CNTN` | 05고객응대메모내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 69 | `BQ_LOAD_DTTM` | BQ적재일시 | `DATETIME` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 70 | `BQ_LOAD_USER_ID` | BQ적재사용자ID | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |

### 2.5. 부가서비스 가입 — `L2ZI_MBL_VAS_ENTR_INFO_DALY_H`

[원안 정의](./tables/L2ZI_MBL_VAS_ENTR_INFO_DALY_H), [현재 매핑](../../data/seeding/hackathon-2week/onboarded-sources/hackathon_vas_subscription/spec.json)

| 번호 | 원안 필드명 | 논리명 | 원안 타입 | 현재 상태 | 분석용 DuckDB 필드 | DuckDB 타입 | 변환 / 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `P_YYYYMMDD` | 기준일(파티션키) | `DATE` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 2 | `BASE_YYMM` | 기준년월 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 3 | `MM_LAST_DT_YN` | 월마지막일자여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 4 | `ENTR_NO` | 가입번호 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 5 | `ENTR_SVC_SEQNO` | 가입상품누적번호 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 6 | `CUST_NO` | 고객번호 | `STRING` | 분석 필드 변환 | `customer_id` | `VARCHAR` | `customer_id`: 문자열 고객키의 SHA-256 앞 24자리 + `customer_` 접두사 |
| 7 | `PRD_NO` | 상품번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 8 | `AGE_SGMT_NM` | 연령세그먼트명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 9 | `BILL_ACNT_NO` | 청구계정번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 10 | `PROD_CD` | 상품코드 | `STRING` | 분석 필드 변환 | `dim_product_code` | `VARCHAR` | `dim_product_code`: 공통 이벤트 dimensions.product_code에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 11 | `PROD_NM` | 상품명 | `STRING` | 분석 필드 변환 | `topic`, `text` | `VARCHAR`, `VARCHAR` | `topic`: 문자열 변환; 제외 패턴 일치 값은 `unknown`; `text`: 문자열 변환 |
| 12 | `CATG_LVL1_NM` | 카테고리1레벨명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 13 | `CATG_LVL2_NM` | 카테고리2레벨명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 14 | `CATG_LVL3_NM` | 카테고리3레벨명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 15 | `CATG_LVL4_NM` | 카테고리4레벨명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 16 | `BUY_PRC_YN` | 구매가격여부 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 17 | `BILL_KD_CD` | 청구유형코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 18 | `VAT_XCLN_AMT` | 부가세제외금액 | `INTEGER` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 19 | `VAT_INCL_ALL_AMT` | 부가세포함전체금액 | `INTEGER` | 분석 필드 변환 | `measure_amount_krw` | `DOUBLE` | `measure_amount_krw`: 정수 파싱 후 `DOUBLE`; 단위 `KRW` |
| 20 | `PAC_YN` | 패키지여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 21 | `PAC_DIVS_CD` | 패키지구분코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 22 | `RTNG_DIVS_CD` | 과금구분코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 23 | `PROD_CSTC_CNTN` | 상품구성내용 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 24 | `KPI_YN` | KPI여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 25 | `ARST_INCL_YN` | 실적포함여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 26 | `SVC_KD_CD` | 상품유형코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 27 | `SVC_STTS_CD` | 상품상태코드 | `STRING` | 분석 필드 변환 | `action` | `VARCHAR` | `action`: 문자열 변환 |
| 28 | `SVC_STTS_NM` | 상품상태명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 29 | `SVC_STRT_DT` | 서비스시작일자 | `DATE` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 30 | `SVC_END_DT` | 서비스종료일자 | `DATE` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 31 | `BGN_YN` | 신규여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 32 | `SRVL_YN` | 잔존여부 | `STRING` | 분석 필드 변환 | `outcome` | `VARCHAR` | `outcome`: 문자열 변환; 제외 패턴 일치 값은 `unknown` |
| 33 | `EXPY_YN` | 해지여부 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 34 | `PROD_ENTR_DAYS` | 상품가입일수 | `INTEGER` | 분석 필드 변환 | `measure_subscription_days` | `DOUBLE` | `measure_subscription_days`: 정수 파싱 후 `DOUBLE`; 단위 `days` |
| 35 | `PROD_ENTR_MMCT` | 상품가입개월수 | `INTEGER` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 36 | `PAC_CMPT_PROD_YN` | 패키지구성품상품여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 37 | `PAC_PROD_CD` | 패키지상품코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 38 | `PAC_PROD_NM` | 패키지상품명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 39 | `PAC_PROD_STRT_DT` | 패키지상품시작일자 | `DATE` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 40 | `PAC_PROD_END_DT` | 패키지상품종료일자 | `DATE` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 41 | `SVC_FRST_STRT_DT` | 상품최초시작일자 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 42 | `SVC_STRT_RSN_CD` | 상품시작사유코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 43 | `SVC_STRT_RSN_NM` | 상품시작사유명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 44 | `SVC_END_RSN_CD` | 상품종료사유코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 45 | `SVC_END_RSN_NM` | 상품종료사유명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 46 | `RSV_END_YN` | 예약종료여부 | `INTEGER` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 47 | `RSV_END_DT` | 예약종료일자 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 48 | `BASF_AMT` | 기본료금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 49 | `BASF_DACAL_YN` | 기본료일할계산여부 | `INTEGER` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 50 | `PP_DPND_YN` | 요금제종속여부 | `INTEGER` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 51 | `SVC_ENTR_PRSS_DLR_CD` | 상품가입처리대리점코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 52 | `SVC_ENTR_OPRTR_ID` | 상품가입처리자ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 53 | `SVC_EXPRY_PRSS_DLR_CD` | 상품해지처리대리점코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 54 | `SVC_EXPRY_OPRTR_ID` | 상품해지처리자ID | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 55 | `ATRCT_CHNL_CD` | 유치채널코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 56 | `ATRCT_CHNL_NM` | 유치채널명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 57 | `RSALE_POS_CD` | 실판매POS코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 58 | `SALE_EMP_NO` | 판매사원번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 59 | `LAST_YN` | 최종여부 | `INTEGER` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 60 | `ATRC_CHNL_DIVS_NM` | 유치채널구분명 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 61 | `ATRC_DGTL_CHNL_DIVS_NM` | 유치디지털채널구분명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 62 | `LVL1_ORG_NM` | 1레벨조직명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 63 | `LVL2_ORG_NM` | 2레벨조직명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 64 | `LVL3_ORG_NM` | 3레벨조직명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 65 | `LVL4_ORG_NM` | 4레벨조직명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 66 | `EXPY_CHNL_DIVS_NM` | 해지채널구분명 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 67 | `DEVC_MDL_CD` | 단말모델코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 68 | `DEVC_MDL_NM` | 단말모델명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 69 | `PET_NM` | 펫명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 70 | `PET_NM2` | 펫명2 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 71 | `DVIC_KD_NM` | 단말기유형명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 72 | `DVIC_SPEC_KD_NM` | 단말기스펙유형명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 73 | `DVIC_OS_NM` | 단말기운영체제명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 74 | `THMM_TRM_SALE_YN` | 당월단말판매여부 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 75 | `STOP_XCLN_TRM_USE_TERM_DAYS` | 정지제외단말사용기간일수 | `INTEGER` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 76 | `TRM_USE_TERM_MMCT` | 단말사용기간개월수 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 77 | `PP_CD` | 요금제코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 78 | `PP_NM` | 요금제명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 79 | `PURE_RATE` | 순요율 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 80 | `PP_NCRG_GRP_NM` | 요금제순액그룹명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 81 | `PP_DIVS_NM` | 요금제구분명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 82 | `LTE_G5_PP_DIVS_NM` | LTE5G요금제구분명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 83 | `BQ_LOAD_DTTM` | BQ적재일시 | `DATETIME` | 분석 필드 변환 | `occurred_at` | `TIMESTAMP` | `occurred_at`: Asia/Seoul로 해석 후 UTC 변환, timezone 정보 제거 |
| 84 | `BQ_LOAD_USER_ID` | BQ적재사용자ID | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |

### 2.6. 고객 빌링 프로필 — `L1BAT_CUST_BLNG_AND_BNFT_SUM`

[원안 정의](./tables/L1BAT_CUST_BLNG_AND_BNFT_SUM), [현재 매핑](../../data/seeding/hackathon-2week/onboarded-sources/hackathon_billing_profile/spec.json)

| 번호 | 원안 필드명 | 논리명 | 원안 타입 | 현재 상태 | 분석용 DuckDB 필드 | DuckDB 타입 | 변환 / 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `CZ_LNK_KEY` | CSZ_연결키 | `INT64` | 분석 필드 변환 | `customer_id` | `VARCHAR` | `customer_id`: 문자열 고객키의 SHA-256 앞 24자리 + `customer_` 접두사 |
| 2 | `BASE_YYMM` | 기준년월 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 3 | `BILL_ACNT_NO` | 암호화청구계정번호 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 4 | `ACE_NO` | 암호화납입자정보 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 5 | `ENTR_NO` | 암호화가입번호 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 6 | `CUST_NO` | 암호화고객번호 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 7 | `YY10_AGELV_ID` | 10년연령대ID | `INT64` | 분석 필드 변환 | `dim_age_band` | `VARCHAR` | `dim_age_band`: 공통 이벤트 dimensions.age_band에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 8 | `CUST_AGE` | 고객연령 | `INT64` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 9 | `ONEID_EMAIL_ADDR` | 암호화ONEID이메일주소 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 10 | `SVC_CD` | 서비스코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 11 | `SVC_NM` | 서비스명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 12 | `PP_CD` | 요금제코드 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 13 | `PP_NM` | 요금제명 | `STRING` | 분석 필드 변환 | `topic`, `text` | `VARCHAR`, `VARCHAR` | `topic`: 문자열 변환; 제외 패턴 일치 값은 `unknown`; `text`: 문자열 변환 |
| 14 | `PRD_NO` | 암호화상품번호 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 15 | `ENTR_STTS_CD` | 가입상태코드 | `STRING` | 분석 필드 변환 | `outcome` | `VARCHAR` | `outcome`: 문자열 변환; 제외 패턴 일치 값은 `unknown` |
| 16 | `ENTR_STTS_NM` | 가입상태명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 17 | `CNVG_NO` | 결합번호 | `INT64` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 18 | `HM_CD` | 홈코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 19 | `FRST_ENTR_DT` | 최초개통일자 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 20 | `EXPRY_DT` | 해지일자 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 21 | `BAS_AMT` | 기본료금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 22 | `SPPS_AMT` | 부가서비스금액 | `NUMERIC` | 분석 필드 변환 | `measure_vas_amount_krw` | `DOUBLE` | `measure_vas_amount_krw`: 정수 파싱 후 `DOUBLE`; 단위 `KRW` |
| 23 | `DEVC_INSTT_AMT` | 단말할부금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 24 | `DEVC_SALE_AMT` | 단말판매금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 25 | `DEVC_RENT_AMT` | 단말임대금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 26 | `DOME_CALL_AMT` | 국내통화료금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 27 | `DOME_VDO_CALL_AMT` | 국내영상통화료금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 28 | `ADDV_CALL_USE_AMT` | 부가통화사용금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 29 | `DOME_LTTR_TADV_AMT` | 국내문자이용금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 30 | `ENTP_LTTR_TADV_AMT` | 기업문자이용요금금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 31 | `MBL_GEN3_DATA_TADV_AMT` | 모바일3G데이터사용료금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 32 | `MBL_LTE_DATA_TADV_AMT` | 모바일LTE데이터사용료금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 33 | `RMNG_TADV_AMT` | 로밍이용금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 34 | `ICTY_CALL_AMT` | 시내통화료금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 35 | `OCTY_CALL_AMT` | 시외통화료금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 36 | `INTCALL_CALL_AMT` | 국제통화료금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 37 | `NAT_REP_CALL_AMT` | 전국대표통화료금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 38 | `ETC_CALL_AMT` | 기타통화료금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 39 | `INFO_TADV_AMT` | 정보이용료 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 40 | `PPS_RING_ELCTC_AMT` | PPS링충전금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 41 | `SMLS_STLM_AMT` | 소액결제금액 | `NUMERIC` | 분석 필드 변환 | `measure_micropayment_amount_krw` | `DOUBLE` | `measure_micropayment_amount_krw`: 정수 파싱 후 `DOUBLE`; 단위 `KRW` |
| 42 | `GOOGLE_PLAY_BUY_AMT` | 구글플레이구매금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 43 | `INTG_APPSTORE_STLM_AMT` | 통합앱스토어결제금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 44 | `IPTV_VOD_TADV_AMT` | IPTVVOD이용금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 45 | `ENTF_AMT` | 가입비금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 46 | `EBCST_AMT` | 설치비금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 47 | `ENGR_GOUT_AMT` | 기사출동금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 48 | `DEVC_INDM_AMT` | 단말배상금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 49 | `DEVC_RPAR_AMT` | 단말수리금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 50 | `AS_AMT` | AS금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 51 | `AGDC_RETURN_AMT` | 약정할인반환금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 52 | `DEVC_RETURN_AMT` | 단말반환금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 53 | `DEVC_SUPRT_STACC_AMT` | 단말지원정산금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 54 | `BASF_DSCNT_RETURN_AMT` | 기본료할인반환금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 55 | `SPPS_DSCNT_RETURN_AMT` | 부가서비스할인반환금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 56 | `CNVG_DSCNT_RETURN_AMT` | 결합할인반환금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 57 | `OFFR_DSCNT_RETURN_AMT` | 오퍼할인반환금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 58 | `EBCST_RETURN_AMT` | 설치비반환금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 59 | `EXPRY_RETURN_AMT` | 해지반환금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 60 | `ETC_RETURN_AMT` | 기타반환금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 61 | `ETC_AMT` | 기타금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 62 | `AGDC_AMT` | 약정할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 63 | `CHCE_AGDC_AMT` | 선택약정할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 64 | `LNTEM_DSCNT_AMT` | 장기할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 65 | `HANBNG_YO_CNVG_DSCNT_AMT` | 한방에YO결합할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 66 | `ETC_CNVG_DSCNT_AMT` | 기타결합할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 67 | `PGM_DSCNT_AMT` | 프로그램할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 68 | `CUST_MGMT_DSCNT_AMT` | 고객케어할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 69 | `PRMTN_DSCNT_AMT` | 프로모션할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 70 | `MBRSH_DSCNT_AMT` | 멤버십할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 71 | `PUBWF_DSCNT_AMT` | 공공복지할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 72 | `GROP_DSCNT_AMT` | 단체할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 73 | `CNTC_DSCNT_AMT` | 계약할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 74 | `ETC_DSCNT_AMT` | 기타할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 75 | `CHRG_ADJMT_DSCNT_AMT` | 요금조정할인금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 76 | `CNTC_CHRG_ADJMT_AMT` | 계약요금조정금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 77 | `PMTH_UCLM_AMT` | 전월미청구금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 78 | `LTPYM_ADDC_AMT` | 연체가산금 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 79 | `BDP_NON_CLSS_BILL_AMT` | BDP미분류청구금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 80 | `BILL_VAT_AMT` | 청구부가가치세금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 81 | `TOT_BILL_AMT` | 청구총금액 | `NUMERIC` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 82 | `PMTH_UPAID_AMT` | 전월미납금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 83 | `PMTH_XCLN_ACLTN_UPAID_AMT` | 전월제외누적미납금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 84 | `PYM_AMT` | 납부금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 85 | `THMN_DEVC_SUPRT_AMT` | 당월단말지원금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 86 | `THMN_GIFT_AMT` | 당월사은품금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 87 | `MBRSH_RMND_PNT` | 멤버십잔여포인트 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 88 | `THMN_MBRSH_USE_PNT` | 당월멤버십사용포인트 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 89 | `THMN_CMPN_AMT` | 당월캠페인이용금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 90 | `THMN_EZPNT_USE_AMT` | 당월EZ포인트사용금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 91 | `THMN_YO_PNT_USE_AMT` | 당월YO포인트사용금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 92 | `THMN_AIR_MLGE_PNT_AMT` | 당월항공마일리지부여금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 93 | `CNTRB_PRFT_AMT` | 공헌이익금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 94 | `MBOOK_AMT` | 머니북금액 | `NUMERIC` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 95 | `DP_LOAD_DTTM` | 데이터처리적재시간 | `DATETIME` | 분석 필드 변환 | `occurred_at` | `TIMESTAMP` | `occurred_at`: Asia/Seoul로 해석 후 UTC 변환, timezone 정보 제거 |
| 96 | `DP_LOAD_USER_ID` | 데이터처리사용자아이디 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 97 | `SEX_DV_CD` | 성별구분코드 | `STRING` | 분석 필드 변환 | `dim_sex` | `VARCHAR` | `dim_sex`: 공통 이벤트 dimensions.sex에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |

### 2.7. 로밍 이용 — `L1DA_RMNG_USE_MMLY_INTG_H`

[원안 정의](./tables/L1DA_RMNG_USE_MMLY_INTG_H), [현재 매핑](../../data/seeding/hackathon-2week/onboarded-sources/hackathon_roaming_usage/spec.json)

| 번호 | 원안 필드명 | 논리명 | 원안 타입 | 현재 상태 | 분석용 DuckDB 필드 | DuckDB 타입 | 변환 / 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `CSZ_LNK_KEY` | CSZ_연결키 | `INT64` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 2 | `P_YYYYMM` | 기준연월(최저치) | `INT64` | 분석 필드 변환 | `dim_billing_month` | `VARCHAR` | `dim_billing_month`: 공통 이벤트 dimensions.billing_month에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 3 | `ENTR_NO` | 가입번호 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 4 | `CUST_NO` | 고객번호 | `STRING` | 분석 필드 변환 | `customer_id` | `VARCHAR` | `customer_id`: 문자열 고객키의 SHA-256 앞 24자리 + `customer_` 접두사 |
| 5 | `BILL_ACNT_NO` | 청구계정번호 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 6 | `PROD_NO` | 상품번호 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 7 | `AG10_AGJU_ID` | 10대연령확인 | `INT64` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 8 | `CUST_AGE` | 고객연령 | `INT64` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 9 | `SEX_DIVS_CD` | 성별구분코드 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 10 | `SEX_DIVS_NM` | 성별구분명 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 11 | `CUST_BRTH_YEAR` | 고객출생년월 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 12 | `CUST_KD_CD` | 고객유형코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 13 | `CUST_KD_NM` | 고객유형명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 14 | `PP_CD` | 요금제코드 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 15 | `PP_NM` | 요금제명 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 16 | `NCRG_CHRG` | 순정요금 | `NUMERIC(22, ...)` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 17 | `ENTR_STUS_CD` | 가입일상태코드 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 18 | `ENTR_STUS_NM` | 가입일상태명 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 19 | `MRKT_CD` | 단말코드 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 20 | `MRKT_NM` | 단말명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 21 | `TRM_MDL_CD` | 단말상품군명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 22 | `TRM_MDL_NM` | 단말모델명 | `STRING` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 23 | `SCDEV_USE_YN` | 2ND단말기사용여부 | `INT64` | CSV 미생성 | — | — | 현재 합성 CSV 및 분석용 DuckDB에 없음 |
| 24 | `RMNG_NATN_NM` | 로밍국가명 | `STRING` | 분석 필드 변환 | `dim_country` | `VARCHAR` | `dim_country`: 공통 이벤트 dimensions.country에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 25 | `DPTR_DT` | 출국일자 | `STRING` | 분석 필드 변환 | `dim_departure_date` | `VARCHAR` | `dim_departure_date`: 공통 이벤트 dimensions.departure_date에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 26 | `HMCML_DT` | 귀국일자 | `STRING` | 분석 필드 변환 | `dim_return_date` | `VARCHAR` | `dim_return_date`: 공통 이벤트 dimensions.return_date에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 27 | `ABRD_STAY_DAYS` | 국외체류일수 | `INT64` | 분석 필드 변환 | `measure_abroad_stay_days` | `DOUBLE` | `measure_abroad_stay_days`: 정수 파싱 후 `DOUBLE`; 단위 `days` |
| 28 | `SPPS_CD` | 부가서비스코드 | `STRING` | 분석 필드 변환 | `dim_product_code` | `VARCHAR` | `dim_product_code`: 공통 이벤트 dimensions.product_code에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 29 | `SPPS_NM` | 부가서비스명 | `STRING` | 분석 필드 변환 | `text` | `VARCHAR` | `text`: 문자열 변환 |
| 30 | `SPPS_ENTR_STUS_CD` | 부가서비스가입상태코드 | `STRING` | 분석 필드 변환 | `outcome` | `VARCHAR` | `outcome`: 문자열 변환; 제외 패턴 일치 값은 `unknown` |
| 31 | `SPPS_ENTR_STUS_NM` | 부가서비스가입상태명 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 32 | `SPPS_FRST_ENTR_DT` | 부가서비스최초가입일자 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 33 | `SPPS_STRT_DT` | 부가서비스시작일자 | `STRING` | 분석 필드 변환 | `dim_service_start_date` | `VARCHAR` | `dim_service_start_date`: 공통 이벤트 dimensions.service_start_date에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 34 | `SPPS_END_DT` | 부가서비스종료일자 | `STRING` | 분석 필드 변환 | `dim_service_end_date` | `VARCHAR` | `dim_service_end_date`: 공통 이벤트 dimensions.service_end_date에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 35 | `RTNG_STRT_DT` | 과금시작일자 | `STRING` | 분석 필드 변환 | `dim_rating_start_date` | `VARCHAR` | `dim_rating_start_date`: 공통 이벤트 dimensions.rating_start_date에서 평탄화; 문자열 유지, 제외 패턴 일치 값은 미노출 |
| 36 | `RTNG_END_DT` | 과금종료일자 | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 37 | `PP_USE_DAYS` | 요금제사용일수 | `INT64` | 분석 필드 변환 | `measure_plan_use_days` | `DOUBLE` | `measure_plan_use_days`: 정수 파싱 후 `DOUBLE`; 단위 `days` |
| 38 | `MERT_USE_DAYS` | 증량제사용일수 | `INT64` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 39 | `DATA_USAG` | 데이터사용량 | `NUMERIC(22, ...)` | 분석 필드 변환 | `measure_data_usage` | `DOUBLE` | `measure_data_usage`: 실수 파싱 후 `DOUBLE`; 단위 `bytes` |
| 40 | `ALL_VCE_PHCL_U...` | 전체음성통화사용량 | `NUMERIC(22, ...)` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 41 | `VCE_PHCL_RCP_...` | 음성통화수신사용량 | `NUMERIC(22, ...)` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 42 | `VCE_PHCL_DSP_...` | 음성통화발신사용량 | `NUMERIC(22, ...)` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 43 | `ALL_VDO_PHCL_U...` | 전체영상통화사용량 | `NUMERIC(22, ...)` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 44 | `VDO_PHCL_RCP_...` | 영상통화수신사용량 | `NUMERIC(22, ...)` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 45 | `VDO_PHCL_DSP...` | 영상통화발신사용량 | `NUMERIC(22, ...)` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 46 | `RMNG_LTTR_CNT` | 로밍문자건수 | `INT64` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |
| 47 | `SVC_ATRC_DEAL...` | 서비스유치대리점코드 | `STRING` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 48 | `SVC_ATRC_DEAL...` | 서비스유치대리점명 | `STRING` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 49 | `SVC_ENTR_OPTR...` | 서비스가입처리자ID | `STRING` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 50 | `LAST_RMNG_PP...` | 최종로밍요금제시... | `STRING` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 51 | `LAST_RMNG_PP...` | 최종로밍요금제코드 | `STRING` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 52 | `LAST_RMNG_PP...` | 최종로밍요금제명 | `STRING` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 53 | `YY1_RMNG_USE...` | 1년로밍사용여부 | `INT64` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 54 | `YY3_RMNG_USE...` | 3년로밍사용여부 | `INT64` | 원안 물리명 잘림 / CSV 미생성 | — | — | 원문 표기 그대로 기록, 전체 물리명 추정 안 함 |
| 55 | `BQ_LOAD_DTTM` | BQ적재일시 | `DATETIME` | 분석 필드 변환 | `occurred_at` | `TIMESTAMP` | `occurred_at`: Asia/Seoul로 해석 후 UTC 변환, timezone 정보 제거 |
| 56 | `BQ_LOAD_USER_ID` | BQ적재사용자ID | `STRING` | CSV만 유지 | — | — | CSV 물리명 유지, Source 매핑 없음 |

## 3. 원안에 없는 분석용 공통 필드와 고정값

### 시스템에서 생성하는 필드

| 필드 | 타입 | 생성 규칙 / 원안과의 차이 |
| --- | --- | --- |
| `source_id` | `VARCHAR` | `spec.json`의 Source ID, 원래 테이블명 대신 `hackathon_*` 사용 |
| `event_id` | `VARCHAR` | `source_id + '-' + SHA256(source_id + ':' + 0부터 시작하는 CSV 행 순번)[:24]`; 원안 `ID`, `RUN_ID`, `CALL_ID` 재사용 없음 |
| `evidence_id` | `VARCHAR` | `ev-` + `event_id` |
| `customer_id` | `VARCHAR` | `customer_` + `SHA256(문자열 canonical_customer_id)[:24]`; 원래 고객키 직접 노출 없음 |

`event_id`는 Source ID와 행 순서에 의존합니다. 같은 행도 CSV 정렬이나 앞쪽 행 삽입으로 순번이 바뀌면 ID가 바뀝니다.
고객 연결에는 Source마다 지정한 `CZ_LNK_KEY` 또는 `CUST_NO`를 사용합니다. 원안의 모든 식별키를 자동으로 조인하는 구조는 아닙니다.
해커톤 Source는 `synthetic_customer` namespace, `exact` 연결 방식, 신뢰도 `1.0`을 선언합니다.

### 원안 필드 대신 넣는 고정값

| Source | 분석 필드 | 고정값 | 타입 |
| --- | --- | --- | --- |
| `hackathon_search_history` | `event_type` | `search` | `VARCHAR` |
| `hackathon_search_feedback` | `event_type` | `feedback` | `VARCHAR` |
| `hackathon_search_feedback` | `action` | `rate_search` | `VARCHAR` |
| `hackathon_voc` | `event_type` | `voc` | `VARCHAR` |
| `hackathon_voc` | `action` | `contact_customer_service` | `VARCHAR` |
| `hackathon_vas_subscription` | `event_type` | `subscription` | `VARCHAR` |
| `hackathon_billing_profile` | `event_type` | `billing_profile` | `VARCHAR` |
| `hackathon_billing_profile` | `action` | `review_profile` | `VARCHAR` |
| `hackathon_roaming_usage` | `event_type` | `roaming_usage_snapshot` | `VARCHAR` |
| `hackathon_roaming_usage` | `action` | `review_roaming_usage` | `VARCHAR` |
| `hackathon_roaming_usage` | `topic` | `해외 로밍 이용` | `VARCHAR` |

### 타입과 값의 공통 변환

| 항목 | 현재 변환 | 영향 |
| --- | --- | --- |
| 시간 | Source의 timestamp 컬럼을 `Asia/Seoul`로 해석한 뒤 UTC로 바꾸고 timezone을 제거하여 `TIMESTAMP` 저장 | 원안의 날짜나 적재시간과 동일한 표현이 아님; `2026-09-04 09:00 KST`는 `2026-09-04 00:00` UTC |
| 앱 행동 시간 | `LOG_DTTM` 대신 `BQ_LOAD_DTTM` → `occurred_at` | 조회 기간과 순서의 기준은 매핑된 적재시간 |
| 검색 시간 | `CREATED_AT` → `occurred_at` | 검색 생성 시각 사용 |
| VOC 시간 | `CALL_CRTE_DTTM` → `occurred_at` | 콜 생성 시각 사용 |
| 피드백, VAS, 로밍 시간 | `BQ_LOAD_DTTM` → `occurred_at` | 적재 시각 사용 |
| 빌링 시간 | `DP_LOAD_DTTM` → `occurred_at` | 적재 시각 사용 |
| 숫자 지표 | integer 또는 number 파싱 후 모두 `DOUBLE` | 원안의 정수 타입이나 `NUMERIC` 정밀도 보존 안 함 |
| 차원 | `dim_*`에 `VARCHAR` 저장 | 날짜 의미의 `dim_departure_date`, `dim_billing_month`도 문자열 |
| 공통 문자열 | `event_type`, `action`, `topic`, `outcome`, `text`는 `VARCHAR` | 원안 필드의 타입, 길이, 허용값 제약 복제 없음 |
| 검색 동작 | `SEARCH_QUERY_TYPE`: `initial` → `search`, `repeat` → `repeat_search` | `action` 값 변환; `dim_query_type`에는 원래 값 유지 |
| 정답을 암시하는 값 필터 | `topic`, `outcome`에서 제외 정규식에 일치하면 `unknown` | 분석 결과에 정답성 라벨이 들어가지 않도록 변환 |
| 차원/지표 노출 | 이름이나 값이 제외 정규식에 일치하면 생략; descriptor의 PII 분류가 `none`이 아니어도 생략 | `ABTEST_ID` → `dimensions.abtest_id` 매핑은 존재하지만 `dim_abtest_id`는 분석 DB에서 제거 |
| 공개 텍스트 정리 | 이메일, 전화번호 패턴을 치환하고 민감 키를 가림 | 분석에 제공되는 텍스트가 입력 문자열과 달라질 수 있음 |
| 원안에서 생략한 필드 | CSV 미생성 | DuckDB 컬럼만 추가해도 원래 값 복원 불가 |
| 매핑하지 않은 CSV 필드 | 공통 이벤트로 복사하지 않음 | 분석용 SQL 조회 불가; Source spec에 별도 매핑 필요 |
| 근거 원문 | 온보딩 Evidence의 `raw_fields`는 `{}` | CSV의 미매핑 필드가 Evidence JSON에 보존된 것으로 해석하면 안 됨 |
| 제약조건 | 분석용 `events`는 컬럼명과 타입만 선언, PK/FK/NOT NULL 미선언 | 원안의 키, 필수값, 파티션 제약을 복제하지 않음 |

제외 정규식은 대소문자를 구분하지 않는 `wandering|unreachable|incomplete|ground.?truth|abtest|treatment|control_group`입니다.
이 필터는 `topic`, `outcome`, 차원과 지표에 적용합니다. 모든 텍스트에서 같은 패턴을 삭제하는 동작은 아닙니다.

CSV의 값은 합성 시나리오용으로 생성합니다. 이 표는 원안 스키마와 매핑의 차이를 설명하며,
제공받지 않은 운영 원본 행과 합성 값의 일대일 변경 여부까지 판정하지 않습니다.
특히 `REWRITE_SEARCH_QUERY`는 현재 합성 데이터에서 업무 주제를 담고 `topic`으로 쓰이므로 운영 재검색 문장과 의미가 같다고 가정하면 안 됩니다.

## 4. 실제 파일 DuckDB의 전체 스키마

아래는 `data/generated/customer_signal.duckdb`를 읽기 전용으로 조회한 결과입니다.
해커톤 분석용 메모리 DuckDB와 구분해야 합니다. 원안 7개 테이블의 물리 테이블은 이 파일에 없습니다.

| 실제 테이블 | 종류 | 행 수 |
| --- | --- | --- |
| `customers` | `BASE TABLE` | 30 |
| `database_metadata` | `BASE TABLE` | 1 |
| `events` | `BASE TABLE` | 199 |
| `evidence` | `BASE TABLE` | 199 |
| `identity_edges` | `BASE TABLE` | 150 |

메타데이터: `schema_version=2`, `dataset_version=2`, `manifest_version=2`입니다.

| 실제 테이블 | 필드명 | 타입 | NULL 허용 | 기본값 |
| --- | --- | --- | --- | --- |
| `customers` | `customer_id` | `VARCHAR` | NO | — |
| `database_metadata` | `schema_version` | `INTEGER` | NO | — |
| `database_metadata` | `dataset_version` | `INTEGER` | NO | — |
| `database_metadata` | `manifest_version` | `VARCHAR` | NO | — |
| `events` | `event_id` | `VARCHAR` | NO | — |
| `events` | `evidence_id` | `VARCHAR` | NO | — |
| `events` | `source_id` | `VARCHAR` | NO | — |
| `events` | `occurred_at` | `TIMESTAMP WITH TIME ZONE` | NO | — |
| `events` | `event_type` | `VARCHAR` | NO | — |
| `events` | `action` | `VARCHAR` | NO | — |
| `events` | `topic` | `VARCHAR` | NO | — |
| `events` | `outcome` | `VARCHAR` | NO | — |
| `events` | `text` | `VARCHAR` | NO | — |
| `events` | `identities` | `JSON` | NO | — |
| `events` | `canonical_customer_id` | `VARCHAR` | NO | — |
| `events` | `attributes` | `JSON` | NO | — |
| `events` | `dimensions` | `JSON` | NO | — |
| `events` | `measures` | `JSON` | NO | — |
| `evidence` | `evidence_id` | `VARCHAR` | NO | — |
| `evidence` | `source_id` | `VARCHAR` | NO | — |
| `evidence` | `occurred_at` | `TIMESTAMP WITH TIME ZONE` | NO | — |
| `evidence` | `masked_customer_id` | `VARCHAR` | NO | — |
| `evidence` | `summary` | `VARCHAR` | NO | — |
| `evidence` | `raw_fields` | `JSON` | NO | — |
| `identity_edges` | `left_namespace` | `VARCHAR` | NO | — |
| `identity_edges` | `left_value` | `VARCHAR` | NO | — |
| `identity_edges` | `right_namespace` | `VARCHAR` | NO | — |
| `identity_edges` | `right_value` | `VARCHAR` | NO | — |
| `identity_edges` | `link_type` | `VARCHAR` | NO | — |
| `identity_edges` | `confidence` | `DOUBLE` | NO | — |
| `identity_edges` | `provenance` | `VARCHAR` | NO | — |

파일 DB의 키 제약은 다음과 같습니다. 위 표의 `NULL 허용`과 함께 현재 DDL을 나타냅니다.

| 테이블 | 제약 | 필드 |
| --- | --- | --- |
| `customers` | `PRIMARY KEY` | `customer_id` |
| `events` | `PRIMARY KEY` | `event_id` |
| `evidence` | `PRIMARY KEY` | `evidence_id` |
| `identity_edges` | `PRIMARY KEY` | `left_namespace`, `left_value`, `right_namespace`, `right_value`, `link_type` |

파일 DB의 `events.source_id`별 행 수는 다음과 같습니다. 이 목록은 기본 데모 Source이며 `hackathon_*` Source와 다릅니다.

| Source | 행 수 |
| --- | --- |
| `digital_behavior` | 30 |
| `search_feedback` | 36 |
| `search_history` | 54 |
| `subscription` | 49 |
| `voc` | 30 |

파일 DB의 `events.dimensions`, `events.measures`는 JSON입니다. 분석용 메모리 DB는 이를 공개 가능한 `dim_*`, `measure_*` 컬럼으로 펼칩니다.
파일 DB의 `identities`, `canonical_customer_id`, `attributes`는 분석용 DB에 같은 이름의 컬럼으로 복사하지 않습니다.
분석용 DB에는 변환된 `customer_id`만 있습니다. 파일 DB의 `events.occurred_at`은 `TIMESTAMP WITH TIME ZONE`, 분석용은 `TIMESTAMP`입니다.

## 5. 해커톤 7개 Source를 함께 읽었을 때의 분석용 스키마

현재 등록 CSV를 기존 adapter와 `InvestigationData` 코드로 읽어 로컬 메모리 DB를 생성하고 `DESCRIBE events`로 확인했습니다.
확인 기간은 `2026-09-04 00:00 KST` 이상, `2026-09-18 00:00 KST` 미만입니다.
실행 중인 Backend에 요청하거나 외부 모델을 호출하지 않았습니다.

검증 이벤트는 15,377건, 분석용 `events` 컬럼은 38개입니다. 이 컬럼 목록은 해당 전체 기간과 7개 Source 조합의 결과입니다.

| Source / 뷰 | 행 수 |
| --- | --- |
| `hackathon_app_behavior` | 9250 |
| `hackathon_billing_profile` | 1550 |
| `hackathon_roaming_usage` | 280 |
| `hackathon_search_feedback` | 339 |
| `hackathon_search_history` | 1540 |
| `hackathon_vas_subscription` | 2070 |
| `hackathon_voc` | 348 |

공통 컬럼 10개를 포함한 실제 컬럼 목록은 다음과 같습니다.

| 분석용 컬럼 | 실제 타입 | 원안 또는 생성 규칙 |
| --- | --- | --- |
| `action` | `VARCHAR` | `hackathon_app_behavior.EVET_ACT_NM`; `hackathon_search_history.SEARCH_QUERY_TYPE`; `hackathon_vas_subscription.SVC_STTS_CD`; `hackathon_billing_profile`: 고정값 `review_profile`; `hackathon_roaming_usage`: 고정값 `review_roaming_usage`; `hackathon_search_feedback`: 고정값 `rate_search`; `hackathon_voc`: 고정값 `contact_customer_service` |
| `customer_id` | `VARCHAR` | `hackathon_app_behavior.CUST_NO`; `hackathon_search_history.CZ_LNK_KEY`; `hackathon_search_feedback.CZ_LNK_KEY`; `hackathon_voc.CZ_LNK_KEY`; `hackathon_vas_subscription.CUST_NO`; `hackathon_billing_profile.CZ_LNK_KEY`; `hackathon_roaming_usage.CUST_NO` |
| `dim_age_band` | `VARCHAR` | `hackathon_billing_profile.YY10_AGELV_ID` |
| `dim_billing_month` | `VARCHAR` | `hackathon_roaming_usage.P_YYYYMM` |
| `dim_country` | `VARCHAR` | `hackathon_roaming_usage.RMNG_NATN_NM` |
| `dim_departure_date` | `VARCHAR` | `hackathon_roaming_usage.DPTR_DT` |
| `dim_menu` | `VARCHAR` | `hackathon_app_behavior.REP_CHNL_MENU_NM` |
| `dim_product_code` | `VARCHAR` | `hackathon_vas_subscription.PROD_CD`; `hackathon_roaming_usage.SPPS_CD` |
| `dim_query_type` | `VARCHAR` | `hackathon_search_history.SEARCH_QUERY_TYPE` |
| `dim_rating_start_date` | `VARCHAR` | `hackathon_roaming_usage.RTNG_STRT_DT` |
| `dim_reason` | `VARCHAR` | `hackathon_search_feedback.REASON` |
| `dim_resolution` | `VARCHAR` | `hackathon_voc.CSLR_PRSS_CNTN` |
| `dim_return_date` | `VARCHAR` | `hackathon_roaming_usage.HMCML_DT` |
| `dim_service_end_date` | `VARCHAR` | `hackathon_roaming_usage.SPPS_END_DT` |
| `dim_service_start_date` | `VARCHAR` | `hackathon_roaming_usage.SPPS_STRT_DT` |
| `dim_session_id` | `VARCHAR` | `hackathon_app_behavior.SESN_ID` |
| `dim_sex` | `VARCHAR` | `hackathon_billing_profile.SEX_DV_CD` |
| `dim_subject` | `VARCHAR` | `hackathon_voc.CNSL_SBJC_TIT_NM` |
| `dim_template` | `VARCHAR` | `hackathon_search_history.SEARCH_RESULT_REFERENCE_TEMPLATE_NAME` |
| `event_id` | `VARCHAR` | 시스템 생성 |
| `event_type` | `VARCHAR` | `hackathon_app_behavior.EVET_NM`; `hackathon_billing_profile`: 고정값 `billing_profile`; `hackathon_roaming_usage`: 고정값 `roaming_usage_snapshot`; `hackathon_search_feedback`: 고정값 `feedback`; `hackathon_search_history`: 고정값 `search`; `hackathon_vas_subscription`: 고정값 `subscription`; `hackathon_voc`: 고정값 `voc` |
| `evidence_id` | `VARCHAR` | 시스템 생성 |
| `measure_abroad_stay_days` | `DOUBLE` | `hackathon_roaming_usage.ABRD_STAY_DAYS` |
| `measure_amount_krw` | `DOUBLE` | `hackathon_vas_subscription.VAT_INCL_ALL_AMT` |
| `measure_consult_seconds` | `DOUBLE` | `hackathon_voc.CUST_CNSL_TM` |
| `measure_data_usage` | `DOUBLE` | `hackathon_roaming_usage.DATA_USAG` |
| `measure_latency_ms` | `DOUBLE` | `hackathon_search_history.FIRST_RESPONSE_LATENCY_MS` |
| `measure_micropayment_amount_krw` | `DOUBLE` | `hackathon_billing_profile.SMLS_STLM_AMT` |
| `measure_page_stay_seconds` | `DOUBLE` | `hackathon_app_behavior.PAGE_STAY_TM` |
| `measure_plan_use_days` | `DOUBLE` | `hackathon_roaming_usage.PP_USE_DAYS` |
| `measure_session_stay_seconds` | `DOUBLE` | `hackathon_app_behavior.SESN_STAY_TM` |
| `measure_subscription_days` | `DOUBLE` | `hackathon_vas_subscription.PROD_ENTR_DAYS` |
| `measure_vas_amount_krw` | `DOUBLE` | `hackathon_billing_profile.SPPS_AMT` |
| `occurred_at` | `TIMESTAMP` | `hackathon_app_behavior.BQ_LOAD_DTTM`; `hackathon_search_history.CREATED_AT`; `hackathon_search_feedback.BQ_LOAD_DTTM`; `hackathon_voc.CALL_CRTE_DTTM`; `hackathon_vas_subscription.BQ_LOAD_DTTM`; `hackathon_billing_profile.DP_LOAD_DTTM`; `hackathon_roaming_usage.BQ_LOAD_DTTM` |
| `outcome` | `VARCHAR` | `hackathon_app_behavior.EVET_ACT_LABE_NM`; `hackathon_search_history.STATUS`; `hackathon_search_feedback.FEEDBACK_TYPE`; `hackathon_voc.CUST_SNMT_NM`; `hackathon_vas_subscription.SRVL_YN`; `hackathon_billing_profile.ENTR_STTS_CD`; `hackathon_roaming_usage.SPPS_ENTR_STUS_CD` |
| `source_id` | `VARCHAR` | 시스템 생성 |
| `text` | `VARCHAR` | `hackathon_app_behavior.REP_CHNL_MENU_NM`; `hackathon_search_history.SEARCH_QUERY`; `hackathon_search_feedback.REASON`; `hackathon_voc.CNSL_ALL_SMRY_CNTN`; `hackathon_vas_subscription.PROD_NM`; `hackathon_billing_profile.PP_NM`; `hackathon_roaming_usage.SPPS_NM` |
| `topic` | `VARCHAR` | `hackathon_app_behavior.EVET_ACT_CATG_NM`; `hackathon_search_history.REWRITE_SEARCH_QUERY`; `hackathon_search_feedback.OPTION`; `hackathon_voc.CNSL_THMA_NM`; `hackathon_vas_subscription.PROD_NM`; `hackathon_billing_profile.PP_NM`; `hackathon_roaming_usage`: 고정값 `해외 로밍 이용` |

## 6. 검증 범위와 근거

- 원안 7개 문서의 454개 필드 항목 전수 포함, 로밍의 잘린 물리명 14개 별도 표시
- 생성 CSV와 등록 CSV의 헤더가 `TABLE_COLUMNS`와 일치하는지 확인
- 등록된 7개 `spec.json`과 현재 exporter의 매핑 선언 일치 확인
- 원안 대비 CSV에 새로 추가되거나 다른 이름으로 생성된 필드가 없는지 확인
- 모든 노출 대상 매핑의 컬럼명과 타입을 로컬 메모리 DuckDB의 실제 스키마와 대조
- `dim_abtest_id`가 실제 분석 스키마에 없는지 확인
- 파일 DuckDB의 전체 컬럼, 타입, NULL 허용, 제약, 테이블 및 Source별 행 수를 읽기 전용으로 조회

| 근거 | 용도 |
| --- | --- |
| [원안 정의 디렉터리](./tables/) | 제공받은 테이블 물리명, 논리명, 타입 |
| [시딩 필드 선언](../../backend/src/customer_signal/seeding/models.py) | 현재 CSV 필드 목록 |
| [시딩 exporter](../../backend/src/customer_signal/seeding/exporter.py) | 테이블명과 Source ID 대응, 공통 이벤트 매핑 |
| [CSV reader](../../backend/src/customer_signal/onboarding/table_pages.py) | 문자열과 빈 값 처리 |
| [온보딩 adapter](../../backend/src/customer_signal/onboarding/adapter.py) | 타입 변환, ID 생성, Evidence 원문 처리 |
| [분석용 DuckDB](../../backend/src/customer_signal/investigation/data.py) | 노출 필터, 고객키 변환, 컬럼 타입과 뷰 생성 |
| [공개 텍스트 정리](../../backend/src/customer_signal/observability/langfuse.py) | `sanitize_trace_value` 처리 |
| [파일 DuckDB DDL](../../backend/src/customer_signal/data/database.py) | 기본 데모 DB 스키마 |
| [API 의존성 연결](../../backend/src/customer_signal/api.py) | 파일 DB Source와 온보딩 Source의 결합 |

이 문서는 2026-09-10 작업 시점의 로컬 코드와 생성 파일을 기준으로 합니다.
Source 매핑이나 시딩 필드를 바꾸면 이 조견표와 동반 CSV도 다시 대조해야 합니다.

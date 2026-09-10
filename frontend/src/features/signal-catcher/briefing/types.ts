/**
 * 브리핑(메인) 화면이 그리는 값.
 * 실제 브리핑 API와 데모 fixture가 함께 채우므로 ReactNode 없이 직렬화되는 값만 둔다.
 */

/** 카드 안 지표 한 줄. */
export interface BriefingMetric {
  label: string;
  value: string;
  /** "5.7%p" 또는 비교 기간이 없을 때 "첫 측정". */
  delta: string;
  direction: "up" | "down" | "flat";
}

export interface BriefingSignal {
  id: string;
  /** 머리말에 붙는 시그널 이름. "로밍 상품 결정 지연" */
  name: string;
  /**
   * 카드 제목. `*로 감싼 구간*`이 마젠타로 칠해진다.
   * 강조를 마크업이 아니라 문자열에 두어야 백엔드가 그대로 실어 보낼 수 있다.
   */
  headline: string;
  body: string;
  metrics: BriefingMetric[];
  /** 스파크라인. 0~1 로 정규화한 값을 시간순으로 넣는다. */
  trend: number[];
  /** "근거 3개 소스 · 로밍 / 상담 / VOC" */
  evidenceNote: string;
  /** 사용자가 걸어 둔 요청으로 잡힌 시그널. 카드에 배지가 붙는다. */
  fromRequest: boolean;
  /** 아래 칩에 쓰는 짧은 이름. */
  chipLabel: string;
}

export interface Briefing {
  /** "9월 8일 화요일" */
  dateLabel: string;
  /** 리드 문장. headline 과 같은 `*강조*` 규칙을 쓴다. */
  lede: string;
  signals: BriefingSignal[];
  /** 이번 브리핑에 반영된 내 요청 수. 0이면 배지를 숨긴다. */
  requestCount: number;
  /** 관찰 중인 실험 수. */
  watchingCount: number;
  /** 지난 브리핑 날짜. "9/7" */
  pastDates: string[];
  /** 지난 브리핑에서 넘긴 시그널 수. */
  backlogCount: number;
  /** 요청 입력창에 깔리는 예시 문구. */
  askPlaceholder: string;
  /** 입력창 아래 제안 버튼. */
  suggestions: string[];
}

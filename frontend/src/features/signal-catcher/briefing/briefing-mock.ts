/**
 * 브리핑 화면 목업. docs/main-screen-ideas.html 의 B 안이 전제한
 * "시그널 2건이 이미 놓여 있는 아침" 상태를 그대로 옮겼다.
 * 실제 브리핑 API 가 붙으면 이 모양만 채워 주면 화면은 그대로 돈다.
 */
import type { Briefing } from "./types";

export const DEMO_BRIEFING: Briefing = {
  dateLabel: "9월 8일 화요일",
  lede: "두 곳에서 고객이 *멈춰 서 있어요.*",
  requestCount: 2,
  watchingCount: 0,
  pastDates: ["9/7", "9/5"],
  backlogCount: 2,
  askPlaceholder: "해지 방어 통화 후 재가입한 고객",
  suggestions: [
    "앱 알림을 끈 뒤 접속이 줄어든 고객",
    "요금제 변경 후 7일 안에 되돌린 고객",
    "상담 뒤에도 같은 문의를 반복한 고객",
  ],
  signals: [
    {
      id: "roaming_decision_delay",
      name: "로밍 상품 결정 지연",
      chipLabel: "로밍 결정 지연",
      headline: "로밍 상품을 *5.2일*씩 보다가 결정하지 못한 고객 *1,284명*",
      body:
        "지난달보다 탐색 기간이 3.1일 길어졌습니다. 요금제 비교 화면을 반복해서 오간 뒤, "
        + "24.3%가 하루 안에 상담으로 넘어갔어요. 결정을 돕는 정보가 화면에서 부족하다는 신호로 보입니다.",
      metrics: [
        { label: "가입 전환율", value: "18.4%", delta: "5.7%p", direction: "down" },
        { label: "평균 탐색 기간", value: "5.2일", delta: "3.1일", direction: "up" },
        { label: "24시간 내 상담 인입", value: "312건", delta: "24.3%", direction: "up" },
      ],
      trend: [0.12, 0.18, 0.32, 0.48, 0.7, 0.92],
      evidenceNote: "근거 3개 소스 · 로밍 / 상담 / VOC",
      fromRequest: false,
    },
    {
      id: "payment_limit_dropoff",
      name: "소액결제 한도 변경 중도 이탈",
      chipLabel: "소액결제 이탈",
      headline: "한도를 바꾸려다 *동의 단계*에서 멈춘 고객 *892명*",
      body:
        "한도 변경을 시도한 고객의 41.7%가 끝내지 못했고, 그중 63.2%가 약관 동의 단계에서 "
        + "이탈했습니다. 평균 2.8번 다시 시도한 뒤 21.0%가 상담으로 유입됐어요.",
      metrics: [
        { label: "시도 후 미완료", value: "41.7%", delta: "12.8%p", direction: "up" },
        { label: "평균 재시도", value: "2.8회", delta: "1.4회", direction: "up" },
        { label: "동의 단계 이탈 비중", value: "63.2%", delta: "9.4%p", direction: "up" },
        { label: "24시간 내 상담 유입", value: "187건", delta: "21.0%", direction: "up" },
      ],
      trend: [0.1, 0.24, 0.2, 0.5, 0.66, 0.88],
      evidenceNote: "근거 2개 소스 · 결제 / 상담",
      fromRequest: true,
    },
  ],
};

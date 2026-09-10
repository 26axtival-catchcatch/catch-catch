"use client";

import { useEffect, useRef, useState } from "react";

import type { CatchReport, RunOutcome } from "../state/types";

import { EvidencePanel } from "./EvidencePanel";
import { JourneyFlow } from "./JourneyFlow";
import { ProcessTrace } from "./ProcessTrace";
import styles from "./result.module.css";

interface ResultScreenProps {
  report: CatchReport;
  outcome: RunOutcome;
  onOpenTrace: () => void;
  onRestart: () => void;
  /** 액션 상세로 이동. 다음 행동 카드가 곧 실험 목록 역할을 한다. */
  onOpenAction: (actionId: string) => void;
  experimentOf: (actionId: string) => { status: string; elapsedDays: number; observeDays: number; hits: number; total: number } | undefined;
  /** 리포트에서 넘어온 다음 액션. 그 카드로 안내한다. */
  highlightActionId: string | null;
  onHighlightSeen: () => void;
  /** 이 분석 이후 적용된 실험. 리포트를 고치지 않고 맥락만 얹는다. */
  applied: { actionId: string; title: string; status: string }[];
}

export function ResultScreen({
  report,
  outcome,
  onOpenTrace,
  onRestart,
  onOpenAction,
  experimentOf,
  highlightActionId,
  onHighlightSeen,
  applied,
}: ResultScreenProps) {
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [limitsOpen, setLimitsOpen] = useState(false);
  const highlightRef = useRef<HTMLLIElement>(null);

  /*
   * 리포트의 "이어지는 액션"에서 넘어오면 결과 화면 어딘가에 떨어져 당황하게 된다.
   * 해당 카드로 데려간 뒤 잠깐 표시해 어디를 보라는지 알린다.
   */
  useEffect(() => {
    if (!highlightActionId) return;
    const timer = setTimeout(() => {
      highlightRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 80);
    const clear = setTimeout(onHighlightSeen, 2600);
    return () => {
      clearTimeout(timer);
      clearTimeout(clear);
    };
  }, [highlightActionId, onHighlightSeen]);

  const degraded = outcome === "degraded";
  // 탈락한 주장은 과정 보기 안쪽 검증 기록에 싣는다. 여기 남는 건 통과한 것뿐이다.
  const findings = report.findings.filter((claim) => claim.verdict === "passed");

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <header className={styles.head}>
          {degraded ? (
            <div className={styles.headTop}>
              <button
                type="button"
                className={styles.degraded}
                onClick={() => setLimitsOpen((prev) => !prev)}
                aria-expanded={limitsOpen}
              >
                부분 캐치
              </button>
            </div>
          ) : null}

          <h1 className={styles.headline}>
            {report.headline}
            <br />
            <em>{report.headlineCount.toLocaleString("ko-KR")}명</em>을 찾았어요
          </h1>
          {report.headlineTrailer ? (
            <p className={styles.trailer}>{report.headlineTrailer}</p>
          ) : null}

          {limitsOpen ? (
            <ul className={styles.limits}>
              {report.limitations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}

          {/* 언제 자른 스냅샷인지. 리포트를 사후에 갱신하지 않으므로 시점을 못 박는다. */}
          <dl className={styles.snapshot} aria-label="스냅샷 정보">
            <div>
              <dt>데이터</dt>
              <dd>{report.periodLabel}</dd>
            </div>
            <div>
              <dt>분석</dt>
              <dd>{report.analyzedAt}</dd>
            </div>
          </dl>

          {/*
            리포트는 사후에 갱신하지 않는다. 갱신하면 "이 결론이 나온 과정"을
            재현할 수 없어진다. 대신 이후에 무슨 일이 있었는지 맥락만 얹는다.
          */}
          {applied.length ? (
            <div className={styles.after} role="status">
              <p>
                이 분석 이후 <strong>{applied[0].title}</strong>를 적용
                {applied[0].status === "done" ? "했어요" : "해 관찰 중이에요"}.
                아래 수치는 <strong>적용 전 시점</strong>의 값입니다.
              </p>
              <button type="button" onClick={() => onOpenAction(applied[0].actionId)}>
                {applied[0].status === "done" ? "실험 결과 보기" : "경과 보기"}
                <span aria-hidden="true"> →</span>
              </button>
            </div>
          ) : null}

          <p className={styles.summary}>{report.summary}</p>

          <dl className={styles.metrics}>
            {report.metrics.map((metric) => {
              const missing = Number.isNaN(metric.value);
              return (
                <div key={metric.metric_key} data-missing={missing}>
                  <dt>{metric.label}</dt>
                  <dd>
                    {missing ? (
                      <span className={styles.metricMissing}>근거 부족</span>
                    ) : (
                      <>
                        {metric.value.toLocaleString("ko-KR")}
                        <small>{metric.unit}</small>
                      </>
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
        </header>

        <section className={styles.block}>
          <h2 className={styles.blockTitle}>고객 여정 맵</h2>
          <p className={styles.blockNote}>
            가장 복잡했던 고객 한 명의 여정을 그대로 폈습니다.
            점을 누르면 그 행동의 원본 근거가 열려요.
          </p>
          <JourneyFlow report={report} onOpenEvidence={setEvidenceId} />
        </section>

        <section className={styles.insight}>
          <div>
            <h2 className={styles.blockTitle}>검증된 발견</h2>
            <ul className={styles.findings}>
              {findings.map((claim) => (
                <li key={claim.claimId}>
                  <p className={styles.findingText}>{claim.statement}</p>
                  <div className={styles.chips}>
                    {claim.evidenceIds.map((id) => (
                      <button key={id} type="button" onClick={() => setEvidenceId(id)}>
                        근거 {id}
                      </button>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h2 className={styles.blockTitle}>다음 행동</h2>
            <ul className={styles.actions}>
              {report.actions.map((item) => (
                <li
                  key={item.actionId}
                  ref={item.actionId === highlightActionId ? highlightRef : undefined}
                  data-highlight={item.actionId === highlightActionId}
                >
                  {(() => {
                    const exp = experimentOf(item.actionId);
                    if (!exp) return null;
                    return (
                      <p className={styles.actionState} data-status={exp.status}>
                        <span>
                          {exp.status === "done"
                            ? `실험 완료 · 예측 ${exp.total}개 중 ${exp.hits}개 적중`
                            : `관찰 중 · ${exp.elapsedDays}일째`}
                        </span>
                        {exp.status === "watching" ? (
                          <i>
                            <b
                              style={{
                                width: `${(exp.elapsedDays / exp.observeDays) * 100}%`,
                              }}
                            />
                          </i>
                        ) : null}
                      </p>
                    );
                  })()}
                  <h4>{item.title}</h4>
                  <p>{item.reason}</p>
                  <div className={styles.actionFoot}>
                    <div className={styles.chips}>
                      {item.evidenceIds.slice(0, 2).map((id) => (
                        <button key={id} type="button" onClick={() => setEvidenceId(id)}>
                          근거 {id}
                        </button>
                      ))}
                    </div>
                    {item.keywords ? (
                      <button
                        type="button"
                        className={styles.primaryBtn}
                        onClick={() => onOpenAction(item.actionId)}
                      >
                        {experimentOf(item.actionId) ? "경과 보기" : "미리보기"}
                      </button>
                    ) : (
                      <span className={styles.actionSoon}>다음 단계</span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* 분석가 모드 대신 이 자리. 로딩 때 흘러간 처리 과정을 그대로 다시 편다. */}
        <ProcessTrace report={report} onOpenTrace={onOpenTrace} />

        <footer className={styles.foot}>
          <button type="button" className={styles.ghostBtn} onClick={onRestart}>
            새로 캐치하기
          </button>
        </footer>
      </div>

      {evidenceId ? (
        <EvidencePanel evidenceId={evidenceId} onClose={() => setEvidenceId(null)} />
      ) : null}
    </div>
  );
}

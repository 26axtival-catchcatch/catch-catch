"use client";

import { useState } from "react";

import { STAGES, observabilityLinks } from "../state/mock";
import { markOf } from "../state/tick-marks";
import type { CatchReport } from "../state/types";

import styles from "./process.module.css";

interface ProcessTraceProps {
  report: CatchReport;
  /** 주장별 근거 계보까지 파고드는 화면. 과정 요약 다음 칸이다. */
  onOpenTrace: () => void;
}

/**
 * 분석 중 흘러간 처리 과정을 결과 화면에서 그대로 다시 펼친다.
 * 로딩 화면은 지나가면 사라지기 때문에, 결론을 의심한 사람이 되돌아올 자리가 필요하다.
 * 기호와 문장을 로딩 때와 똑같이 써서 "아까 그 줄"로 알아볼 수 있게 한다.
 */
export function ProcessTrace({ report, onOpenTrace }: ProcessTraceProps) {
  const [open, setOpen] = useState(false);
  const { score } = report;
  const links = observabilityLinks(report.runId);
  const ticks = STAGES.map((stage) => ({
    stage,
    ticks: report.traceLog.filter((tick) => tick.stage === stage.key),
  }));
  const toolCalls = report.traceLog.filter((item) => item.kind === "tool").length;
  const catches = report.traceLog.filter((item) => item.kind === "fact").length;

  return (
    <section className={styles.wrap}>
      <button
        type="button"
        className={styles.toggle}
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <span className={styles.toggleLabel}>이 결론이 나온 과정 보기</span>
        <span className={styles.toggleMeta}>
          {STAGES.length}단계 · 도구 {toolCalls}회 · 포착 {catches}건 ·{" "}
          {(score.durationMs / 1000).toFixed(1)}초
        </span>
        <span className={styles.chevron} data-open={open} aria-hidden="true">
          ▾
        </span>
      </button>

      {open ? (
        <div className={styles.body}>
          <p className={styles.runId}>
            run_id <code>{report.runId}</code> · dataset {report.datasetVersion}
          </p>

          <ol className={styles.stages}>
            {ticks.map(({ stage, ticks: stageTicks }, index) => (
              <li key={stage.key} className={styles.stage}>
                <div className={styles.stageHead}>
                  <span className={styles.stageNo}>{index + 1}</span>
                  <h4>{stage.label}</h4>
                  <code className={styles.stageEvent}>{stage.event}</code>
                </div>

                <ol className={styles.rail}>
                  {stageTicks.map((tick, tickIndex) => (
                    <li key={`${tick.meta}-${tickIndex}`} className={styles.row} data-kind={tick.kind}>
                      <span className={styles.mark} aria-hidden="true">
                        {markOf(tick)}
                      </span>
                      <div className={styles.rowBody}>
                        {tick.kind === "tool" && tick.primitive ? (
                          <code className={styles.primitive}>{tick.primitive}</code>
                        ) : null}
                        {tick.kind === "fact" && tick.short ? (
                          <span className={styles.caught}>포착 · {tick.short}</span>
                        ) : null}
                        {tick.kind === "reject" ? (
                          <span className={styles.dropped}>근거 부족</span>
                        ) : null}
                        <span className={styles.text}>{tick.text}</span>
                      </div>
                      {tick.kind === "tool" ? (
                        <span className={styles.result}>{tick.meta}</span>
                      ) : null}
                    </li>
                  ))}
                </ol>
              </li>
            ))}
          </ol>

          <h4 className={styles.subTitle}>실행한 분석 스텝</h4>
          <ol className={styles.steps}>
            {report.planSteps.map((step) => (
              <li key={step.stepId}>
                <span className={styles.stepId}>{step.stepId}</span>
                <div>
                  <p className={styles.stepObjective}>{step.objective}</p>
                  <p className={styles.stepMeta}>
                    <code>{step.primitive}</code>
                    <span>{(step.durationMs / 1000).toFixed(1)}초</span>
                  </p>
                  {step.revisedFrom ? (
                    <p className={styles.stepRevised}>계획 수정됨 — {step.revisedFrom}</p>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>

          <div className={styles.links}>
            <button type="button" className={styles.ledgerLink} onClick={onOpenTrace}>
              주장별 근거 계보 보기 <span aria-hidden="true">→</span>
            </button>
            {links.map((link) => (
              <a
                key={link.id}
                className={styles.external}
                href={link.href}
                target="_blank"
                rel="noreferrer"
              >
                <span>{link.label}</span>
                <small>{link.note}</small>
                <span aria-hidden="true" className={styles.arrow}>
                  ↗
                </span>
              </a>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

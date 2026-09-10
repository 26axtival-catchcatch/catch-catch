"use client";

import { useEffect } from "react";

import type { EvidenceRecord, SourceId } from "../../customer-intelligence/contracts";

import { Overlay } from "../Overlay";

import styles from "./result.module.css";

interface EvidencePanelProps {
  evidenceId: string;
  record: EvidenceRecord | null;
  loading: boolean;
  failed: boolean;
  sourceLabels: Record<SourceId, string>;
  onRetry: () => void;
  onClose: () => void;
}

/** Tier 2. 결과 화면을 떠나지 않고 원본 한 건까지 확인한다. */
export function EvidencePanel({
  evidenceId,
  record,
  loading,
  failed,
  sourceLabels,
  onRetry,
  onClose,
}: EvidencePanelProps) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <Overlay>
      <div className={styles.drawerScrim} onMouseDown={onClose} />
      <aside className={styles.drawer} role="dialog" aria-modal="true" aria-label="원본 근거">
        <header className={styles.drawerHead}>
          <div>
            <p className={styles.drawerTag}>원본 근거</p>
            <h3>{evidenceId}</h3>
          </div>
          <button type="button" className={styles.drawerClose} onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </header>

        {loading ? (
          <div className={styles.drawerBody} role="status">
            <p className={styles.drawerSummary}>마스킹된 원본 근거를 불러오고 있어요.</p>
          </div>
        ) : record ? (
          <div className={styles.drawerBody}>
            <p className={styles.drawerSummary}>{record.summary}</p>

            <dl className={styles.drawerMeta}>
              <div>
                <dt>데이터 원천</dt>
                <dd>{sourceLabels[record.source_id] ?? record.source_id}</dd>
              </div>
              <div>
                <dt>발생 시각</dt>
                <dd>{new Date(record.occurred_at).toLocaleString("ko-KR")}</dd>
              </div>
              <div>
                <dt>고객</dt>
                <dd>{record.masked_customer_id}</dd>
              </div>
            </dl>

            <p className={styles.drawerFieldsTitle}>원본 필드</p>
            <table className={styles.drawerFields}>
              <tbody>
                {Object.entries(record.raw_fields).map(([key, value]) => (
                  <tr key={key}>
                    <th scope="row">{key}</th>
                    <td>{value === null ? "—" : String(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <p className={styles.drawerNote}>
              고객 식별자는 마스킹된 값이고, 데이터는 모두 합성입니다.
            </p>
          </div>
        ) : failed ? (
          <div className={styles.drawerBody} role="alert">
            <p className={styles.drawerSummary}>이 근거를 불러오지 못했어요.</p>
            <button type="button" className={styles.ghostBtn} onClick={onRetry}>
              다시 불러오기
            </button>
          </div>
        ) : (
          <div className={styles.drawerBody}>
            <p className={styles.drawerSummary}>이 근거는 아직 불러올 수 없어요.</p>
          </div>
        )}
      </aside>
    </Overlay>
  );
}

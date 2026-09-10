"""Verify real SQL/SQLite/Langfuse wiring with synthetic fixtures, without model calls."""

import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/tests"))
from test_signals import definition, make_data  # noqa: E402

from customer_signal.investigation.contracts import Candidate, Decision
from customer_signal.investigation.data import query_owner
from customer_signal.observability.langfuse import (
    LangfuseRunContext, agent_observation, bind_langfuse_run, flush_langfuse,
    update_langfuse_workflow,
)
from customer_signal.signals.service import SignalService
from customer_signal.signals.store import SignalStore
from customer_signal.signals.workbench import SignalWorkbench

out = Path("data/live-validation/2026-09-10/signals-one-utterance-deterministic")
out.mkdir(parents=True, exist_ok=True)
run_id = str(uuid4())
context = LangfuseRunContext(run_id, "generic", "검증용: 모델 호출 없이 패턴 trace 연결 확인", ("app",))
store = SignalStore(out / "signals.sqlite3")
before_ids = {s.signal_id for s in store.list_signals()}
data = make_data()
wb = SignalWorkbench(data=data, store=store, run_id=run_id)
candidates, decisions = [], []
try:
    with bind_langfuse_run(context):
        with agent_observation(role="investigator", task_id="task-fixture", input={"fixture": True}):
            token = query_owner.set("task-fixture")
            try:
                for action, title in [("close", "검증 패턴 A: 종료 행동"), ("done", "검증 패턴 B: 완료 행동")]:
                    d = definition(cohort_sql=f"SELECT customer_id FROM events WHERE action = '{action}'")
                    measured = wb.measure(d)
                    wb.propose(action, measured["measurement_id"])
                    cohort = data.query(d.cohort_sql)["query_id"]
                    candidates.append(Candidate(
                        candidate_id=action, title=title, intent="합성 패턴 연결 검증",
                        cohort_query_id=cohort, evidence_query_ids=[cohort],
                        representative_customer_ids=data.cohort(cohort),
                        behavior_evidence=f"합성 {action} 행동", normal_comparison="완료 행동과 비교",
                        resolution="합성 관측", recommendation="배선 검증만 수행",
                        limitations=["실제 LLM 분석이 아닌 결정적 합성 검증입니다."],
                    ))
            finally:
                query_owner.reset(token)
        with agent_observation(role="verifier", task_id="task-fixture-verify", input={"fixture": True}):
            token = query_owner.set("task-fixture-verify")
            try:
                for c in candidates:
                    d = wb.proposals[c.candidate_id]
                    wb.measure(d)
                    cohort = data.query(d.cohort_sql)["query_id"]
                    decisions.append(Decision(
                        candidate_id=c.candidate_id,
                        verdict="confirmed" if c.candidate_id == "close" else "candidate",
                        reason="합성 검증의 확정/미확정 분기", cohort_query_id=cohort,
                        evidence_query_ids=[cohort],
                    ))
            finally:
                query_owner.reset(token)
        proposals = wb.persist(candidates, decisions)
        assert len(proposals) == 1
        assert {s.signal_id for s in store.list_signals()} == before_ids
        update_langfuse_workflow(output={"status": "completed", "fixture": True, "model_calls": 0})
    selected = SignalService(store=store, load_data=lambda _: None).register_proposal(proposals[0])
    summary = {"run_id": run_id, "trace_id": context.trace_id, "fixture": True, "model_calls": 0,
               "pattern_count": len(candidates), "proposal_count": len(proposals),
               "pattern_observation_id": proposals[0].observation_id,
               "selected_signal_id": selected.signal_id}
    (out / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))
finally:
    data.close()
    flush_langfuse()

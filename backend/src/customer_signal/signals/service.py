"""User-authorized registration and server-only measurement orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from customer_signal.agent.contracts import RunRequest
from customer_signal.observability.langfuse import (
    LangfuseRunContext,
    bind_langfuse_run,
    bind_langfuse_trace,
    public_observation,
    signal_observation,
)
from customer_signal.signals.contracts import Measurement, Proposal, Signal, SignalDefinition
from customer_signal.signals.measurement import measure_definition, unavailable_measurement
from customer_signal.signals.store import SignalStore
from customer_signal.signals.alerts import AlertStore
from customer_signal.signals.alert_contracts import RecommendationSet
from customer_signal.signals.alert_recommendations import fixture_recommendations


class MeasurementUnavailable(ValueError):
    """A user definition could not be measured; no registration has been saved."""


class SignalService:
    def __init__(
        self, *, store: SignalStore, load_data: Callable,
        recommend: Callable[[Signal, Measurement], RecommendationSet] = fixture_recommendations,
    ):
        self.store = store
        self.load_data = load_data
        self.recommend = recommend

    def ensure_recommendations(
        self, signal: Signal, measurement: Measurement, *, retry: bool = False,
    ) -> Signal:
        signal = self.store.get_signal(signal.signal_id)
        current = signal.alert_recommendations
        if current is not None and (current.status == "ready" or not retry):
            return signal
        with public_observation(
            name="customer_signal.alert_recommendation", stage="alert_recommendation",
            input={"signal_id": signal.signal_id, "measurement_id": measurement.measurement_id},
        ) as observation:
            try:
                recommendations = self.recommend(signal, measurement)
            except Exception:
                recommendations = RecommendationSet(
                    status="unavailable", source="model",
                    reason="추천 조건을 생성하지 못했습니다. 다시 시도할 수 있습니다.",
                )
            updated = AlertStore(self.store).save_recommendations(signal.signal_id, recommendations)
            observation.update(output=updated.alert_recommendations.model_dump(mode="json"))
            return updated

    @staticmethod
    def _trace(
        title: str, definition: SignalDefinition, trace_run_id: str | None = None
    ) -> LangfuseRunContext:
        return LangfuseRunContext(
            run_id=trace_run_id or str(uuid4()),
            run_kind="generic",
            question=title,
            source_ids=tuple(definition.source_ids),
        )

    def _measure(
        self,
        *,
        title: str,
        definition: SignalDefinition,
        start_at: datetime,
        end_at: datetime,
        trace_id: str,
    ) -> Measurement:
        request = RunRequest(
            question=title,
            start_at=start_at,
            end_at=end_at,
            enabled_sources=definition.source_ids,
        )
        data = None
        try:
            data = self.load_data(request)
            result = measure_definition(data, definition)
        except Exception:
            result = unavailable_measurement(
                definition,
                start_at,
                end_at,
                "필수 Source 또는 관측 데이터를 불러오지 못했습니다.",
            )
        finally:
            if data is not None:
                data.close()
        return result.model_copy(update={"trace_id": trace_id})

    def register_proposal(self, proposal: Proposal, *, trace_run_id: str | None = None) -> Signal:
        trace = LangfuseRunContext(
            run_id=proposal.run_id,
            run_kind="generic",
            question=f"시그널 등록: {proposal.title}",
            source_ids=tuple(proposal.definition.source_ids),
            parent_observation_id=proposal.observation_id,
        )
        with (
            bind_langfuse_trace(trace),
            signal_observation(
                operation="registration",
                proposal_id=proposal.proposal_id,
                candidate_id=proposal.candidate_id,
                task_id=proposal.task_id,
                input={
                    "definition": proposal.definition.model_dump(mode="json"),
                    "source_run_id": proposal.run_id,
                    "request_id": trace_run_id,
                },
            ) as observation,
        ):
            signal, persisted = self.store.register_with_measurement(proposal.proposal_id)
            signal = self.ensure_recommendations(signal, persisted)
            observation.update(
                output={
                    "signal_id": signal.signal_id,
                    "measurement_id": persisted.measurement_id,
                    "measurement": persisted.model_dump(mode="json"),
                }
            )
            return signal

    def register_definition(
        self,
        *,
        title: str,
        description: str,
        definition: SignalDefinition,
        start_at: datetime,
        end_at: datetime,
        trace_run_id: str | None = None,
    ) -> Signal:
        trace = self._trace(f"시그널 직접 등록: {title}", definition, trace_run_id)
        with (
            bind_langfuse_run(trace),
            signal_observation(
                operation="direct_registration",
                input={
                    "title": title,
                    "definition": definition.model_dump(mode="json"),
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                },
            ) as observation,
        ):
            measurement = self._measure(
                title=title,
                definition=definition,
                start_at=start_at,
                end_at=end_at,
                trace_id=trace.trace_id,
            )
            if measurement.status != "success":
                observation.update(output={"status": "unavailable", "reason": measurement.reason})
                raise MeasurementUnavailable(measurement.reason)
            signal, persisted = self.store.register_definition_with_measurement(
                title=title,
                description=description,
                definition=definition,
                measurement=measurement,
            )
            signal = self.ensure_recommendations(signal, persisted)
            observation.update(
                output={
                    "signal_id": signal.signal_id,
                    "measurement_id": persisted.measurement_id,
                    "measurement": persisted.model_dump(mode="json"),
                }
            )
            return signal

    def measure(
        self,
        signal: Signal,
        *,
        start_at: datetime,
        end_at: datetime,
        trace_run_id: str | None = None,
        evaluate_alerts: bool = True,
    ) -> Measurement:
        trace = self._trace(f"시그널 재측정: {signal.title}", signal.definition, trace_run_id)
        with (
            bind_langfuse_run(trace),
            signal_observation(
                operation="measurement",
                signal_id=signal.signal_id,
                proposal_id=signal.proposal_id,
                input={
                    "definition": signal.definition.model_dump(mode="json"),
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                },
            ) as signal_span,
            public_observation(
                name="customer_signal.signal_measurement",
                stage="measurement",
                input={
                    "signal_id": signal.signal_id,
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                },
            ) as observation,
        ):
            measurement = self._measure(
                title=signal.title,
                definition=signal.definition,
                start_at=start_at,
                end_at=end_at,
                trace_id=trace.trace_id,
            )
            persisted = self.store.add_measurement(
                signal.signal_id, measurement, evaluate_alerts=evaluate_alerts,
            )
            observation.update(output=persisted.model_dump(mode="json"))
            signal_span.update(
                output={
                    "signal_id": signal.signal_id,
                    "measurement_id": persisted.measurement_id,
                    "measurement": persisted.model_dump(mode="json"),
                }
            )
            return persisted

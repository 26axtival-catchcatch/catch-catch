"""Typed alert APIs; polling reads only durable events and never triggers evaluation."""

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from customer_signal.observability.langfuse import LangfuseRunContext, bind_langfuse_run
from customer_signal.signals.alert_contracts import (
    AlertEvents,
    AlertRules,
    RecommendationSet,
    RuleSelection,
)
from customer_signal.signals.alerts import AlertStore, RuleConflict


class _AlertRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validate_request(request):
            try:
                return await handler(request)
            except RequestValidationError as error:
                # FastAPI echoes invalid input by default. NaN/Infinity cannot be encoded
                # as JSON and would turn an expected 422 into a 500. Expose only schema errors.
                raise HTTPException(
                    422,
                    detail=[
                        {key: item[key] for key in ("loc", "msg", "type")}
                        for item in error.errors()
                    ],
                ) from None

        return validate_request


def create_alert_router(*, service) -> APIRouter:
    router = APIRouter(tags=["signals"], route_class=_AlertRoute)
    store = service.store
    alerts = AlertStore(store)

    def signal_or_404(signal_id):
        try:
            return store.get_signal(signal_id)
        except KeyError:
            raise HTTPException(404, "시그널을 찾을 수 없습니다.") from None

    @router.get(
        "/api/signals/{signal_id}/alert-recommendations",
        summary="시그널의 측정 지표별 알림 기준 조회",
    )
    def recommendations(signal_id: str) -> RecommendationSet | None:
        return signal_or_404(signal_id).alert_recommendations

    @router.post(
        "/api/signals/{signal_id}/alert-recommendations",
        summary="기존 시그널의 측정 지표로 알림 기준 준비",
    )
    def generate(signal_id: str, response: Response) -> RecommendationSet:
        signal = signal_or_404(signal_id)
        if (
            signal.alert_recommendations
            and signal.alert_recommendations.status == "ready"
            and signal.alert_recommendations.source == "measurement"
        ):
            return signal.alert_recommendations
        measurements = [m for m in store.list_measurements(signal_id) if m.status == "success"]
        if not measurements:
            raise HTTPException(409, "알림 기준에 사용할 성공한 측정값이 없습니다.")
        trace = LangfuseRunContext(
            str(uuid4()),
            "generic",
            f"시그널 알림 기준: {signal.title}",
            tuple(signal.definition.source_ids),
        )
        response.headers["X-Langfuse-Trace-Id"] = trace.trace_id
        with bind_langfuse_run(trace):
            result = service.ensure_recommendations(
                signal,
                max(measurements, key=lambda m: (m.end_at, m.measured_at)),
                retry=True,
            )
        return result.alert_recommendations

    @router.get("/api/signals/{signal_id}/alert-rules", summary="사용자가 선택한 알림 조건 조회")
    def rules(signal_id: str) -> AlertRules:
        signal_or_404(signal_id)
        return alerts.get_rules(signal_id)

    @router.put(
        "/api/signals/{signal_id}/alert-rules", summary="시그널 알림 조건 선택 또는 전체 해제"
    )
    def select(signal_id: str, request: RuleSelection) -> AlertRules:
        signal_or_404(signal_id)
        try:
            return alerts.replace_rules(signal_id, request)
        except RuleConflict:
            raise HTTPException(
                409, "알림 설정이 변경되었습니다. 다시 조회한 뒤 저장해야 합니다."
            ) from None
        except ValueError:
            raise HTTPException(
                422, "이 시그널의 알림 기준 ID와 임계값 범위를 확인해야 합니다."
            ) from None

    @router.get("/api/signal-alert-events", summary="커서 이후의 시그널 알림 이벤트 폴링")
    def events(
        after: int | None = Query(
            default=None,
            ge=0,
            le=9007199254740991,
            description="생략하면 현재 커서만 반환, 0이면 전체 이력부터 조회",
        ),
        limit: int = Query(default=100, ge=1, le=500, description="페이지당 최대 이벤트 수"),
    ) -> AlertEvents:
        return alerts.events(after=after, limit=limit)

    return router

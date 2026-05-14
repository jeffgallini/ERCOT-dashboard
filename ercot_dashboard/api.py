from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse

from ercot_dashboard.schemas import (
    DashboardSnapshot,
    DegreeDayForecastResponse,
    EiaNaturalGasResponse,
    ErcotDebugResponse,
    ErcotPublicDashboardsResponse,
    ErcotReportResponse,
    ErcotReportsResponse,
    HealthResponse,
    LoadZoneLmpResponse,
    NoaaSnapshot,
    OperatorEvent,
    OperatorEventCreate,
    OperatorEventDeleteResponse,
    OperatorEventListResponse,
    OperatorEventUpdate,
    ScenarioInput,
    ScenarioPreviewResponse,
    SourceBundle,
    StreamCatalogResponse,
    SupplyDemandResponse,
)
from ercot_dashboard.services.clients import (
    CPC_DEFAULT_REGION,
    ERCOT_PRICE_SETTLEMENT_POINT,
    fetch_cpc_degree_day_forecast,
    fetch_eia_natural_gas,
    fetch_ercot_load_zone_lmps,
    fetch_ercot_report,
    fetch_ercot_snapshot,
    fetch_ercot_public_dashboards,
    fetch_noaa_airport_weather,
    fetch_supply_demand_dashboard,
    get_ercot_debug_status,
    list_ercot_reports,
)
from ercot_dashboard.services.dashboard import (
    get_climate_source_bundle,
    get_dashboard_snapshot,
    get_energy_source_bundle,
    get_ercot_dashboards_source_bundle,
    get_grid_source_bundle,
    get_market_source_bundle,
    get_weather_source_bundle,
)
from ercot_dashboard.services.events import (
    create_operator_event,
    delete_operator_event,
    list_operator_events,
    update_operator_event,
)
from ercot_dashboard.services.scenarios import apply_heatwave_scenario, apply_wind_ramp_scenario, preview_scenarios


def register_api_routes(server: FastAPI) -> None:
    @server.get("/", include_in_schema=False)
    async def index() -> RedirectResponse:
        return RedirectResponse(url="/dash/")

    @server.get(
        "/api/health",
        tags=["Operations"],
        response_model=HealthResponse,
        summary="FastAPI health probe",
    )
    async def health() -> dict[str, str]:
        return {"status": "ok", "backend": "fastapi"}

    @server.get(
        "/api/dashboard",
        tags=["Operations"],
        response_model=DashboardSnapshot,
        summary="Aggregate ERCOT, EIA, NOAA, and scenario-ready metrics",
        description="Runs the request-scope async fanout and returns the normalized dashboard state used by Dash.",
    )
    async def dashboard() -> dict[str, Any]:
        return await get_dashboard_snapshot()

    @server.get(
        "/api/source/grid",
        tags=["Operations", "ERCOT"],
        response_model=SourceBundle,
        summary="Refresh the ERCOT grid source bundle",
    )
    async def grid_source() -> dict[str, Any]:
        return await get_grid_source_bundle()

    @server.get(
        "/api/source/ercot-dashboards",
        tags=["Operations", "ERCOT"],
        response_model=SourceBundle,
        summary="Refresh ERCOT public dashboard replica feeds",
    )
    async def ercot_dashboards_source() -> dict[str, Any]:
        return await get_ercot_dashboards_source_bundle()

    @server.get(
        "/api/source/weather",
        tags=["Operations", "Weather"],
        response_model=SourceBundle,
        summary="Refresh NOAA/NWS airport weather",
    )
    async def weather_source() -> dict[str, Any]:
        return await get_weather_source_bundle()

    @server.get(
        "/api/source/energy",
        tags=["Operations", "EIA"],
        response_model=SourceBundle,
        summary="Refresh EIA electric and natural gas source bundle",
    )
    async def energy_source() -> dict[str, Any]:
        return await get_energy_source_bundle()

    @server.get(
        "/api/source/climate",
        tags=["Operations", "Weather"],
        response_model=SourceBundle,
        summary="Refresh NOAA CPC degree-day outlook",
    )
    async def climate_source() -> dict[str, Any]:
        return await get_climate_source_bundle()

    @server.get(
        "/api/source/market",
        tags=["Operations", "ERCOT Market"],
        response_model=SourceBundle,
        summary="Refresh ERCOT load-zone market prices",
    )
    async def market_source() -> dict[str, Any]:
        return await get_market_source_bundle()

    @server.get(
        "/api/ercot/reports",
        tags=["ERCOT"],
        response_model=ErcotReportsResponse,
        summary="List configured ERCOT Public API reports",
    )
    async def ercot_reports() -> dict[str, Any]:
        return {"reports": list_ercot_reports()}

    @server.get(
        "/api/ercot/debug",
        tags=["ERCOT"],
        response_model=ErcotDebugResponse,
        summary="Inspect ERCOT credentials and optional report reachability",
    )
    async def ercot_debug(check_reports: bool = False) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            return await get_ercot_debug_status(client, check_reports=check_reports)

    @server.get(
        "/api/ercot/report/{report_name}",
        tags=["ERCOT"],
        response_model=ErcotReportResponse,
        summary="Fetch a configured ERCOT report by local report name",
    )
    async def ercot_report(
        report_name: str,
        size: int = Query(default=5, ge=1, le=50),
        start_time: str | None = Query(default=None),
        end_time: str | None = Query(default=None),
        settlement_point: str | None = Query(default=None),
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            try:
                return await fetch_ercot_report(
                    client,
                    report_name,
                    size=size,
                    start_time=start_time,
                    end_time=end_time,
                    settlement_point=settlement_point,
                )
            except ValueError as exc:
                status_code = 404 if str(exc).startswith("Unknown ERCOT report") else 400
                raise HTTPException(status_code=status_code, detail=str(exc)) from exc
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:500] or exc.response.reason_phrase
                raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc

    @server.get(
        "/api/ercot/hb-north-lmp",
        tags=["ERCOT Market"],
        response_model=ErcotReportResponse,
        summary="Fetch North Hub real-time LMP rows",
    )
    @server.get(
        "/api/ercot/rt-lmp",
        tags=["ERCOT Market"],
        response_model=ErcotReportResponse,
        summary="Fetch real-time LMP rows for a settlement point",
    )
    async def hb_north_lmp(
        start_time: str | None = Query(default=None),
        end_time: str | None = Query(default=None),
        settlement_point: str = Query(default=ERCOT_PRICE_SETTLEMENT_POINT),
        size: int = Query(default=288, ge=1, le=1000),
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            try:
                return await fetch_ercot_report(
                    client,
                    "hb-north-lmp",
                    size=size,
                    start_time=start_time,
                    end_time=end_time,
                    settlement_point=settlement_point,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:500] or exc.response.reason_phrase
                raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc

    @server.get(
        "/api/ercot/hb-north-da-lmp",
        tags=["ERCOT Market"],
        response_model=ErcotReportResponse,
        summary="Fetch North Hub day-ahead LMP rows",
    )
    async def hb_north_da_lmp(size: int = Query(default=24, ge=1, le=50)) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            try:
                return await fetch_ercot_report(client, "hb-north-da-lmp", size=size)
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:500] or exc.response.reason_phrase
                raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc

    @server.get(
        "/api/ercot/load-zone-lmps",
        tags=["ERCOT Market"],
        response_model=LoadZoneLmpResponse,
        summary="Fetch latest ERCOT load-zone real-time LMPs",
    )
    async def load_zone_lmps() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            return await fetch_ercot_load_zone_lmps(client)

    @server.get(
        "/api/ercot/supply-demand",
        tags=["ERCOT"],
        response_model=SupplyDemandResponse,
        summary="Fetch ERCOT current-day supply and demand dashboard data",
    )
    async def supply_demand() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await fetch_supply_demand_dashboard(client)

    @server.get(
        "/api/ercot/public-dashboards",
        tags=["ERCOT"],
        response_model=ErcotPublicDashboardsResponse,
        summary="Fetch ERCOT public dashboard replica feeds",
    )
    async def ercot_public_dashboards() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await fetch_ercot_public_dashboards(client)

    @server.get(
        "/api/eia/natural-gas",
        tags=["EIA"],
        response_model=EiaNaturalGasResponse,
        summary="Fetch EIA natural gas storage and STEO outlook",
    )
    async def eia_natural_gas() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await fetch_eia_natural_gas(client)

    @server.get(
        "/api/weather/airports",
        tags=["Weather"],
        response_model=NoaaSnapshot,
        summary="Fetch normalized NOAA/NWS Texas airport observations",
    )
    async def airport_weather() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await fetch_noaa_airport_weather(client)

    @server.get(
        "/api/weather/degree-days",
        tags=["Weather"],
        response_model=DegreeDayForecastResponse,
        summary="Fetch NOAA CPC degree-day forecast for a region",
    )
    async def degree_days(region: str = Query(default=CPC_DEFAULT_REGION, min_length=2, max_length=80)) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await fetch_cpc_degree_day_forecast(client, region=region)

    @server.get(
        "/api/streams",
        tags=["Streams"],
        response_model=StreamCatalogResponse,
        summary="List WebSocket channels used by the dashboard",
        description="Swagger/OpenAPI does not model WebSocket routes directly, so this catalog documents them.",
    )
    async def stream_catalog() -> dict[str, Any]:
        return {
            "channels": [
                {
                    "name": "ercot",
                    "url": "/ws/ercot?interval=30",
                    "source": "ERCOT",
                    "description": "Polls ERCOT reports or the dashboard snapshot and streams normalized JSON.",
                    "query_parameters": {
                        "interval": "Seconds between polls, clamped by server policy.",
                        "report": "Optional configured report name such as hb-north-lmp.",
                        "size": "Optional row count for report streams.",
                    },
                },
                {
                    "name": "weather",
                    "url": "/ws/weather?interval=60",
                    "source": "NOAA/NWS",
                    "description": "Polls current Texas airport observations and streams a normalized weather snapshot.",
                    "query_parameters": {
                        "interval": "Seconds between polls, clamped by server policy.",
                    },
                },
            ]
        }

    @server.get(
        "/api/events",
        tags=["Events"],
        response_model=OperatorEventListResponse,
        summary="List operator-created dashboard events",
        description="Returns in-memory operator events that are also folded into the dashboard event feed.",
    )
    async def events(
        limit: int = Query(default=10, ge=1, le=25),
        include_acknowledged: bool = Query(default=True),
    ) -> dict[str, Any]:
        records = list_operator_events(limit=limit, include_acknowledged=include_acknowledged)
        return {"count": len(records), "events": records}

    @server.post(
        "/api/events",
        tags=["Events"],
        response_model=OperatorEvent,
        status_code=201,
        summary="Create an operator event",
        description="Adds a manual event to the in-memory event store and the next dashboard snapshot.",
    )
    async def create_event(payload: OperatorEventCreate) -> dict[str, Any]:
        return create_operator_event(payload.model_dump(mode="python"))

    @server.put(
        "/api/events/{event_id}",
        tags=["Events"],
        response_model=OperatorEvent,
        summary="Update or acknowledge an operator event",
        description="Updates event text, severity, source, or acknowledgement state in the in-memory store.",
    )
    async def update_event(event_id: str, payload: OperatorEventUpdate) -> dict[str, Any]:
        try:
            return update_operator_event(event_id, payload.model_dump(mode="python", exclude_unset=True))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Operator event '{event_id}' was not found.") from exc

    @server.delete(
        "/api/events/{event_id}",
        tags=["Events"],
        response_model=OperatorEventDeleteResponse,
        summary="Delete an operator event",
        description="Removes a manual event from the in-memory event store and future dashboard snapshots.",
    )
    async def delete_event(event_id: str) -> dict[str, Any]:
        try:
            event = delete_operator_event(event_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Operator event '{event_id}' was not found.") from exc
        return {"deleted": True, "event": event}

    @server.websocket("/ws/ercot")
    async def ercot_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        interval = _stream_interval(
            websocket.query_params.get("interval"),
            env_name="ERCOT_STREAM_INTERVAL_SECONDS",
            default=30,
            minimum=10,
            maximum=900,
        )
        report = websocket.query_params.get("report")
        size = _int_query(websocket.query_params.get("size"), default=5, minimum=1, maximum=50)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
                while True:
                    try:
                        payload = (
                            await fetch_ercot_report(client, report, size=size)
                            if report
                            else await fetch_ercot_snapshot(client)
                        )
                    except Exception as exc:
                        payload = {"error": {"type": type(exc).__name__, "message": str(exc)}}

                    payload["stream"] = {
                        "interval_seconds": interval,
                        "report": report or "dashboard-snapshot",
                        "source": "ercot-rest-polled-by-fastapi-websocket",
                    }
                    await websocket.send_json(payload)
                    await asyncio.sleep(interval)
        except WebSocketDisconnect:
            return

    @server.websocket("/ws/weather")
    async def weather_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        interval = _stream_interval(
            websocket.query_params.get("interval"),
            env_name="NOAA_WEATHER_STREAM_INTERVAL_SECONDS",
            default=60,
            minimum=15,
            maximum=900,
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
                while True:
                    payload = await fetch_noaa_airport_weather(client)
                    payload["stream"] = {"interval_seconds": interval}
                    await websocket.send_json(payload)
                    await asyncio.sleep(interval)
        except WebSocketDisconnect:
            return

    @server.post(
        "/api/scenario/heatwave",
        tags=["Scenarios"],
        response_model=DashboardSnapshot,
        summary="Apply a heatwave demand shock",
    )
    async def heatwave(
        payload: ScenarioInput | None = Body(
            default=None,
            description="Optional current dashboard state. Omit the body to refresh the latest state first.",
        ),
    ) -> dict[str, Any]:
        state = await _scenario_state(payload)
        try:
            return apply_heatwave_scenario(state)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid scenario dashboard state: {exc}") from exc

    @server.post(
        "/api/scenario/wind",
        tags=["Scenarios"],
        response_model=DashboardSnapshot,
        summary="Apply a wind generation ramp scenario",
    )
    async def wind(
        payload: ScenarioInput | None = Body(
            default=None,
            description="Optional current dashboard state. Omit the body to refresh the latest state first.",
        ),
    ) -> dict[str, Any]:
        state = await _scenario_state(payload)
        try:
            return apply_wind_ramp_scenario(state)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid scenario dashboard state: {exc}") from exc

    @server.post(
        "/api/scenario/preview",
        tags=["Scenarios"],
        response_model=ScenarioPreviewResponse,
        summary="Preview base, heatwave, and wind scenarios concurrently",
        description="Uses asyncio.gather to generate scenario cards from a single dashboard state.",
    )
    async def scenario_preview(
        payload: ScenarioInput | None = Body(
            default=None,
            description="Optional current dashboard state. Omit the body to refresh the latest state first.",
        ),
    ) -> dict[str, Any]:
        state = await _scenario_state(payload)
        try:
            return await preview_scenarios(state)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid scenario dashboard state: {exc}") from exc


async def _scenario_state(payload: ScenarioInput | None) -> dict[str, Any]:
    if payload is None:
        return await get_dashboard_snapshot()

    state = payload.model_dump(mode="python")
    missing = [key for key in ("ercot", "noaa", "metrics") if not isinstance(state.get(key), dict)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Scenario payload must be a dashboard snapshot or omitted. Missing sections: {', '.join(missing)}.",
        )
    return state


def _stream_interval(
    value: str | None,
    *,
    env_name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    configured = value or os.getenv(env_name, str(default))
    try:
        seconds = float(configured)
    except ValueError:
        seconds = default
    return max(minimum, min(maximum, seconds))


def _int_query(value: str | None, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        parsed = default
    return max(minimum, min(maximum, parsed))

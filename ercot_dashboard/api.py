from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Path, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse

from ercot_dashboard.schemas import (
    DashboardSnapshot,
    DegreeDayForecastResponse,
    EiaSnapshot,
    EiaNaturalGasResponse,
    ErcotSnapshot,
    ErcotDebugResponse,
    FeedCatalogResponse,
    FeedSnapshotResponse,
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
    SourceBundle,
    StreamCatalogResponse,
    SupplyDemandResponse,
)
from ercot_dashboard.services.clients import (
    CPC_DEFAULT_REGION,
    ERCOT_PRICE_SETTLEMENT_POINT,
    NOAA_AIRPORT_STATIONS,
    fetch_cpc_degree_day_forecast,
    fetch_eia_snapshot,
    fetch_eia_natural_gas,
    fetch_eia_natural_gas_feed,
    fetch_ercot_load_zone_lmps,
    fetch_ercot_report,
    fetch_ercot_public_dashboard_feed,
    fetch_ercot_snapshot,
    fetch_ercot_public_dashboards,
    fetch_ercot_zone_report,
    fetch_noaa_airport_weather,
    fetch_supply_demand_dashboard,
    get_ercot_debug_status,
    list_eia_natural_gas_feeds,
    list_ercot_public_dashboard_feeds,
    list_ercot_reports,
    list_ercot_zone_reports,
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
        "/api/feeds",
        tags=["Operations"],
        response_model=FeedCatalogResponse,
        summary="List individual data-feed endpoints",
        description="Returns the concrete API routes for each normalized external feed the demo can request.",
    )
    async def data_feed_catalog() -> dict[str, Any]:
        return {"feeds": _data_feed_catalog()}

    @server.get(
        "/api/dashboard",
        tags=["Operations"],
        response_model=DashboardSnapshot,
        summary="Aggregate ERCOT, EIA, NOAA, and public dashboard metrics",
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
        "/api/ercot/grid",
        tags=["ERCOT"],
        response_model=ErcotSnapshot,
        summary="Fetch normalized ERCOT grid telemetry",
    )
    async def ercot_grid() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            return await fetch_ercot_snapshot(client)

    @server.get(
        "/api/ercot/system-load",
        tags=["ERCOT"],
        response_model=ErcotReportResponse,
        summary="Fetch ERCOT system load report rows",
    )
    async def ercot_system_load(size: int = Query(default=20, ge=1, le=50)) -> dict[str, Any]:
        return await _fetch_ercot_report_endpoint("system-load", size=size)

    @server.get(
        "/api/ercot/system-generation",
        tags=["ERCOT"],
        response_model=ErcotReportResponse,
        summary="Fetch ERCOT system generation report rows",
    )
    async def ercot_system_generation(size: int = Query(default=20, ge=1, le=50)) -> dict[str, Any]:
        return await _fetch_ercot_report_endpoint("system-generation", size=size)

    @server.get(
        "/api/ercot/wind-5min",
        tags=["ERCOT"],
        response_model=ErcotReportResponse,
        summary="Fetch ERCOT wind actual 5-minute rows",
    )
    async def ercot_wind_5min(size: int = Query(default=20, ge=1, le=50)) -> dict[str, Any]:
        return await _fetch_ercot_report_endpoint("wind-5min", size=size)

    @server.get(
        "/api/ercot/solar-5min",
        tags=["ERCOT"],
        response_model=ErcotReportResponse,
        summary="Fetch ERCOT solar actual 5-minute rows",
    )
    async def ercot_solar_5min(size: int = Query(default=20, ge=1, le=50)) -> dict[str, Any]:
        return await _fetch_ercot_report_endpoint("solar-5min", size=size)

    @server.get(
        "/api/ercot/load-zones/{zone_name}/load",
        tags=["ERCOT"],
        response_model=ErcotReportResponse,
        summary="Fetch an ERCOT load-zone load report",
    )
    async def ercot_load_zone_load(
        zone_name: str = Path(..., min_length=3, max_length=20),
        size: int = Query(default=20, ge=1, le=50),
    ) -> dict[str, Any]:
        return await _fetch_ercot_zone_report_endpoint(zone_name, "load", size=size)

    @server.get(
        "/api/ercot/load-zones/{zone_name}/generation",
        tags=["ERCOT"],
        response_model=ErcotReportResponse,
        summary="Fetch an ERCOT load-zone generation report",
    )
    async def ercot_load_zone_generation(
        zone_name: str = Path(..., min_length=3, max_length=20),
        size: int = Query(default=20, ge=1, le=50),
    ) -> dict[str, Any]:
        return await _fetch_ercot_zone_report_endpoint(zone_name, "generation", size=size)

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
        "/api/ercot/public-dashboards/{feed_name}",
        tags=["ERCOT"],
        response_model=FeedSnapshotResponse,
        summary="Fetch one normalized ERCOT public dashboard feed",
        description="Valid feed names: prc, fuel-mix, storage, combined-renewables, dc-ties, outages, ancillary.",
    )
    async def ercot_public_dashboard_feed(
        feed_name: str = Path(..., min_length=2, max_length=80),
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            try:
                return await fetch_ercot_public_dashboard_feed(client, feed_name)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

    @server.get(
        "/api/eia/fuel-mix",
        tags=["EIA"],
        response_model=EiaSnapshot,
        summary="Fetch EIA ERCOT fuel mix snapshot",
    )
    async def eia_fuel_mix() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await fetch_eia_snapshot(client)

    @server.get(
        "/api/eia/natural-gas",
        tags=["EIA"],
        response_model=EiaNaturalGasResponse,
        summary="Fetch EIA natural gas storage, supply/consumption, and STEO outlook",
    )
    async def eia_natural_gas() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await fetch_eia_natural_gas(client)

    @server.get(
        "/api/eia/natural-gas/{feed_name}",
        tags=["EIA"],
        response_model=FeedSnapshotResponse,
        summary="Fetch one normalized EIA natural-gas feed",
        description="Valid feed names: storage, balance, steo.",
    )
    async def eia_natural_gas_feed(
        feed_name: str = Path(..., min_length=2, max_length=80),
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            try:
                return await fetch_eia_natural_gas_feed(client, feed_name)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

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
        "/api/weather/airports/{airport_code}",
        tags=["Weather"],
        response_model=NoaaSnapshot,
        summary="Fetch normalized NOAA/NWS observation for one Texas airport",
    )
    async def airport_weather_feed(
        airport_code: str = Path(..., min_length=3, max_length=4),
    ) -> dict[str, Any]:
        normalized_code = airport_code.strip().upper()
        if normalized_code not in NOAA_AIRPORT_STATIONS:
            valid = ", ".join(NOAA_AIRPORT_STATIONS)
            raise HTTPException(status_code=404, detail=f"Unknown airport '{airport_code}'. Valid airports: {valid}.")
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await fetch_noaa_airport_weather(client, airport_codes=[normalized_code])

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


async def _fetch_ercot_report_endpoint(
    report_name: str,
    *,
    size: int,
    start_time: str | None = None,
    end_time: str | None = None,
    settlement_point: str | None = None,
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


async def _fetch_ercot_zone_report_endpoint(
    zone_name: str,
    report_kind: str,
    *,
    size: int,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
        try:
            return await fetch_ercot_zone_report(client, zone_name, report_kind, size=size)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] or exc.response.reason_phrase
            raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc


def _data_feed_catalog() -> list[dict[str, Any]]:
    report_aliases = {
        "system-load": "/api/ercot/system-load",
        "system-generation": "/api/ercot/system-generation",
        "wind-5min": "/api/ercot/wind-5min",
        "solar-5min": "/api/ercot/solar-5min",
        "hb-north-lmp": "/api/ercot/hb-north-lmp",
        "hb-north-da-lmp": "/api/ercot/hb-north-da-lmp",
    }
    feeds: list[dict[str, Any]] = [
        {
            "name": "ercot-grid",
            "provider": "ERCOT",
            "title": "Normalized Grid Telemetry",
            "local_url": "/api/ercot/grid",
            "upstream_url": "",
            "description": "Normalized ERCOT load, generation, wind, solar, price, and zone metrics.",
        },
        {
            "name": "ercot-supply-demand",
            "provider": "ERCOT",
            "title": "Supply and Demand Dashboard",
            "local_url": "/api/ercot/supply-demand",
            "upstream_url": "",
            "description": "Current-day and six-day supply/demand dashboard data.",
        },
        {
            "name": "ercot-load-zone-lmps",
            "provider": "ERCOT Market",
            "title": "Load-Zone Real-Time LMPs",
            "local_url": "/api/ercot/load-zone-lmps",
            "upstream_url": "",
            "description": "Latest Houston, North, South, and West load-zone LMPs.",
        },
    ]
    feeds.extend(
        {
            "name": f"ercot-report-{report['name']}",
            "provider": "ERCOT",
            "title": report["title"],
            "local_url": report_aliases.get(report["name"], report["local_url"]),
            "upstream_url": report["ercot_url"],
            "description": "Configured ERCOT Public API report feed.",
        }
        for report in list_ercot_reports()
    )
    feeds.extend(
        {
            "name": f"ercot-zone-{report['name']}",
            "provider": "ERCOT",
            "title": report["title"],
            "local_url": report["local_url"],
            "upstream_url": report["ercot_url"],
            "description": "Configured ERCOT load-zone report feed.",
        }
        for report in list_ercot_zone_reports()
    )
    feeds.extend(
        {
            "name": f"ercot-dashboard-{feed['name']}",
            "provider": "ERCOT",
            "title": feed["title"],
            "local_url": feed["local_url"],
            "upstream_url": feed["source_url"],
            "description": feed["description"],
        }
        for feed in list_ercot_public_dashboard_feeds()
    )
    feeds.append(
        {
            "name": "eia-fuel-mix",
            "provider": "EIA",
            "title": "ERCOT Fuel Mix",
            "local_url": "/api/eia/fuel-mix",
            "upstream_url": "",
            "description": "EIA API v2 ERCOT hourly fuel-type mix.",
        }
    )
    feeds.extend(
        {
            "name": f"eia-natural-gas-{feed['name']}",
            "provider": "EIA",
            "title": feed["title"],
            "local_url": feed["local_url"],
            "upstream_url": feed["source_url"],
            "description": feed["description"],
        }
        for feed in list_eia_natural_gas_feeds()
    )
    feeds.append(
        {
            "name": "noaa-airports",
            "provider": "NOAA/NWS",
            "title": "Texas Airport Observations",
            "local_url": "/api/weather/airports",
            "upstream_url": "",
            "description": "Normalized current observations for configured Texas airport stations.",
        }
    )
    feeds.extend(
        {
            "name": f"noaa-airport-{code.lower()}",
            "provider": "NOAA/NWS",
            "title": f"{station['name']} Observation",
            "local_url": f"/api/weather/airports/{code}",
            "upstream_url": "",
            "description": f"Latest NWS observation for {station['station_id']}.",
        }
        for code, station in NOAA_AIRPORT_STATIONS.items()
    )
    feeds.append(
        {
            "name": "noaa-cpc-degree-days",
            "provider": "NOAA CPC",
            "title": "Degree-Day Forecast",
            "local_url": f"/api/weather/degree-days?region={CPC_DEFAULT_REGION}",
            "upstream_url": "",
            "description": "Monthly heating and cooling degree-day outlook.",
        }
    )
    return feeds


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

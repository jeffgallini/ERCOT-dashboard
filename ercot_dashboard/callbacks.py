from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import time
from typing import Any

from dash import Input, Output, State, callback_context, set_props
import dash
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import httpx

from ercot_dashboard.figures import (
    build_ancillary_chart,
    build_degree_day_chart,
    build_eia_gas_storage_chart,
    build_ercot_fuel_stack,
    build_fuel_mix,
    build_grid_map,
    build_kpi_sparkline,
    build_outages_chart,
    build_prc_chart,
    build_steo_gas_chart,
    build_storage_chart,
    build_system_price_chart,
    build_supply_demand_chart,
)
from ercot_dashboard.layout import kpi_card
from ercot_dashboard.services.dashboard import compose_dashboard_from_source_bundles
from ercot_dashboard.services.scenarios import apply_heatwave_scenario, apply_wind_ramp_scenario


SOURCE_LABELS = {
    "ercot": "ERCOT grid",
    "eia": "EIA fuel",
    "noaa": "NOAA weather",
    "supply_demand": "Supply/Demand",
    "ercot_dashboards": "ERCOT dashboards",
    "eia_gas": "EIA gas",
    "cpc": "CPC climate",
}
MAX_EVENT_LOG_ITEMS = 50


def register_callbacks(app: dash.Dash) -> None:
    @app.callback(
        Output("grid-store", "data"),
        Input("grid-refresh-interval", "n_intervals"),
        Input("refresh-button", "n_clicks"),
        State("grid-store", "data"),
        running=[(Output("refresh-button", "loading"), True, False)],
    )
    async def refresh_grid_source(_: int, __: int | None, current: dict[str, Any] | None) -> dict[str, Any]:
        if _source_backoff_active(current):
            return current or {}
        return await _source_get(app, "/api/source/grid", "grid")

    @app.callback(
        Output("ercot-dashboards-store", "data"),
        Input("ercot-dashboards-refresh-interval", "n_intervals"),
        Input("refresh-button", "n_clicks"),
        State("ercot-dashboards-store", "data"),
    )
    async def refresh_ercot_dashboards_source(
        _: int,
        __: int | None,
        current: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if _source_backoff_active(current):
            return current or {}
        return await _source_get(app, "/api/source/ercot-dashboards", "ercot_dashboards")

    @app.callback(
        Output("weather-store", "data"),
        Input("weather-refresh-interval", "n_intervals"),
        Input("refresh-button", "n_clicks"),
        State("weather-store", "data"),
    )
    async def refresh_weather_source(_: int, __: int | None, current: dict[str, Any] | None) -> dict[str, Any]:
        if _source_backoff_active(current):
            return current or {}
        return await _source_get(app, "/api/source/weather", "weather")

    @app.callback(
        Output("energy-store", "data"),
        Input("energy-refresh-interval", "n_intervals"),
        Input("refresh-button", "n_clicks"),
        State("energy-store", "data"),
    )
    async def refresh_energy_source(_: int, __: int | None, current: dict[str, Any] | None) -> dict[str, Any]:
        if _source_backoff_active(current):
            return current or {}
        return await _source_get(app, "/api/source/energy", "energy")

    @app.callback(
        Output("climate-store", "data"),
        Input("climate-refresh-interval", "n_intervals"),
        Input("refresh-button", "n_clicks"),
        State("climate-store", "data"),
    )
    async def refresh_climate_source(_: int, __: int | None, current: dict[str, Any] | None) -> dict[str, Any]:
        if _source_backoff_active(current):
            return current or {}
        return await _source_get(app, "/api/source/climate", "climate")

    @app.callback(
        Output("dashboard-store", "data"),
        Output("last-update", "children"),
        Output("api-health", "children"),
        Output("api-health", "color"),
        Input("grid-store", "data"),
        Input("ercot-dashboards-store", "data"),
        Input("weather-store", "data"),
        Input("energy-store", "data"),
        Input("climate-store", "data"),
        Input("market-store", "data"),
        Input("scenario-control-store", "data"),
    )
    def compose_dashboard(
        grid: dict[str, Any] | None,
        ercot_dashboards: dict[str, Any] | None,
        weather: dict[str, Any] | None,
        energy: dict[str, Any] | None,
        climate: dict[str, Any] | None,
        market: dict[str, Any] | None,
        scenario_command: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], str, str, str]:
        snapshot = compose_dashboard_from_source_bundles(
            grid=grid,
            ercot_dashboards=ercot_dashboards,
            weather=weather,
            energy=energy,
            climate=climate,
            market=market,
        )
        snapshot = _apply_scenario_command(snapshot, scenario_command)
        loaded_count = sum(bundle is not None for bundle in (grid, ercot_dashboards, weather, energy, climate, market))
        health_color = "green" if loaded_count == 6 else "yellow"
        return snapshot, _format_timestamp(snapshot["timestamp"]), f"{loaded_count}/6 sources", health_color

    @app.callback(
        Output("scenario-control-store", "data"),
        Input("heatwave-button", "n_clicks"),
        Input("wind-button", "n_clicks"),
        Input("refresh-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def select_scenario(
        heatwave_clicks: int | None,
        wind_clicks: int | None,
        refresh_clicks: int | None,
    ) -> dict[str, Any]:
        trigger = callback_context.triggered_id
        if trigger == "heatwave-button":
            return {"kind": "heatwave", "selected_at": datetime.now(timezone.utc).isoformat()}
        if trigger == "wind-button":
            return {"kind": "wind", "selected_at": datetime.now(timezone.utc).isoformat()}
        if trigger == "refresh-button":
            return {}
        return dash.no_update

    @app.callback(
        Output("scenario-preview-store", "data"),
        Input("dashboard-store", "data"),
        websocket=True,
    )
    async def refresh_scenario_preview(snapshot: dict[str, Any] | None) -> dict[str, Any]:
        if not snapshot:
            return {"timestamp": "", "strategy": "asyncio.gather", "cards": []}
        return await _api_post(app, "/api/scenario/preview", snapshot)

    @app.callback(
        Output("scenario-preview-grid", "children"),
        Input("scenario-preview-store", "data"),
    )
    def render_scenario_preview(preview: dict[str, Any] | None) -> dmc.SimpleGrid:
        return _scenario_preview_grid(preview)

    @app.callback(
        Output("active-scenario-impact", "children"),
        Input("dashboard-store", "data"),
    )
    def render_active_scenario(snapshot: dict[str, Any] | None) -> dmc.Box:
        return _active_scenario_panel(snapshot)

    @app.callback(
        Output("market-store", "data"),
        Output("map-price-store", "data"),
        Output("map-price-retry-interval", "disabled"),
        Input("map-price-retry-interval", "n_intervals"),
        Input("refresh-button", "n_clicks"),
        State("map-price-store", "data"),
        State("market-store", "data"),
    )
    async def refresh_map_prices(
        _retry_count: int,
        _refresh_clicks: int | None,
        current_prices: dict[str, Any] | None,
        current_market: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        if _map_prices_complete(current_prices) and callback_context.triggered_id != "refresh-button":
            market = _market_bundle_from_prices(current_prices or {})
            return market, current_prices or {}, True

        if _source_backoff_active(current_market):
            return current_market or _market_bundle_from_prices(current_prices or {}), current_prices or {}, False

        try:
            market = await _source_get(app, "/api/source/market", "market")
            prices = (market.get("data") or {}).get("load_zone_lmps") or {}
        except Exception as exc:
            prices = {
                "timestamp": datetime.utcnow().isoformat(),
                "complete": False,
                "status": {
                    "source": "ERCOT Load Zone RT LMP",
                    "state": "unavailable",
                    "message": str(exc),
                },
                "zones": [],
            }
            market = _market_bundle_from_prices(prices)
        return market, prices, _map_prices_complete(prices)

    @app.callback(
        Output("ws-transport-mode", "children"),
        Output("ws-transport-mode", "color"),
        Output("fanout-latency-total", "children"),
        Output("callback-transport-meta", "children"),
        Output("fanout-latency-grid", "children"),
        Input("telemetry-interval", "n_intervals"),
        State("dashboard-store", "data"),
        websocket=True,
    )
    async def update_transport_panel(
        _heartbeat: int,
        snapshot: dict[str, Any] | None,
    ) -> tuple[str, str, str, str, list[dmc.Box] | list[dmc.Skeleton]]:
        started = time.perf_counter()
        set_props("ws-side-update-status", {"children": "WS active", "color": "cyan"})
        await asyncio.sleep(0)

        callback_ms = round((time.perf_counter() - started) * 1000, 1)
        if not snapshot:
            set_props("ws-side-update-status", {"children": "Waiting", "color": "gray"})
            return "WebSocket", "gray", "Waiting", f"{callback_ms:.1f} ms", _latency_placeholders()

        fanout = snapshot.get("fanout", {})
        latency_ms = fanout.get("source_latency_ms") or {}
        fanout_ms = float(fanout.get("duration_ms") or 0)
        set_props("ws-side-update-status", {"children": "Side update OK", "color": "green"})
        return (
            "WebSocket",
            "green",
            f"{fanout_ms:,.0f} ms",
            f"{callback_ms:.1f} ms",
            _latency_rows(latency_ms),
        )

    @app.callback(
        Output("async-benefit-card", "children"),
        Input("dashboard-store", "data"),
    )
    def update_async_benefit(snapshot: dict[str, Any] | None) -> dmc.Stack:
        return _async_benefit_card(snapshot)

    @app.callback(
        Output("kpi-row", "children"),
        Output("system-status", "children"),
        Output("system-status", "color"),
        Input("dashboard-store", "data"),
    )
    def update_kpis(snapshot: dict[str, Any] | None) -> tuple[dmc.Grid, str, str]:
        if not snapshot:
            return _placeholder_kpis(), "Waiting for data", "gray"

        ercot = snapshot["ercot"]
        metrics = snapshot["metrics"]
        status = snapshot["system_status"]
        status_color = _status_color(status)
        load_utilization = _clamp((ercot["load_mw"] / max(ercot["generation_mw"], 1)) * 100)
        renewable_share = _clamp(metrics["renewable_share_pct"])
        solar_share = _clamp((ercot["solar_mw"] / max(ercot["wind_mw"] + ercot["solar_mw"], 1)) * 100)
        net_load_mw = float(ercot["load_mw"]) - float(ercot["wind_mw"]) - float(ercot["solar_mw"])
        net_load_share = _clamp((net_load_mw / max(float(ercot["load_mw"]), 1)) * 100)
        price_proxy = ercot.get("price_proxy")
        price_state = (ercot.get("price_status") or ercot.get("status", {})).get("state")
        price_available = isinstance(price_proxy, int | float) and price_state not in {"demo", "unavailable"}
        kpi_span = {"base": 12, "sm": 6, "lg": 4, "xl": 2}
        cards = dmc.Grid(
            [
                dmc.GridCol(
                    kpi_card(
                        title="ERCOT Load",
                        value=f"{ercot['load_mw']:,.0f} MW",
                        subtitle=f"Balance {metrics['balance_mw']:,.0f} MW",
                        color="cyan",
                        icon="tabler:bolt",
                        progress=load_utilization,
                        signal=f"{load_utilization:.0f}% served",
                        sparkline=build_kpi_sparkline(_trend(snapshot, "load_mw"), color="cyan"),
                    ),
                    span=kpi_span,
                ),
                dmc.GridCol(
                    kpi_card(
                        title=ercot.get("price_label") or f"{ercot.get('price_settlement_point', 'HB_NORTH')} LMP",
                        value=f"${price_proxy:.2f}" if price_available else "N/A",
                        subtitle="ERCOT hub price" if price_available else "Price API unavailable",
                        color="yellow",
                        icon="tabler:currency-dollar",
                        progress=_clamp((float(price_proxy) / 120) * 100) if price_available else 0,
                        signal="Market proxy" if price_available else "No live price",
                        sparkline=build_kpi_sparkline(
                            _trend(snapshot, "price_proxy") if price_available else [],
                            color="yellow",
                        ),
                    ),
                    span=kpi_span,
                ),
                dmc.GridCol(
                    kpi_card(
                        title="Wind",
                        value=f"{ercot['wind_mw']:,.0f} MW",
                        subtitle=f"{metrics['renewable_share_pct']:.1f}% renewable share",
                        color="green",
                        icon="tabler:wind",
                        progress=renewable_share,
                        signal="Renewable stack",
                        sparkline=build_kpi_sparkline(_trend(snapshot, "wind_mw"), color="green"),
                    ),
                    span=kpi_span,
                ),
                dmc.GridCol(
                    kpi_card(
                        title="Solar",
                        value=f"{ercot['solar_mw']:,.0f} MW",
                        subtitle=f"{snapshot['noaa']['temperature_f']:.1f} F current weather",
                        color="orange",
                        icon="tabler:sun-electricity",
                        progress=solar_share,
                        signal=f"{solar_share:.0f}% of renewables",
                        sparkline=build_kpi_sparkline(_trend(snapshot, "solar_mw"), color="orange"),
                    ),
                    span=kpi_span,
                ),
                dmc.GridCol(
                    kpi_card(
                        title="Net Load",
                        value=f"{net_load_mw:,.0f} MW",
                        subtitle="Load minus wind and solar",
                        color="violet",
                        icon="tabler:chart-arrows-vertical",
                        progress=net_load_share,
                        signal=f"{net_load_share:.0f}% after renewables",
                        sparkline=build_kpi_sparkline(_trend(snapshot, "net_load_mw"), color="violet"),
                    ),
                    span=kpi_span,
                ),
                dmc.GridCol(
                    kpi_card(
                        title="Stress Index",
                        value=f"{metrics['stress_index']:.1f}",
                        subtitle=status,
                        color=status_color,
                        icon="tabler:alert-triangle",
                        progress=_clamp(metrics["stress_index"]),
                        signal="Composite index",
                        sparkline=build_kpi_sparkline(_trend(snapshot, "stress_index"), color=status_color),
                    ),
                    span=kpi_span,
                ),
            ],
            gutter="md",
        )
        return cards, status, status_color

    @app.callback(
        Output("supply-demand-chart", "figure"),
        Output("supply-demand-caption", "children"),
        Input("dashboard-store", "data"),
    )
    def update_supply_demand(snapshot: dict[str, Any] | None):
        caption = ""
        if snapshot:
            supply = snapshot.get("supply_demand", {})
            summary = supply.get("summary", {})
            last_updated = _format_supply_timestamp(supply.get("last_updated", ""))
            caption = (
                f"{last_updated} | Peak {summary.get('peak_demand_mw', 0):,.0f} MW | "
                f"Min margin {summary.get('minimum_margin_pct', 0):.1f}%"
            )
        return build_supply_demand_chart(snapshot), caption

    @app.callback(
        Output("prc-chart", "figure"),
        Output("system-price-chart", "figure"),
        Output("ercot-fuel-stack", "figure"),
        Output("storage-chart", "figure"),
        Output("outages-chart", "figure"),
        Output("ancillary-chart", "figure"),
        Output("eia-gas-storage-chart", "figure"),
        Output("steo-gas-chart", "figure"),
        Output("degree-day-chart", "figure"),
        Input("dashboard-store", "data"),
    )
    def update_dashboard_replica(snapshot: dict[str, Any] | None):
        return (
            build_prc_chart(snapshot),
            build_system_price_chart(snapshot),
            build_ercot_fuel_stack(snapshot),
            build_storage_chart(snapshot),
            build_outages_chart(snapshot),
            build_ancillary_chart(snapshot),
            build_eia_gas_storage_chart(snapshot),
            build_steo_gas_chart(snapshot),
            build_degree_day_chart(snapshot),
        )

    @app.callback(
        Output("grid-map", "figure"),
        Output("map-caption", "children"),
        Output("map-price-loader", "visible"),
        Input("dashboard-store", "data"),
        Input("map-price-store", "data"),
    )
    def update_map(snapshot: dict[str, Any] | None, map_prices: dict[str, Any] | None):
        caption = ""
        if snapshot:
            caption = f"{snapshot['noaa']['station']} | {snapshot['noaa']['wind_speed_mph']} mph wind"
        price_caption = _map_price_caption(map_prices)
        if price_caption:
            caption = f"{caption} | {price_caption}" if caption else price_caption
        return build_grid_map(_with_map_prices(snapshot, map_prices)), caption, not _map_prices_complete(map_prices)

    @app.callback(
        Output("fuel-mix", "figure"),
        Output("fuel-period", "children"),
        Input("dashboard-store", "data"),
    )
    def update_fuel_mix(snapshot: dict[str, Any] | None):
        period = snapshot["eia"]["latest_period"] if snapshot else ""
        return build_fuel_mix(snapshot), period

    @app.callback(
        Output("system-overview", "children"),
        Output("source-status-grid", "children"),
        Input("dashboard-store", "data"),
    )
    def update_system_overview(snapshot: dict[str, Any] | None):
        if not snapshot:
            return _system_overview_placeholder(), _source_status_placeholders()

        ercot = snapshot["ercot"]
        metrics = snapshot["metrics"]
        noaa = snapshot["noaa"]
        status = snapshot["system_status"]
        stress = _clamp(metrics["stress_index"])
        reserve = float(ercot["reserve_margin_pct"])
        reserve_score = _clamp(reserve * 5)
        renewable_share = _clamp(metrics["renewable_share_pct"])
        weather_pressure = _clamp(max(0, float(noaa["temperature_f"]) - 70) * 3.2)
        status_color = _status_color(status)

        overview = dmc.SimpleGrid(
            [
                dmc.Box(
                    [
                        dmc.RingProgress(
                            sections=[{"value": stress, "color": status_color}],
                            size=156,
                            thickness=13,
                            roundCaps=True,
                            rootColor="dark.6",
                            label=dmc.Center(
                                dmc.Stack(
                                    [
                                        dmc.Text(f"{stress:.0f}", className="ring-value"),
                                        dmc.Text("Stress", size="xs", c="dimmed"),
                                    ],
                                    gap=0,
                                    align="center",
                                )
                            ),
                        ),
                        dmc.Stack(
                            [
                                dmc.Text(status, fw=800, className="system-posture"),
                                dmc.Text(
                                    f"{ercot['generation_mw']:,.0f} MW generation against {ercot['load_mw']:,.0f} MW load",
                                    size="sm",
                                    c="dimmed",
                                ),
                            ],
                            gap=2,
                        ),
                    ],
                    className="ring-panel",
                ),
                dmc.Stack(
                    [
                        _metric_bar("Reserve margin", f"{reserve:.1f}%", reserve_score, _reserve_color(reserve)),
                        _metric_bar("Renewable share", f"{renewable_share:.1f}%", renewable_share, "green"),
                        _metric_bar("Weather pressure", f"{noaa['temperature_f']:.1f} F", weather_pressure, "orange"),
                    ],
                    gap="sm",
                    className="signal-bars",
                ),
                dmc.Stack(
                    [
                        _fact_tile("Net balance", f"{metrics['balance_mw']:,.0f} MW", "tabler:arrows-exchange-2", "cyan"),
                        _fact_tile("Wind speed", f"{noaa['wind_speed_mph']:.1f} mph", "tabler:wind", "green"),
                        _fact_tile("Weather nodes", f"{noaa.get('airport_count', 1)} stations", "tabler:cloud-data-connection", "violet"),
                    ],
                    gap="sm",
                    className="fact-stack",
                ),
            ],
            cols={"base": 1, "md": 3},
            spacing="md",
        )

        groups = snapshot.get("source_groups") or {}
        if groups:
            sources = [
                _source_group_tile("Grid", groups.get("grid"), "tabler:bolt", "cyan"),
                _source_group_tile("ERCOT Dashboards", groups.get("ercot_dashboards"), "tabler:layout-dashboard", "cyan"),
                _source_group_tile("Weather", groups.get("weather"), "tabler:cloud", "green"),
                _source_group_tile("Energy", groups.get("energy"), "tabler:database", "violet"),
                _source_group_tile("Climate", groups.get("climate"), "tabler:temperature", "green"),
                _source_group_tile("Market", groups.get("market"), "tabler:currency-dollar", "yellow"),
            ]
        else:
            sources = [
                _source_status_tile("ERCOT", snapshot["source_status"]["ercot"], "tabler:bolt", "cyan"),
                _source_status_tile(
                    "ERCOT Dashboards",
                    snapshot["source_status"]["ercot_dashboards"],
                    "tabler:layout-dashboard",
                    "cyan",
                ),
                _source_status_tile("EIA", snapshot["source_status"]["eia"], "tabler:database", "violet"),
                _source_status_tile("EIA Gas", snapshot["source_status"]["eia_gas"], "tabler:flame", "orange"),
                _source_status_tile("NOAA", snapshot["source_status"]["noaa"], "tabler:cloud", "green"),
                _source_status_tile("CPC", snapshot["source_status"]["cpc"], "tabler:temperature", "green"),
            ]
        return overview, sources

    @app.callback(
        Output("event-log-store", "data"),
        Input("dashboard-store", "data"),
        Input("map-price-store", "data"),
        State("event-log-store", "data"),
        websocket=True,
    )
    async def update_event_log(
        snapshot: dict[str, Any] | None,
        map_prices: dict[str, Any] | None,
        current_log: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        await asyncio.sleep(0)
        incoming = [
            *_snapshot_event_records(snapshot),
            *_map_price_event_records(map_prices),
        ]
        return _merge_event_log(current_log or [], incoming)

    @app.callback(
        Output("event-feed", "children"),
        Output("event-feed-count", "children"),
        Output("event-feed-count", "color"),
        Input("event-log-store", "data"),
    )
    def update_event_feed(event_log: list[dict[str, Any]] | None) -> tuple[dmc.Stack, str, str]:
        if not event_log:
            skeletons = dmc.Stack([dmc.Skeleton(h=48), dmc.Skeleton(h=48), dmc.Skeleton(h=48)], gap="xs")
            return skeletons, "0 events", "gray"

        events = [_event_card(event) for event in event_log[:30]]
        return dmc.Stack(events, gap="xs"), f"{len(event_log)} events", _event_feed_count_color(event_log)


def _snapshot_event_records(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not snapshot:
        return []

    records = [
        _event_record(
            level=str(event.get("level") or "info"),
            title=str(event.get("title") or "System event"),
            message=str(event.get("message") or ""),
            source=str(event.get("source") or "Dashboard"),
            event_time=str(event.get("time") or _event_time()),
        )
        for event in snapshot.get("events", [])
        if isinstance(event, dict)
    ]

    for name, status in (snapshot.get("source_status") or {}).items():
        if not isinstance(status, dict):
            continue
        state = str(status.get("state") or "unknown")
        if state == "live":
            continue
        records.append(
            _event_record(
                level="warning" if state in {"demo", "partial", "stale"} else "danger",
                title=f"{SOURCE_LABELS.get(name, name.replace('_', ' ').title())} source {state.title()}",
                message=str(status.get("message") or "Source did not return a live response."),
                source=str(status.get("source") or name),
                event_time=_event_time(),
            )
        )
    return records


def _map_price_event_records(map_prices: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not map_prices:
        return []

    status = map_prices.get("status") or {}
    records = []
    for zone in map_prices.get("zones") or []:
        if not isinstance(zone, dict):
            continue
        zone_status = str(zone.get("status") or "unknown")
        if zone_status == "live":
            continue
        diagnostic = zone.get("diagnostic") if isinstance(zone.get("diagnostic"), dict) else {}
        records.append(
            _event_record(
                level="warning" if zone_status == "stale" else "danger",
                title=f"{zone.get('settlement_point', zone.get('name', 'Load zone'))} RT LMP {zone_status.title()}",
                message=str(diagnostic.get("message") or status.get("message") or "No load-zone price row was returned."),
                source="ERCOT Load Zone RT LMP",
                event_time=_event_time_from_iso(str(map_prices.get("timestamp") or "")),
            )
        )

    if not records and status.get("state") == "live":
        records.append(
            _event_record(
                level="success",
                title="Load-zone LMPs live",
                message="Houston, North, South, and West load-zone RT LMP rows are available.",
                source="ERCOT Load Zone RT LMP",
                event_time=_event_time_from_iso(str(map_prices.get("timestamp") or "")),
            )
        )
    return records


def _merge_event_log(
    current_log: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key = {
        str(event.get("key")): dict(event)
        for event in current_log
        if isinstance(event, dict) and event.get("key")
    }
    ordered_keys = [str(event.get("key")) for event in current_log if isinstance(event, dict) and event.get("key")]

    for event in incoming:
        key = str(event["key"])
        if key in by_key:
            updated = dict(by_key[key])
            updated["time"] = event["time"]
            updated["count"] = int(updated.get("count") or 1) + 1
            updated["last_seen"] = event["time"]
            by_key[key] = updated
            if key in ordered_keys:
                ordered_keys.remove(key)
        else:
            by_key[key] = event
        ordered_keys.insert(0, key)

    deduped_keys = []
    for key in ordered_keys:
        if key not in deduped_keys:
            deduped_keys.append(key)
    return [by_key[key] for key in deduped_keys[:MAX_EVENT_LOG_ITEMS]]


def _event_record(
    *,
    level: str,
    title: str,
    message: str,
    source: str,
    event_time: str,
) -> dict[str, Any]:
    normalized_level = level if level in {"danger", "warning", "success", "info"} else "info"
    key = "|".join([source, normalized_level, title, message])
    return {
        "key": key,
        "time": event_time,
        "first_seen": event_time,
        "last_seen": event_time,
        "level": normalized_level,
        "title": title,
        "message": message,
        "source": source,
        "count": 1,
    }


def _event_card(event: dict[str, Any]) -> dmc.Box:
    count = int(event.get("count") or 1)
    badges = [
        dmc.Badge(str(event.get("time") or ""), color=_event_color(str(event.get("level") or "info")), variant="light"),
        dmc.Badge(str(event.get("source") or "System"), color="gray", variant="outline"),
    ]
    if count > 1:
        badges.append(dmc.Badge(f"x{count}", color="cyan", variant="light"))

    return dmc.Box(
        [
            dmc.Group(
                [
                    dmc.Group(badges, gap=6, wrap="wrap"),
                    dmc.Text(str(event.get("title") or "System event"), fw=700, size="sm"),
                ],
                gap="xs",
                align="flex-start",
            ),
            dmc.Text(str(event.get("message") or ""), size="sm", c="dimmed", mt=4, lineClamp=2),
        ],
        className="event-card",
    )


def _event_feed_count_color(event_log: list[dict[str, Any]]) -> str:
    levels = {str(event.get("level") or "") for event in event_log}
    if "danger" in levels:
        return "red"
    if "warning" in levels:
        return "yellow"
    return "green"


def _event_time_from_iso(value: str) -> str:
    if not value:
        return _event_time()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return _event_time()
    return parsed.astimezone(timezone.utc).strftime("%H:%M:%S UTC")


def _event_time() -> str:
    return datetime.utcnow().strftime("%H:%M:%S UTC")


async def _api_get(app: dash.Dash, path: str) -> dict[str, Any]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.server),
        base_url="http://dash-fastapi",
        timeout=10,
    ) as client:
        response = await client.get(path)
        response.raise_for_status()
        return response.json()


def _apply_scenario_command(
    snapshot: dict[str, Any],
    command: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(command, dict):
        return snapshot

    scenario_kind = command.get("kind")
    try:
        if scenario_kind == "heatwave":
            return apply_heatwave_scenario(snapshot)
        if scenario_kind == "wind":
            return apply_wind_ramp_scenario(snapshot)
    except Exception as exc:
        event = _event_record(
            level="danger",
            title="Scenario error",
            message=f"{type(exc).__name__}: {exc}",
            source="Scenarios",
            event_time=_event_time(),
        )
        fallback = dict(snapshot)
        fallback["events"] = [event, *fallback.get("events", [])]
        return fallback
    return snapshot


async def _api_post(app: dash.Dash, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.server),
        base_url="http://dash-fastapi",
        timeout=10,
    ) as client:
        response = await client.post(path, json=payload)
        response.raise_for_status()
        return response.json()


async def _source_get(app: dash.Dash, path: str, source_name: str) -> dict[str, Any]:
    try:
        return await _api_get(app, path)
    except Exception as exc:
        return _source_error_bundle(source_name, exc)


def _source_error_bundle(source_name: str, exc: Exception) -> dict[str, Any]:
    message = f"{type(exc).__name__}: {exc}"
    status = {
        "source": source_name.replace("_", " ").title(),
        "state": "unavailable",
        "message": message,
    }
    return {
        "name": source_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_ms": 0.0,
        "latency_ms": {},
        "source_count": 0,
        "status": status,
        "refresh_policy": _refresh_policy_for_status(status),
        "data": {},
    }


def _market_bundle_from_prices(prices: dict[str, Any]) -> dict[str, Any]:
    status = prices.get("status") if isinstance(prices.get("status"), dict) else None
    if status is None:
        status = {
            "source": "ERCOT Load Zone RT LMP",
            "state": "live" if _map_prices_complete(prices) else "partial",
            "message": "",
        }
    return {
        "name": "market",
        "timestamp": str(prices.get("timestamp") or datetime.now(timezone.utc).isoformat()),
        "duration_ms": 0.0,
        "latency_ms": {"load_zone_lmps": 0.0},
        "source_count": 1,
        "status": status,
        "refresh_policy": _refresh_policy_for_status(status),
        "data": {"load_zone_lmps": prices},
    }


def _source_backoff_active(bundle: dict[str, Any] | None) -> bool:
    if callback_context.triggered_id == "refresh-button":
        return False
    if not isinstance(bundle, dict):
        return False

    retry_after = str((bundle.get("refresh_policy") or {}).get("retry_after") or "")
    if not retry_after:
        return False

    try:
        parsed = datetime.fromisoformat(retry_after.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed > datetime.now(timezone.utc)


def _refresh_policy_for_status(status: dict[str, Any]) -> dict[str, Any]:
    state = status.get("state")
    backoff_seconds = 0
    if state in {"unavailable", "unknown"}:
        backoff_seconds = 120
    elif state in {"demo", "partial", "stale"}:
        backoff_seconds = 60

    retry_after = ""
    if backoff_seconds:
        retry_after = (datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)).isoformat()
    return {"backoff_seconds": backoff_seconds, "retry_after": retry_after}


def _placeholder_kpis() -> dmc.Grid:
    return dmc.Grid(
        [
            dmc.GridCol(
                dmc.Card(dmc.Skeleton(h=82), withBorder=True, className="kpi-card"),
                span={"base": 12, "sm": 6, "lg": 4, "xl": 2},
            )
            for _ in range(6)
        ],
        gutter="md",
    )


def _scenario_preview_grid(preview: dict[str, Any] | None) -> dmc.SimpleGrid:
    cards = preview.get("cards") if isinstance(preview, dict) else []
    if not isinstance(cards, list) or not cards:
        children = [
            dmc.Box(
                dmc.Stack([dmc.Skeleton(h=16, w="70%"), dmc.Skeleton(h=26), dmc.Skeleton(h=12)], gap=8),
                className="scenario-preview-card",
            )
            for _ in range(3)
        ]
    else:
        children = [_scenario_preview_card(card) for card in cards if isinstance(card, dict)]

    return dmc.SimpleGrid(children=children, cols={"base": 1, "sm": 3}, spacing="xs")


def _scenario_preview_card(card: dict[str, Any]) -> dmc.Box:
    label = str(card.get("label") or "Scenario")
    status = str(card.get("status") or "Unknown")
    stress = _float_or_zero(card.get("stress_index"))
    stress_delta = _float_or_zero(card.get("stress_delta"))
    price = card.get("price_proxy")
    color = _scenario_preview_color(status, stress_delta)
    return dmc.Box(
        [
            dmc.Group(
                [
                    dmc.Text(label, fw=800, size="sm", lineClamp=1),
                    dmc.Badge(_signed_value(stress_delta), color=color, variant="light", size="sm"),
                ],
                justify="space-between",
                gap=6,
                wrap="nowrap",
            ),
            dmc.Group(
                [
                    dmc.Text(f"{stress:.1f}", className="scenario-preview-value"),
                    dmc.Text("stress", size="xs", c="dimmed"),
                ],
                gap=6,
                align="baseline",
                mt=4,
            ),
            dmc.SimpleGrid(
                [
                    _scenario_preview_fact("Load", f"{_float_or_zero(card.get('load_mw')):,.0f} MW"),
                    _scenario_preview_fact("Wind", f"{_float_or_zero(card.get('wind_mw')):,.0f} MW"),
                    _scenario_preview_fact("Price", f"${float(price):.2f}" if isinstance(price, int | float) else "N/A"),
                    _scenario_preview_fact("Status", status),
                ],
                cols=2,
                spacing=6,
                mt=6,
            ),
        ],
        className=f"scenario-preview-card scenario-preview-{color}",
    )


def _scenario_preview_fact(label: str, value: str) -> dmc.Box:
    return dmc.Box(
        [
            dmc.Text(label, size="xs", c="dimmed", tt="uppercase", fw=800),
            dmc.Text(value, size="xs", fw=760, lineClamp=1),
        ],
        className="scenario-preview-fact",
    )


def _active_scenario_panel(snapshot: dict[str, Any] | None) -> dmc.Box:
    if not snapshot:
        return dmc.Box(
            dmc.Stack([dmc.Skeleton(h=16, w="62%"), dmc.Skeleton(h=32), dmc.Skeleton(h=72)], gap=8),
            className="active-scenario-card active-scenario-cyan",
        )

    active = snapshot.get("active_scenario")
    if not isinstance(active, dict):
        ercot = snapshot.get("ercot", {})
        metrics = snapshot.get("metrics", {})
        return dmc.Box(
            [
                dmc.Group(
                    [
                        _scenario_title("Base Case", "tabler:activity", "cyan"),
                        dmc.Badge(str(snapshot.get("system_status") or "Normal"), color=_status_color(str(snapshot.get("system_status") or "Normal")), variant="light"),
                    ],
                    justify="space-between",
                    gap=8,
                    wrap="nowrap",
                ),
                dmc.SimpleGrid(
                    [
                        _active_scenario_fact("Load", _number_label(ercot.get("load_mw"), "MW"), "tabler:bolt", "cyan"),
                        _active_scenario_fact("Wind", _number_label(ercot.get("wind_mw"), "MW"), "tabler:wind", "green"),
                        _active_scenario_fact("Stress", _number_label(metrics.get("stress_index"), "index", precision=1), "tabler:gauge", _status_color(str(snapshot.get("system_status") or "Normal"))),
                    ],
                    cols={"base": 1, "sm": 3},
                    spacing=6,
                    mt=8,
                ),
            ],
            className="active-scenario-card active-scenario-cyan",
        )

    color = str(active.get("color") or "cyan")
    impacts = [impact for impact in active.get("impacts", []) if isinstance(impact, dict)]
    steps = [step for step in active.get("steps", []) if isinstance(step, dict)]
    return dmc.Box(
        [
            dmc.Group(
                [
                    _scenario_title(
                        str(active.get("label") or "Scenario"),
                        str(active.get("icon") or "tabler:adjustments-bolt"),
                        color,
                    ),
                    dmc.Badge(str(active.get("status") or snapshot.get("system_status") or ""), color=color, variant="light"),
                ],
                justify="space-between",
                gap=8,
                wrap="nowrap",
            ),
            dmc.Text(str(active.get("summary") or ""), size="xs", c="dimmed", mt=6, lineClamp=2),
            dmc.SimpleGrid(
                [_scenario_impact_tile(impact) for impact in impacts[:6]],
                cols={"base": 2, "sm": 3},
                spacing=6,
                mt=9,
            ),
            dmc.Stack([_scenario_step_row(step, color) for step in steps[:4]], gap=6, mt=9),
        ],
        className=f"active-scenario-card active-scenario-{color}",
    )


def _scenario_title(label: str, icon: str, color: str) -> dmc.Group:
    return dmc.Group(
        [
            dmc.ThemeIcon(DashIconify(icon=icon, width=17), color=color, variant="light", radius="sm"),
            dmc.Text(label, fw=850, size="sm", lineClamp=1),
        ],
        gap="xs",
        wrap="nowrap",
        className="active-scenario-title",
    )


def _active_scenario_fact(label: str, value: str, icon: str, color: str) -> dmc.Box:
    return dmc.Box(
        [
            dmc.Group(
                [
                    dmc.ThemeIcon(DashIconify(icon=icon, width=15), color=color, variant="subtle", radius="sm"),
                    dmc.Text(label, size="xs", c="dimmed", tt="uppercase", fw=800),
                ],
                gap=4,
                wrap="nowrap",
            ),
            dmc.Text(value, size="sm", fw=820, mt=2, lineClamp=1),
        ],
        className="active-scenario-fact",
    )


def _scenario_impact_tile(impact: dict[str, Any]) -> dmc.Box:
    direction = str(impact.get("direction") or "flat")
    color = str(impact.get("color") or "gray")
    icon = {
        "up": "tabler:arrow-up-right",
        "down": "tabler:arrow-down-right",
        "flat": "tabler:minus",
    }.get(direction, "tabler:minus")
    return dmc.Box(
        [
            dmc.Group(
                [
                    dmc.Text(str(impact.get("label") or "Metric"), size="xs", c="dimmed", tt="uppercase", fw=800, lineClamp=1),
                    dmc.ThemeIcon(DashIconify(icon=icon, width=14), color=color, variant="subtle", radius="sm", size=22),
                ],
                justify="space-between",
                gap=4,
                wrap="nowrap",
            ),
            dmc.Text(str(impact.get("delta_label") or "+0"), size="sm", fw=850, className=f"impact-value impact-{color}", lineClamp=1),
            dmc.Text(str(impact.get("after_label") or ""), size="xs", c="dimmed", lineClamp=1),
        ],
        className=f"scenario-impact-tile scenario-impact-{color}",
    )


def _scenario_step_row(step: dict[str, Any], color: str) -> dmc.Box:
    return dmc.Box(
        dmc.Group(
            [
                dmc.Badge(str(step.get("value") or ""), color=color, variant="light", size="sm"),
                dmc.Stack(
                    [
                        dmc.Text(str(step.get("label") or "Scenario step"), size="xs", fw=820, lineClamp=1),
                        dmc.Text(str(step.get("message") or ""), size="xs", c="dimmed", lineClamp=2),
                    ],
                    gap=1,
                ),
            ],
            gap="xs",
            wrap="nowrap",
            align="flex-start",
        ),
        className="scenario-step-row",
    )


def _scenario_preview_color(status: str, stress_delta: float) -> str:
    if status == "System Stress" or stress_delta >= 8:
        return "red"
    if stress_delta > 0:
        return "yellow"
    if stress_delta < 0:
        return "green"
    return "cyan"


def _signed_value(value: float) -> str:
    if abs(value) < 0.05:
        return "+0.0"
    return f"{value:+.1f}"


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _number_label(value: Any, unit: str, *, precision: int = 0) -> str:
    if not isinstance(value, int | float):
        return "N/A"
    return f"{float(value):,.{precision}f} {unit}"


def _latency_placeholders() -> list[dmc.Skeleton]:
    return [dmc.Skeleton(h=26, radius="sm") for _ in range(4)]


def _latency_rows(latency_ms: dict[str, Any]) -> list[dmc.Box]:
    rows = []
    numeric = {
        name: float(value)
        for name, value in latency_ms.items()
        if isinstance(value, int | float)
    }
    if not numeric:
        return _latency_placeholders()

    max_latency = max(numeric.values(), default=1) or 1
    for name, duration in numeric.items():
        rows.append(
            dmc.Box(
                [
                    dmc.Group(
                        [
                            dmc.Text(SOURCE_LABELS.get(name, name.replace("_", " ").title()), size="xs", fw=760),
                            dmc.Text(f"{duration:,.0f} ms", size="xs", c="dimmed"),
                        ],
                        justify="space-between",
                        wrap="nowrap",
                        mb=4,
                    ),
                    dmc.Progress(
                        value=_clamp((duration / max_latency) * 100),
                        color=_latency_color(duration),
                        size=5,
                        radius="xl",
                    ),
                ],
                className="latency-row",
            )
        )
    return rows


def _async_benefit_card(snapshot: dict[str, Any] | None) -> dmc.Stack:
    if not snapshot:
        return dmc.Stack(
            [
                dmc.Skeleton(h=20, w="70%"),
                dmc.Skeleton(h=36),
                dmc.Skeleton(h=36),
            ],
            gap="xs",
        )

    fanout = snapshot.get("fanout") or {}
    latency_ms = fanout.get("source_latency_ms") or {}
    numeric = [
        float(value)
        for value in latency_ms.values()
        if isinstance(value, int | float) and float(value) >= 0
    ]
    if not numeric:
        return dmc.Stack(
            [
                dmc.Group(
                    [
                        dmc.ThemeIcon(DashIconify(icon="tabler:timeline-event", width=17), color="gray", variant="light", radius="sm"),
                        dmc.Text("Sync vs async callback fanout", fw=830, size="sm"),
                    ],
                    gap="xs",
                    wrap="nowrap",
                ),
                dmc.Text("Waiting for source latency telemetry.", size="xs", c="dimmed"),
            ],
            gap="xs",
        )

    sequential_ms = sum(numeric)
    async_floor_ms = max(numeric)
    observed_ms = float(fanout.get("duration_ms") or async_floor_ms)
    saved_ms = max(0.0, sequential_ms - async_floor_ms)
    speedup = sequential_ms / async_floor_ms if async_floor_ms else 1
    scale_ms = max(sequential_ms, async_floor_ms, observed_ms, 1)
    strategy = str(fanout.get("strategy") or "async fanout")

    return dmc.Stack(
        [
            dmc.Group(
                [
                    dmc.ThemeIcon(DashIconify(icon="tabler:timeline-event", width=17), color="cyan", variant="light", radius="sm"),
                    dmc.Stack(
                        [
                            dmc.Text("Sync vs async callback fanout", fw=830, size="sm"),
                            dmc.Text(f"{len(numeric)} upstream waits | {strategy}", size="xs", c="dimmed", lineClamp=1),
                        ],
                        gap=1,
                    ),
                    dmc.Badge(f"{speedup:.1f}x", color="green" if speedup >= 1.4 else "cyan", variant="light"),
                ],
                justify="space-between",
                gap="xs",
                wrap="nowrap",
                align="flex-start",
            ),
            _async_benefit_bar("Sync estimate", sequential_ms, scale_ms, "gray", "Sum of each upstream wait"),
            _async_benefit_bar("Async gather floor", async_floor_ms, scale_ms, "cyan", "Bounded by the slowest wait"),
            dmc.SimpleGrid(
                [
                    _async_benefit_fact("Saved", f"{saved_ms:,.0f} ms", "tabler:clock-bolt", "green"),
                    _async_benefit_fact("Observed stores", f"{observed_ms:,.0f} ms", "tabler:activity", "violet"),
                ],
                cols=2,
                spacing=6,
            ),
        ],
        gap="xs",
    )


def _async_benefit_bar(label: str, value_ms: float, scale_ms: float, color: str, caption: str) -> dmc.Box:
    return dmc.Box(
        [
            dmc.Group(
                [
                    dmc.Stack(
                        [
                            dmc.Text(label, size="xs", c="dimmed", tt="uppercase", fw=800),
                            dmc.Text(caption, size="xs", c="dimmed", lineClamp=1),
                        ],
                        gap=0,
                    ),
                    dmc.Text(f"{value_ms:,.0f} ms", className="async-benefit-value"),
                ],
                justify="space-between",
                gap=6,
                wrap="nowrap",
                align="flex-start",
                mb=5,
            ),
            dmc.Progress(value=_clamp((value_ms / scale_ms) * 100), color=color, size=6, radius="xl"),
        ],
        className="async-benefit-bar",
    )


def _async_benefit_fact(label: str, value: str, icon: str, color: str) -> dmc.Box:
    return dmc.Box(
        [
            dmc.Group(
                [
                    dmc.ThemeIcon(DashIconify(icon=icon, width=14), color=color, variant="subtle", radius="sm", size=22),
                    dmc.Text(label, size="xs", c="dimmed", tt="uppercase", fw=800),
                ],
                gap=4,
                wrap="nowrap",
            ),
            dmc.Text(value, size="sm", fw=830, mt=2, lineClamp=1),
        ],
        className="active-scenario-fact",
    )


def _latency_color(duration_ms: float) -> str:
    if duration_ms >= 2000:
        return "red"
    if duration_ms >= 900:
        return "yellow"
    return "cyan"


def _format_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "Updated just now"
    return f"Updated {parsed.strftime('%H:%M:%S UTC')}"


def _status_color(status: str) -> str:
    if status == "System Stress":
        return "red"
    if status == "Elevated":
        return "yellow"
    return "green"


def _trend(snapshot: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return snapshot.get("trends", {}).get(key, [])


def _map_prices_complete(map_prices: dict[str, Any] | None) -> bool:
    if not map_prices:
        return False
    status = map_prices.get("status") or {}
    zones = map_prices.get("zones") or []
    return bool(
        map_prices.get("complete")
        and status.get("state") == "live"
        and len(zones) >= 4
        and all(isinstance(zone.get("price_usd_mwh"), int | float) for zone in zones)
    )


def _with_map_prices(
    snapshot: dict[str, Any] | None,
    map_prices: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not snapshot or not map_prices:
        return snapshot

    price_by_settlement = {
        str(zone.get("settlement_point", "")).upper(): zone
        for zone in map_prices.get("zones", [])
        if isinstance(zone.get("price_usd_mwh"), int | float)
    }
    if not price_by_settlement:
        return snapshot

    updated_snapshot = dict(snapshot)
    ercot = dict(updated_snapshot.get("ercot") or {})
    for key in ("load_zones", "regions"):
        ercot[key] = [_zone_with_map_price(zone, price_by_settlement) for zone in ercot.get(key, [])]
    updated_snapshot["ercot"] = ercot
    return updated_snapshot


def _zone_with_map_price(
    zone: dict[str, Any],
    price_by_settlement: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    updated = dict(zone)
    settlement_point = str(updated.get("settlement_point", "")).upper()
    price_row = price_by_settlement.get(settlement_point)
    if price_row:
        updated["price_usd_mwh"] = round(float(price_row["price_usd_mwh"]), 2)
    return updated


def _map_price_caption(map_prices: dict[str, Any] | None) -> str:
    if not map_prices:
        return "Loading load-zone LMPs"
    status = map_prices.get("status") or {}
    if _map_prices_complete(map_prices):
        timestamp = _latest_map_price_timestamp(map_prices)
        return f"Load-zone LMPs live {timestamp}".strip()
    message = status.get("message") or "retrying every 10s"
    return f"Load-zone LMPs loading ({message})"


def _latest_map_price_timestamp(map_prices: dict[str, Any]) -> str:
    timestamps = [
        str(zone.get("timestamp", ""))
        for zone in map_prices.get("zones", [])
        if zone.get("timestamp")
    ]
    if not timestamps:
        return ""
    try:
        parsed = datetime.fromisoformat(max(timestamps).replace("Z", "+00:00"))
    except ValueError:
        return max(timestamps)
    return parsed.strftime("%H:%M CT")


def _format_supply_timestamp(value: str) -> str:
    if not value:
        return "ERCOT current day"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return f"Updated {parsed.strftime('%H:%M CT')}"


def _event_color(level: str) -> str:
    return {
        "danger": "red",
        "warning": "yellow",
        "success": "green",
        "info": "cyan",
    }.get(level, "gray")


def _clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    return max(minimum, min(maximum, float(value)))


def _system_overview_placeholder() -> dmc.SimpleGrid:
    return dmc.SimpleGrid(
        [
            dmc.Skeleton(h=156, radius="sm"),
            dmc.Stack([dmc.Skeleton(h=44), dmc.Skeleton(h=44), dmc.Skeleton(h=44)], gap="sm"),
            dmc.Stack([dmc.Skeleton(h=44), dmc.Skeleton(h=44), dmc.Skeleton(h=44)], gap="sm"),
        ],
        cols={"base": 1, "md": 3},
        spacing="md",
    )


def _source_status_placeholders() -> list[dmc.Box]:
    return [
        dmc.Box(
            dmc.Group(
                [
                    dmc.Skeleton(h=28, w=28, radius="sm"),
                    dmc.Stack([dmc.Skeleton(h=10, w=82), dmc.Skeleton(h=8, w=132)], gap=6),
                ],
                gap="sm",
                wrap="nowrap",
            ),
            className="source-tile",
        )
        for _ in range(6)
    ]


def _source_status_tile(name: str, status: dict[str, str], icon: str, color: str) -> dmc.Box:
    state = status.get("state", "unknown").title()
    message = status.get("message") or "Healthy response path"
    state_color = _source_state_color(status.get("state", "unknown"), color)
    return dmc.Box(
        [
            dmc.Group(
                [
                    dmc.ThemeIcon(
                        DashIconify(icon=icon, width=18),
                        color=state_color,
                        variant="light",
                        radius="sm",
                        className="source-icon",
                    ),
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    dmc.Text(name, fw=800, size="sm"),
                                    dmc.Badge(state, color=state_color, variant="dot", size="sm"),
                                ],
                                gap="xs",
                                wrap="nowrap",
                            ),
                            dmc.Text(message, size="xs", c="dimmed", lineClamp=1),
                        ],
                        gap=2,
                    ),
                ],
                gap="sm",
                wrap="nowrap",
            )
        ],
        className=f"source-tile source-tile-{state_color}",
    )


def _source_group_tile(name: str, group: dict[str, Any] | None, icon: str, color: str) -> dmc.Box:
    status = dict((group or {}).get("status") or {})
    policy = (group or {}).get("refresh_policy") or {}
    message = str(status.get("message") or "Healthy response path")
    retry_message = _retry_policy_label(policy)
    if retry_message and status.get("state") != "live":
        message = f"{message} {retry_message}".strip()
    status["message"] = message
    return _source_status_tile(name, status, icon, color)


def _retry_policy_label(policy: dict[str, Any]) -> str:
    retry_after = str(policy.get("retry_after") or "")
    if not retry_after:
        return ""
    try:
        parsed = datetime.fromisoformat(retry_after.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    seconds = max(0, int((parsed - datetime.now(timezone.utc)).total_seconds()))
    if seconds <= 0:
        return ""
    return f"Backoff {seconds}s."


def _metric_bar(label: str, value: str, progress: float, color: str) -> dmc.Box:
    return dmc.Box(
        [
            dmc.Group(
                [
                    dmc.Text(label, size="xs", c="dimmed", tt="uppercase", fw=800),
                    dmc.Text(value, size="sm", fw=800),
                ],
                justify="space-between",
                wrap="nowrap",
                mb=5,
            ),
            dmc.Progress(value=_clamp(progress), color=color, size=6, radius="xl"),
        ],
        className="metric-bar",
    )


def _fact_tile(label: str, value: str, icon: str, color: str) -> dmc.Box:
    return dmc.Box(
        dmc.Group(
            [
                dmc.ThemeIcon(DashIconify(icon=icon, width=18), color=color, variant="light", radius="sm"),
                dmc.Stack(
                    [
                        dmc.Text(label, size="xs", c="dimmed", tt="uppercase", fw=800),
                        dmc.Text(value, size="sm", fw=800),
                    ],
                    gap=0,
                ),
            ],
            gap="sm",
            wrap="nowrap",
        ),
        className="fact-tile",
    )


def _reserve_color(reserve_margin: float) -> str:
    if reserve_margin < 8:
        return "red"
    if reserve_margin < 14:
        return "yellow"
    return "green"


def _source_state_color(state: str, fallback: str) -> str:
    if state == "live":
        return "green"
    if state == "partial":
        return "yellow"
    if state == "stale":
        return "orange"
    if state == "demo":
        return "cyan"
    return fallback

from __future__ import annotations

import html as html_lib
import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from dash import html as dash_html
import dash_leaflet as dl
import plotly.graph_objects as go

ERCOT_LOAD_ZONES_ASSET = Path(__file__).parent / "assets" / "ERCOT_Load_Zones.geojson"
GRID_MAP_CENTER = [31.0, -99.2]
GRID_MAP_TILE_URL = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
GRID_MAP_TILE_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
    '&copy; <a href="https://carto.com/attributions">CARTO</a>'
)
ERCOT_LOAD_ZONE_COLORS = {
    "Houston": "#38bdf8",
    "North": "#a78bfa",
    "South": "#22c55e",
    "West": "#facc15",
}
SPARKLINE_COLORS = {
    "cyan": "#22d3ee",
    "yellow": "#facc15",
    "green": "#22c55e",
    "orange": "#fb923c",
    "red": "#fb7185",
    "violet": "#a78bfa",
}
FUEL_COLORS = {
    "Natural Gas": "#38bdf8",
    "Wind": "#22c55e",
    "Coal and Lignite": "#facc15",
    "Solar": "#fb923c",
    "Nuclear": "#a78bfa",
    "Power Storage": "#f472b6",
    "Hydro": "#2dd4bf",
    "Other": "#94a3b8",
}
GAS_REGION_COLORS = {
    "east_bcf": "#38bdf8",
    "midwest_bcf": "#22c55e",
    "south_central_bcf": "#facc15",
    "mountain_bcf": "#a78bfa",
    "pacific_bcf": "#fb923c",
}
DARK_HOVERLABEL = {
    "bgcolor": "rgba(8, 13, 23, 0.96)",
    "bordercolor": "rgba(34, 211, 238, 0.32)",
    "font": {"color": "#e8eef7", "size": 12},
    "namelength": -1,
}
WEATHER_ICON_RULES = (
    (("thunder", "storm", "lightning"), "storm", "Stormy", "#a78bfa"),
    (("snow", "sleet", "ice", "freezing", "wintry"), "snow", "Snowy", "#bae6fd"),
    (("rain", "shower", "drizzle", "precip"), "rain", "Rainy", "#38bdf8"),
    (("fog", "mist", "haze", "smoke"), "fog", "Foggy", "#94a3b8"),
    (("wind", "breezy", "gust"), "wind", "Windy", "#2dd4bf"),
    (("partly", "scattered", "few clouds", "mostly sunny"), "partly-cloudy", "Partly Cloudy", "#facc15"),
    (("cloud", "overcast"), "cloud", "Cloudy", "#cbd5e1"),
    (("sun", "clear", "fair"), "sun", "Sunny", "#fb923c"),
)
WEATHER_SVG_ICONS = {
    "cloud": (
        '<path d="M7 18h10.2a4.3 4.3 0 0 0 .5-8.6A6.2 6.2 0 0 0 6 11.2A3.4 3.4 0 0 0 7 18Z"/>'
    ),
    "fog": (
        '<path d="M7 15h10.2a4 4 0 0 0 .4-8A5.8 5.8 0 0 0 6.5 8.4A3.2 3.2 0 0 0 7 15Z"/>'
        '<path d="M5 19h14"/><path d="M7 22h10"/>'
    ),
    "partly-cloudy": (
        '<path d="M8.4 9.8A4 4 0 1 1 14 5.3"/>'
        '<path d="M3.5 9.5h1"/><path d="M7 4V3"/><path d="m4.5 6.2-.8-.7"/>'
        '<path d="M8 19h9.2a4 4 0 0 0 .4-8A5.8 5.8 0 0 0 6.5 12.4A3.2 3.2 0 0 0 8 19Z"/>'
    ),
    "rain": (
        '<path d="M7 15.5h10.2a4 4 0 0 0 .4-8A5.8 5.8 0 0 0 6.5 8.9A3.2 3.2 0 0 0 7 15.5Z"/>'
        '<path d="M8 19.5v1.5"/><path d="M12 18.5V20"/><path d="M16 19.5v1.5"/>'
    ),
    "snow": (
        '<path d="M7 14.5h10.2a4 4 0 0 0 .4-8A5.8 5.8 0 0 0 6.5 7.9A3.2 3.2 0 0 0 7 14.5Z"/>'
        '<path d="M12 18v4"/><path d="M10.3 19l3.4 2"/><path d="m13.7 19-3.4 2"/>'
    ),
    "storm": (
        '<path d="M7 14.5h10.2a4 4 0 0 0 .4-8A5.8 5.8 0 0 0 6.5 7.9A3.2 3.2 0 0 0 7 14.5Z"/>'
        '<path d="m12.8 15.5-2.2 4h3.1l-1.5 3"/>'
    ),
    "sun": (
        '<circle cx="12" cy="12" r="3.8"/>'
        '<path d="M12 2.8V5"/><path d="M12 19v2.2"/><path d="M4.9 4.9l1.6 1.6"/>'
        '<path d="m17.5 17.5 1.6 1.6"/><path d="M2.8 12H5"/><path d="M19 12h2.2"/>'
        '<path d="m4.9 19.1 1.6-1.6"/><path d="m17.5 6.5 1.6-1.6"/>'
    ),
    "wind": (
        '<path d="M4 8h10.5a2.2 2.2 0 1 0-2.1-2.8"/>'
        '<path d="M4 12h15.5a2 2 0 1 1-1.8 2.8"/>'
        '<path d="M4 16h8.5a2 2 0 1 1-1.8 2.8"/>'
    ),
}


def build_kpi_sparkline(points: list[dict[str, Any]] | None, *, color: str) -> go.Figure:
    series = points or []
    figure = _sparkline_base()
    if not series:
        return figure

    line_color = SPARKLINE_COLORS.get(color, SPARKLINE_COLORS["cyan"])
    actual = [point for point in series if not point.get("is_forecast")]
    forecast = [point for point in series if point.get("is_forecast")]
    bridge = actual[-1:] if actual and forecast else []

    if actual:
        figure.add_trace(
            go.Scatter(
                x=[point.get("timestamp") or index for index, point in enumerate(actual)],
                y=[point.get("value") for point in actual],
                mode="lines",
                line={
                    "color": _rgba(line_color, 0.42),
                    "width": 2.1,
                    "dash": "solid",
                    "shape": "spline",
                    "smoothing": 0.65,
                },
                fill="tozeroy",
                fillcolor=_rgba(line_color, 0.06),
                hoverinfo="skip",
            )
        )

    if forecast:
        forecast_points = [*bridge, *forecast]
        figure.add_trace(
            go.Scatter(
                x=[point.get("timestamp") or index for index, point in enumerate(forecast_points)],
                y=[point.get("value") for point in forecast_points],
                mode="lines",
                line={
                    "color": _rgba(line_color, 0.9),
                    "width": 2.1,
                    "dash": "dot",
                    "shape": "spline",
                    "smoothing": 0.65,
                },
                hoverinfo="skip",
            )
        )
    return figure


def build_supply_demand_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    if not snapshot:
        return _blank_figure("Waiting for ERCOT supply and demand")

    points = snapshot.get("supply_demand", {}).get("current_day", [])
    if not points:
        return _blank_figure("Waiting for ERCOT supply and demand")

    actual = [point for point in points if not point.get("is_forecast")]
    forecast = [point for point in points if point.get("is_forecast")]
    bridge = actual[-1:] if actual else []

    figure = go.Figure()
    _add_supply_line(figure, actual, key="demand_mw", name="Demand", color="#00c2d8", width=3)
    _add_supply_line(
        figure,
        actual,
        key="committed_capacity_mw",
        name="Committed Capacity",
        color="#6d4acb",
        width=3,
    )
    _add_supply_line(
        figure,
        [*bridge, *forecast],
        key="demand_mw",
        name="Demand Forecast",
        color="#00c2d8",
        dash="dot",
    )
    _add_supply_line(
        figure,
        [*bridge, *forecast],
        key="committed_capacity_mw",
        name="Committed Capacity Forecast",
        color="#6d4acb",
        dash="dot",
    )
    _add_supply_line(
        figure,
        forecast,
        key="available_capacity_mw",
        name="Available Capacity",
        color="#b899ff",
        dash="dash",
        width=2.4,
    )

    latest = snapshot.get("supply_demand", {}).get("latest", {})
    if latest.get("timestamp"):
        figure.add_vline(
            x=latest["timestamp"],
            line={"color": "rgba(248,250,252,.28)", "width": 1, "dash": "dash"},
        )

    figure.update_layout(
        height=348,
        margin={"l": 48, "r": 18, "t": 12, "b": 38},
        hovermode="x unified",
        hoverlabel=DARK_HOVERLABEL,
        legend={
            "orientation": "h",
            "x": 0,
            "y": 1.07,
            "font": {"size": 11},
            "bgcolor": "rgba(2, 6, 23, 0)",
        },
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(2,6,23,.24)",
        font={"color": "#dbeafe"},
        xaxis={
            "title": "",
            "gridcolor": "rgba(148,163,184,.11)",
            "showline": False,
            "tickfont": {"size": 11},
        },
        yaxis={
            "title": "",
            "ticksuffix": " MW",
            "tickformat": ",.0f",
            "gridcolor": "rgba(148,163,184,.14)",
            "zeroline": False,
            "tickfont": {"size": 11},
        },
        uirevision="ercot-supply-demand-current-day",
    )
    return figure


def build_prc_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    prc = (snapshot or {}).get("ercot_dashboards", {}).get("prc", {})
    series = prc.get("series", [])
    if not series:
        return _blank_figure("Waiting for ERCOT PRC")

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=[point["timestamp"] for point in series],
            y=[point["prc_mw"] for point in series],
            mode="lines",
            line={"color": "#22d3ee", "width": 2.4, "shape": "spline", "smoothing": 0.35},
            fill="tozeroy",
            fillcolor="rgba(34,211,238,.12)",
            name="PRC",
            hovertemplate="PRC: %{y:,.0f} MW<extra></extra>",
        )
    )
    figure.add_hline(y=3000, line={"color": "rgba(251,113,133,.7)", "width": 1.2, "dash": "dash"})
    return _apply_chart_layout(figure, height=272, y_suffix=" MW", uirevision="ercot-prc")


def build_system_price_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    ercot = (snapshot or {}).get("ercot", {})
    price_status = ercot.get("price_status") or ercot.get("status", {})
    if price_status.get("state") in {"demo", "unavailable"}:
        return _blank_figure("ERCOT price API unavailable")

    prices = ercot.get("price_series", {})
    rt_series = prices.get("rt_lmp", [])
    da_series = prices.get("da_lmp", [])
    if not rt_series and not da_series:
        return _blank_figure("Waiting for ERCOT market prices")

    figure = go.Figure()
    if rt_series:
        figure.add_trace(
            go.Scatter(
                x=[point["timestamp"] for point in rt_series],
                y=[point["value"] for point in rt_series],
                mode="lines",
                line={"color": "#22d3ee", "width": 2.6, "shape": "spline", "smoothing": 0.35},
                name="RT LMP",
                hovertemplate="RT LMP: $%{y:.2f}/MWh<extra></extra>",
            )
        )
    if da_series:
        figure.add_trace(
            go.Scatter(
                x=[point["timestamp"] for point in da_series],
                y=[point["value"] for point in da_series],
                mode="lines",
                line={"color": "#facc15", "width": 2.4, "shape": "hv"},
                name="DA LMP",
                hovertemplate="DA LMP: $%{y:.2f}/MWh<extra></extra>",
            )
        )

    figure = _apply_chart_layout(figure, height=272, y_prefix="$", uirevision="ercot-system-prices")
    figure.update_layout(
        yaxis={
            **figure.layout.yaxis.to_plotly_json(),
            "ticksuffix": "/MWh",
        },
    )
    return figure


def build_system_demand_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    points = (snapshot or {}).get("supply_demand", {}).get("current_day", [])
    if not points:
        return _blank_figure("Waiting for ERCOT system-wide demand")

    actual = [point for point in points if not point.get("is_forecast")]
    forecast = [point for point in points if point.get("is_forecast")]
    bridge = actual[-1:] if actual else []

    figure = go.Figure()
    _add_supply_line(figure, actual, key="demand_mw", name="Actual Hourly Average", color="#00c2d8", width=2.8)
    _add_supply_line(
        figure,
        [*bridge, *forecast],
        key="demand_mw",
        name="Current Forecast",
        color="#a78bfa",
        dash="dot",
        width=2.5,
    )
    return _apply_chart_layout(figure, height=272, y_suffix=" MW", uirevision="ercot-system-demand")


def build_combined_renewables_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    if not snapshot:
        return _blank_figure("Waiting for wind and solar")

    rows = (snapshot.get("ercot_dashboards", {}).get("combined_renewables", {}) or {}).get("current_day") or []
    if not rows:
        return _blank_figure("Waiting for wind and solar")

    figure = go.Figure()
    _add_trend_line(
        figure,
        _dashboard_actual_forecast_series(rows, "wind_actual_mw", "wind_forecast_mw"),
        "Wind Gen Hourly Avg",
        "#38bdf8",
    )
    _add_trend_line(
        figure,
        _dashboard_actual_forecast_series(rows, "solar_actual_mw", "solar_forecast_mw"),
        "Solar Gen Hourly Avg",
        "#fb923c",
    )
    _add_trend_line(
        figure,
        _dashboard_actual_forecast_series(rows, "combined_actual_mw", "combined_forecast_mw"),
        "Combined Gen Hourly Avg",
        "#a78bfa",
        width=2.9,
    )
    figure = _apply_chart_layout(figure, height=272, y_suffix=" MW", uirevision="ercot-combined-renewables")
    axis_range = _current_day_axis_range(rows)
    if axis_range:
        figure.update_xaxes(range=axis_range)
    return figure


def build_load_zone_price_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    zones = (snapshot or {}).get("ercot", {}).get("load_zones", [])
    rows = [
        zone
        for zone in zones
        if isinstance(zone, dict) and _is_number(zone.get("price_usd_mwh"))
    ]
    if not rows:
        return _blank_figure("Waiting for load-zone LMPs")

    values = [float(zone["price_usd_mwh"]) for zone in rows]
    figure = go.Figure(
        go.Bar(
            x=[zone.get("name", "") for zone in rows],
            y=values,
            marker={
                "color": values,
                "colorscale": [
                    [0, "#22c55e"],
                    [0.55, "#facc15"],
                    [1, "#fb7185"],
                ],
                "line": {"color": "rgba(248,250,252,.18)", "width": 1},
            },
            customdata=[zone.get("settlement_point", "") for zone in rows],
            hovertemplate="%{customdata}: $%{y:.2f}/MWh<extra></extra>",
            name="RT LMP",
        )
    )
    figure = _apply_chart_layout(figure, height=272, y_prefix="$", uirevision="ercot-load-zone-prices")
    figure.update_layout(
        yaxis={
            **figure.layout.yaxis.to_plotly_json(),
            "ticksuffix": "/MWh",
        },
        showlegend=False,
    )
    return figure


def build_dc_tie_flows_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    if not snapshot:
        return _blank_figure("Waiting for DC tie flows")

    series = (snapshot.get("ercot_dashboards", {}).get("dc_ties", {}) or {}).get("series") or {}
    if not isinstance(series, dict) or not any(series.values()):
        return _blank_figure("Waiting for DC tie flows")

    figure = go.Figure()
    colors = {
        "North": "#38bdf8",
        "East": "#a78bfa",
        "Laredo": "#fb923c",
        "Railroad": "#22c55e",
    }
    for name, points in series.items():
        figure.add_trace(
            go.Scatter(
                x=[point["timestamp"] for point in points],
                y=[point["value"] for point in points],
                mode="lines",
                name=name,
                line={"color": colors.get(name, "#94a3b8"), "width": 2.2, "shape": "spline", "smoothing": 0.35},
                hovertemplate=f"{name}: %{{y:+,.0f}} MW<extra></extra>",
            )
        )
    figure.add_hline(y=0, line={"color": "rgba(248,250,252,.28)", "width": 1})
    figure = _apply_chart_layout(figure, height=272, y_suffix=" MW", uirevision="ercot-dc-ties")
    all_points = [point for points in series.values() for point in points if isinstance(point, dict)]
    axis_range = _current_day_axis_range(all_points)
    if axis_range:
        figure.update_xaxes(range=axis_range)
    return figure


def build_ercot_fuel_stack(snapshot: dict[str, Any] | None) -> go.Figure:
    fuel = (snapshot or {}).get("ercot_dashboards", {}).get("fuel_mix", {})
    series = fuel.get("current_day") or _latest_day_series(fuel.get("series", []))
    if not series:
        return _blank_figure("Waiting for ERCOT fuel mix")

    latest_mix = fuel.get("latest", {}).get("mix", [])
    fuel_names = [item["fuel"] for item in latest_mix] or fuel.get("fuel_types", [])
    figure = go.Figure()
    for name in fuel_names:
        values = [point.get("fuels", {}).get(name, 0) for point in series]
        if not any(values):
            continue
        figure.add_trace(
            go.Scatter(
                x=[point["timestamp"] for point in series],
                y=values,
                mode="lines",
                stackgroup="fuel",
                name=name,
                line={"width": 0.6, "color": FUEL_COLORS.get(name, "#94a3b8")},
                hovertemplate=f"{name}: %{{y:,.0f}} MW<extra></extra>",
            )
        )
    return _apply_chart_layout(figure, height=322, y_suffix=" MW", uirevision="ercot-fuel-stack")


def _latest_day_series(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dated_points = [(point, _timestamp_date(point.get("timestamp"))) for point in series]
    latest_day = max((day for _, day in dated_points if day), default=None)
    if not latest_day:
        return series
    return [point for point, day in dated_points if day == latest_day]


def build_storage_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    storage = (snapshot or {}).get("ercot_dashboards", {}).get("storage", {})
    series = storage.get("current_day", [])
    if not series:
        return _blank_figure("Waiting for ERCOT storage")

    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=[point["timestamp"] for point in series],
            y=[point["discharging_mw"] for point in series],
            marker={"color": "#22c55e"},
            name="Discharging",
            hovertemplate="Discharging: %{y:,.0f} MW<extra></extra>",
        )
    )
    figure.add_trace(
        go.Bar(
            x=[point["timestamp"] for point in series],
            y=[-point["charging_mw"] for point in series],
            marker={"color": "#38bdf8"},
            name="Charging",
            hovertemplate="Charging: %{customdata:,.0f} MW<extra></extra>",
            customdata=[point["charging_mw"] for point in series],
        )
    )
    return _apply_chart_layout(figure, height=272, y_suffix=" MW", barmode="relative", uirevision="ercot-storage")


def build_outages_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    outages = (snapshot or {}).get("ercot_dashboards", {}).get("outages", {})
    series = outages.get("current", [])
    if not series:
        return _blank_figure("Waiting for ERCOT outages")

    figure = go.Figure()
    for key, name, color in (
        ("planned_mw", "Planned", "#38bdf8"),
        ("unplanned_mw", "Unplanned", "#fb7185"),
    ):
        figure.add_trace(
            go.Scatter(
                x=[point["timestamp"] for point in series],
                y=[point[key] for point in series],
                mode="lines",
                stackgroup="outages",
                name=name,
                line={"width": 1, "color": color},
                hovertemplate=f"{name}: %{{y:,.0f}} MW<extra></extra>",
            )
        )
    return _apply_chart_layout(figure, height=272, y_suffix=" MW", uirevision="ercot-outages")


def build_ancillary_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    ancillary = (snapshot or {}).get("ercot_dashboards", {}).get("ancillary", {})
    products = ancillary.get("products", [])
    if not products:
        return _blank_figure("Waiting for ERCOT ancillary services")

    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=[product["name"] for product in products],
            y=[product["capability_mw"] for product in products],
            name="Capability",
            marker={"color": "#22d3ee"},
            hovertemplate="Capability: %{y:,.0f} MW<extra></extra>",
        )
    )
    figure.add_trace(
        go.Bar(
            x=[product["name"] for product in products],
            y=[product["awards_mw"] for product in products],
            name="Awards",
            marker={"color": "#a78bfa"},
            hovertemplate="Awards: %{y:,.0f} MW<extra></extra>",
        )
    )
    return _apply_chart_layout(figure, height=272, y_suffix=" MW", barmode="group", uirevision="ercot-ancillary")


def build_eia_gas_storage_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    storage = (snapshot or {}).get("eia_gas", {}).get("storage", {})
    series = storage.get("series", [])
    if not series:
        return _blank_figure("Waiting for EIA gas storage")

    figure = go.Figure()
    regions = storage.get("regions") or [
        {"field": "east_bcf", "label": "East"},
        {"field": "midwest_bcf", "label": "Midwest"},
        {"field": "south_central_bcf", "label": "South Central"},
        {"field": "mountain_bcf", "label": "Mountain"},
        {"field": "pacific_bcf", "label": "Pacific"},
    ]
    for region in regions:
        field = str(region.get("field") or "")
        if not any(_is_number(point.get(field)) for point in series):
            continue
        color = GAS_REGION_COLORS.get(field, "#94a3b8")
        label = str(region.get("label") or _pretty_key(field.removesuffix("_bcf")))
        figure.add_trace(
            go.Scatter(
                x=[point["period"] for point in series],
                y=[point.get(field) for point in series],
                mode="lines",
                stackgroup="storage",
                name=label,
                line={"color": _rgba(color, 0.68), "width": 1.1},
                fillcolor=_rgba(color, 0.26),
                hovertemplate=f"{label}: %{{y:,.0f}} Bcf<extra></extra>",
            )
        )

    figure.add_trace(
        go.Scatter(
            x=[point["period"] for point in series],
            y=[point.get("lower_48_bcf") for point in series],
            mode="lines",
            name="Lower 48",
            line={"color": "#e0f2fe", "width": 2.8, "shape": "spline", "smoothing": 0.35},
            hovertemplate="Lower 48: %{y:,.0f} Bcf<extra></extra>",
        )
    )
    figure = _apply_chart_layout(figure, height=322, y_suffix=" Bcf", uirevision="eia-storage")
    figure.update_layout(legend={"orientation": "h", "x": 0, "y": 1.15, "font": {"size": 9}, "bgcolor": "rgba(2, 6, 23, 0)"})
    return figure


def build_eia_gas_balance_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    balance = (snapshot or {}).get("eia_gas", {}).get("balance", {})
    series = balance.get("series", [])
    if not series:
        return _blank_figure("Waiting for EIA STEO gas balance")

    figure = go.Figure()
    x_values = [point["period"] for point in series]
    figure.add_trace(
        go.Scatter(
            x=x_values,
            y=[point.get("supply_bcf_d") for point in series],
            mode="lines",
            name="Supply",
            line={"color": "#22c55e", "width": 2.7, "shape": "spline", "smoothing": 0.35},
            fill="tozeroy",
            fillcolor="rgba(34,197,94,.07)",
            hovertemplate="Supply: %{y:.1f} Bcf/d<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=x_values,
            y=[point.get("consumption_bcf_d") for point in series],
            mode="lines",
            name="Consumption",
            line={"color": "#facc15", "width": 2.8, "shape": "spline", "smoothing": 0.35},
            hovertemplate="Consumption: %{y:.1f} Bcf/d<extra></extra>",
        )
    )
    figure.add_trace(
        go.Bar(
            x=x_values,
            y=[point.get("supply_consumption_gap_bcf_d") for point in series],
            name="Supply Gap",
            marker={"color": _rgba("#38bdf8", 0.46), "line": {"color": _rgba("#38bdf8", 0.84), "width": 0.35}},
            hovertemplate="Supply gap: %{y:+.1f} Bcf/d<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=x_values,
            y=[point.get("working_inventory_bcf") for point in series],
            mode="lines",
            name="Working Inventory",
            line={"color": "#a78bfa", "width": 2.3, "dash": "dot", "shape": "spline", "smoothing": 0.35},
            yaxis="y2",
            hovertemplate="Inventory: %{y:,.0f} Bcf<extra></extra>",
        )
    )
    figure = _apply_chart_layout(figure, height=322, y_suffix=" Bcf/d", barmode="relative", uirevision="eia-gas-balance")
    figure.update_layout(
        yaxis2={
            "overlaying": "y",
            "side": "right",
            "ticksuffix": " Bcf",
            "gridcolor": "rgba(0,0,0,0)",
            "zeroline": False,
            "tickfont": {"size": 10, "color": "#c9b5ff"},
        },
        legend={"orientation": "h", "x": 0, "y": 1.16, "font": {"size": 9}, "bgcolor": "rgba(2, 6, 23, 0)"},
    )
    return figure


def build_steo_gas_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    steo = (snapshot or {}).get("eia_gas", {}).get("steo", {})
    series = steo.get("series", [])
    if not series:
        return _blank_figure("Waiting for EIA STEO")

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=[point["period"] for point in series],
            y=[point.get("henry_hub_usd_mmbtu") for point in series],
            mode="lines",
            name="Henry Hub",
            line={"color": "#facc15", "width": 2.8, "shape": "spline", "smoothing": 0.35},
            fill="tozeroy",
            fillcolor="rgba(250,204,21,.08)",
            hovertemplate="Henry Hub: $%{y:.2f}/MMBtu<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[point["period"] for point in series],
            y=[point.get("south_central_inventory_bcf") for point in series],
            mode="lines",
            name="SC Inventory",
            line={"color": "#a78bfa", "width": 2.3, "dash": "dot", "shape": "spline", "smoothing": 0.35},
            yaxis="y2",
            hovertemplate="Inventory: %{y:,.0f} Bcf<extra></extra>",
        )
    )
    figure = _apply_chart_layout(figure, height=322, y_prefix="$", uirevision="eia-steo")
    figure.update_layout(
        yaxis2={
            "overlaying": "y",
            "side": "right",
            "ticksuffix": " Bcf",
            "gridcolor": "rgba(0,0,0,0)",
            "zeroline": False,
            "tickfont": {"size": 10, "color": "#c9b5ff"},
        }
    )
    return figure


def build_degree_day_chart(snapshot: dict[str, Any] | None) -> go.Figure:
    climate = (snapshot or {}).get("climate", {})
    rows = climate.get("rows", [])
    if not rows:
        return _blank_figure("Waiting for CPC degree-day forecast")

    figure = go.Figure()
    x_values = [row["period"] for row in rows]
    hdd_means = [float(row["heating_degree_days"]["mean"]) for row in rows]
    cdd_means = [float(row["cooling_degree_days"]["mean"]) for row in rows]
    net_position = [round(hdd - cdd, 1) for hdd, cdd in zip(hdd_means, cdd_means)]
    figure.add_trace(
        go.Bar(
            x=x_values,
            y=hdd_means,
            name="HDD mean",
            marker={"color": "#38bdf8", "line": {"color": "rgba(226,232,240,.18)", "width": 1}},
            hovertemplate="HDD mean: %{y:,.0f}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Bar(
            x=x_values,
            y=[-value for value in cdd_means],
            name="CDD mean",
            marker={"color": "#fb923c", "line": {"color": "rgba(226,232,240,.16)", "width": 1}},
            customdata=cdd_means,
            hovertemplate="CDD mean: %{customdata:,.0f}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=x_values,
            y=net_position,
            mode="lines+markers",
            name="Net climate position",
            line={"color": "#e8eef7", "width": 2.6, "shape": "spline", "smoothing": 0.35},
            marker={"size": 6, "color": "#05070b", "line": {"color": "#e8eef7", "width": 1.6}},
            hovertemplate="Net climate position: %{y:+,.0f}<extra></extra>",
        )
    )
    figure = _apply_chart_layout(figure, height=292, barmode="relative", uirevision="cpc-degree-days")
    figure.update_layout(
        yaxis={
            "title": "",
            "gridcolor": "rgba(148,163,184,.14)",
            "zeroline": True,
            "zerolinecolor": "rgba(248,250,252,.32)",
            "zerolinewidth": 1.2,
            "tickformat": ",.0f",
        },
    )
    return figure


def build_grid_map(snapshot: dict[str, Any] | None) -> list[Any]:
    layers: list[Any] = [_leaflet_tile_layer()]
    if not snapshot:
        return layers

    load_zones = _ercot_load_zones_geojson()
    zone_names = _load_zone_names(load_zones)
    zone_metrics = _load_zone_metrics_by_name(snapshot.get("ercot", {}))
    z_key = "price_usd_mwh" if any(_is_number(zone.get("price_usd_mwh")) for zone in zone_metrics.values()) else "stress"
    z_values = [_zone_optional_numeric(zone_metrics.get(name, {}), z_key) for name in zone_names]
    zmin, zmax = _z_range([value for value in z_values if value is not None])

    layers.extend(_load_zone_leaflet_layers(load_zones, zone_metrics, z_key, zmin, zmax))
    if z_key == "price_usd_mwh":
        layers.extend(_load_zone_lmp_markers(zone_names, zone_metrics, _load_zone_label_positions(load_zones)))
    layers.extend(_weather_leaflet_markers(snapshot))
    layers.append(_leaflet_colorbar(z_key, zmin, zmax))
    return layers


def _leaflet_tile_layer() -> dl.TileLayer:
    return dl.TileLayer(url=GRID_MAP_TILE_URL, attribution=GRID_MAP_TILE_ATTRIBUTION, maxZoom=18)


def _load_zone_leaflet_layers(
    load_zones: dict[str, Any],
    zone_metrics: dict[str, dict[str, Any]],
    z_key: str,
    zmin: float,
    zmax: float,
) -> list[dl.GeoJSON]:
    layers = []
    for feature in load_zones.get("features", []):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        zone_name = str(properties.get("NAME") or "")
        if not zone_name:
            continue
        metrics = zone_metrics.get(zone_name, {})
        value = _zone_optional_numeric(metrics, z_key)
        layers.append(
            dl.GeoJSON(
                data={"type": "FeatureCollection", "features": [feature]},
                style=_load_zone_leaflet_style(value, zmin, zmax),
                hoverStyle={"weight": 2.3, "fillOpacity": 0.72},
                children=[_load_zone_leaflet_tooltip(zone_name, metrics)],
                id={"type": "load-zone-layer", "name": zone_name},
            )
        )
    return layers


def _load_zone_leaflet_style(value: float | None, zmin: float, zmax: float) -> dict[str, Any]:
    if value is None:
        return {
            "color": "rgba(148,163,184,0.42)",
            "weight": 1.1,
            "opacity": 0.82,
            "fillColor": "#334155",
            "fillOpacity": 0.28,
            "dashArray": "4 4",
        }

    return {
        "color": "rgba(226,232,240,0.62)",
        "weight": 1.35,
        "opacity": 0.9,
        "fillColor": _zone_fill_color(value, zmin, zmax),
        "fillOpacity": 0.56,
    }


def _load_zone_leaflet_tooltip(zone_name: str, metrics: dict[str, Any]) -> dl.Tooltip:
    zone, price, load, generation, stress, settlement = _load_zone_hover_data(zone_name, metrics)
    return dl.Tooltip(
        dash_html.Div(
            [
                dash_html.Strong(f"{zone} Load Zone"),
                dash_html.Div(f"RT LMP: {price}"),
                dash_html.Div(f"Load: {load}"),
                dash_html.Div(f"Generation: {generation}"),
                dash_html.Div(f"Stress: {stress}"),
                dash_html.Div(f"Settlement point: {settlement}", className="map-tooltip-muted"),
            ],
            className="map-tooltip-content",
        ),
        sticky=True,
        direction="top",
        className="map-tooltip",
    )


def _load_zone_lmp_markers(
    zone_names: list[str],
    zone_metrics: dict[str, dict[str, Any]],
    label_positions: dict[str, list[float]],
) -> list[dl.DivMarker]:
    markers = []
    for zone_name in zone_names:
        metrics = zone_metrics.get(zone_name, {})
        position = label_positions.get(zone_name)
        if position is None:
            continue
        price = metrics.get("price_usd_mwh")
        price_text = _format_price_label(price)
        marker_state = "available" if _is_number(price) else "missing"
        markers.append(
            dl.DivMarker(
                position=position,
                iconOptions={
                    "html": _load_zone_lmp_marker_html(zone_name, price_text, marker_state),
                    "className": "lmp-leaflet-label",
                    "iconSize": [86, 34],
                    "iconAnchor": [43, 17],
                },
                interactive=False,
                id={"type": "load-zone-lmp-label", "name": zone_name},
            )
        )
    return markers


def _load_zone_label_positions(load_zones: dict[str, Any]) -> dict[str, list[float]]:
    positions = {}
    for feature in load_zones.get("features", []):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        zone_name = str(properties.get("NAME") or "")
        position = _feature_label_position(feature)
        if zone_name and position:
            positions[zone_name] = position
    return positions


def _feature_label_position(feature: dict[str, Any]) -> list[float] | None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return None

    polygon = _largest_geometry_polygon(geometry)
    if not polygon:
        return None

    lon_lat = _polygon_centroid(polygon) or _polygon_bounds_center(polygon)
    return [lon_lat[1], lon_lat[0]] if lon_lat else None


def _largest_geometry_polygon(geometry: dict[str, Any]) -> list[Any] | None:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon" and isinstance(coordinates, list):
        return coordinates

    if geometry_type != "MultiPolygon" or not isinstance(coordinates, list):
        return None

    polygons = [polygon for polygon in coordinates if isinstance(polygon, list) and polygon]
    if not polygons:
        return None
    return max(polygons, key=_polygon_area)


def _polygon_area(polygon: list[Any]) -> float:
    exterior = polygon[0] if polygon else []
    return abs(_ring_signed_area(exterior))


def _polygon_centroid(polygon: list[Any]) -> tuple[float, float] | None:
    exterior = polygon[0] if polygon else []
    area = _ring_signed_area(exterior)
    if abs(area) < 1e-12:
        return None

    centroid = _ring_centroid(exterior, area)
    return centroid if centroid else None


def _ring_signed_area(ring: Any) -> float:
    points = _ring_points(ring)
    if len(points) < 3:
        return 0.0

    area = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        area += (x0 * y1) - (x1 * y0)
    return area / 2


def _ring_centroid(ring: Any, signed_area: float) -> tuple[float, float] | None:
    points = _ring_points(ring)
    if len(points) < 3:
        return None

    factor = 0.0
    x_total = 0.0
    y_total = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        cross = (x0 * y1) - (x1 * y0)
        factor += cross
        x_total += (x0 + x1) * cross
        y_total += (y0 + y1) * cross

    if abs(factor) < 1e-12:
        return None
    return x_total / (6 * signed_area), y_total / (6 * signed_area)


def _polygon_bounds_center(polygon: list[Any]) -> tuple[float, float] | None:
    points = _ring_points(polygon[0] if polygon else [])
    if not points:
        return None
    lon_values = [point[0] for point in points]
    lat_values = [point[1] for point in points]
    return (min(lon_values) + max(lon_values)) / 2, (min(lat_values) + max(lat_values)) / 2


def _ring_points(ring: Any) -> list[tuple[float, float]]:
    if not isinstance(ring, list):
        return []

    points = []
    for point in ring:
        if (
            isinstance(point, list | tuple)
            and len(point) >= 2
            and _is_number(point[0])
            and _is_number(point[1])
        ):
            points.append((float(point[0]), float(point[1])))
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


def _load_zone_lmp_marker_html(zone_name: str, price_text: str, marker_state: str) -> str:
    zone = html_lib.escape(zone_name)
    price = html_lib.escape(price_text)
    state = html_lib.escape(marker_state)
    return (
        f'<div class="lmp-marker lmp-marker-{state}" aria-label="{zone} RT LMP {price}">'
        f'<span class="lmp-marker-zone">{zone}</span>'
        f'<span class="lmp-marker-price">{price}</span>'
        "</div>"
    )


def _weather_leaflet_markers(snapshot: dict[str, Any]) -> list[dl.DivMarker]:
    noaa = snapshot.get("noaa", {})
    airports = [
        airport
        for airport in noaa.get("airports", [])
        if isinstance(airport, dict) and airport.get("lat") is not None and airport.get("lon") is not None
    ]
    markers = []
    for airport in airports:
        condition = _weather_condition(airport)
        temperature = _weather_temperature(airport, noaa)
        markers.append(
            dl.DivMarker(
                position=[airport["lat"], airport["lon"]],
                iconOptions={
                    "html": _weather_marker_html(airport, condition),
                    "className": "weather-leaflet-icon",
                    "iconSize": [38, 38],
                    "iconAnchor": [19, 19],
                    "popupAnchor": [0, -19],
                },
                title=f"{airport.get('airport', '')} {condition['label']}",
                children=[_weather_leaflet_tooltip(airport, condition, temperature)],
                id={"type": "weather-marker", "airport": str(airport.get("airport") or "")},
            )
        )
    return markers


def _weather_marker_html(airport: dict[str, Any], condition: dict[str, str]) -> str:
    airport_code = html_lib.escape(str(airport.get("airport") or "WX"))
    icon_name = html_lib.escape(condition["icon"])
    label = html_lib.escape(condition["label"])
    color = html_lib.escape(condition["color"])
    return (
        f'<div class="weather-marker weather-marker-{icon_name}" '
        f'style="--weather-color: {color};" aria-label="{label} at {airport_code}">'
        f'<span class="weather-marker-glyph" aria-hidden="true">{_weather_icon_svg(condition["icon"])}</span>'
        f'<span class="weather-marker-code">{airport_code}</span>'
        "</div>"
    )


def _weather_icon_svg(icon_name: str) -> str:
    paths = WEATHER_SVG_ICONS.get(icon_name, WEATHER_SVG_ICONS["cloud"])
    return (
        '<svg class="weather-marker-svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
        f"{paths}</svg>"
    )


def _weather_leaflet_tooltip(
    airport: dict[str, Any],
    condition: dict[str, str],
    temperature: float,
) -> dl.Tooltip:
    airport_code = str(airport.get("airport") or "")
    name = str(airport.get("name") or airport_code)
    wind = _weather_number(airport.get("wind_speed_mph"))
    high = _weather_number(airport.get("daily_high_f") or airport.get("temperature_f"))
    description = str(airport.get("description") or condition["label"])
    source = str(airport.get("source") or "")
    return dl.Tooltip(
        dash_html.Div(
            [
                dash_html.Strong(f"{name} ({airport_code})"),
                dash_html.Div(f"Condition: {condition['label']} ({description})"),
                dash_html.Div(f"Temp: {temperature:.1f} F"),
                dash_html.Div(f"Wind: {wind:.1f} mph"),
                dash_html.Div(f"24h high: {high:.1f} F"),
                dash_html.Div(f"Source: {source}", className="map-tooltip-muted"),
            ],
            className="map-tooltip-content",
        ),
        sticky=True,
        direction="top",
        className="map-tooltip",
    )


def _leaflet_colorbar(z_key: str, zmin: float, zmax: float) -> dl.Colorbar:
    ticks = _colorbar_ticks(zmin, zmax)
    is_price = z_key == "price_usd_mwh"
    return dl.Colorbar(
        colorscale=["#16a34a", "#facc15", "#ef4444"],
        min=round(zmin, 2),
        max=round(zmax, 2),
        width=14,
        height=142,
        nTicks=len(ticks),
        tickValues=ticks,
        tickText=[f"${tick:,.0f}" if is_price else f"{tick:,.0f}" for tick in ticks],
        opacity=0.92,
        position="bottomright",
        className="map-colorbar",
        tooltip="RT LMP" if is_price else "Stress",
    )


def _colorbar_ticks(zmin: float, zmax: float) -> list[float]:
    if zmax <= zmin:
        return [round(zmin, 2)]
    step = (zmax - zmin) / 3
    return [round(zmin + step * index, 2) for index in range(4)]


def _zone_fill_color(value: float, zmin: float, zmax: float) -> str:
    if zmax <= zmin:
        ratio = 0
    else:
        ratio = min(1, max(0, (value - zmin) / (zmax - zmin)))

    if ratio <= 0.52:
        return _interpolate_hex("#16a34a", "#facc15", ratio / 0.52)
    return _interpolate_hex("#facc15", "#ef4444", (ratio - 0.52) / 0.48)


def _interpolate_hex(start: str, end: str, ratio: float) -> str:
    ratio = min(1, max(0, ratio))
    start_rgb = _hex_to_rgb(start)
    end_rgb = _hex_to_rgb(end)
    mixed = tuple(round(start_rgb[index] + (end_rgb[index] - start_rgb[index]) * ratio) for index in range(3))
    return _rgb_to_hex(mixed)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _rgb_to_hex(value: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*value)


@lru_cache(maxsize=1)
def _ercot_load_zones_geojson() -> dict[str, Any]:
    with ERCOT_LOAD_ZONES_ASSET.open(encoding="utf-8") as geojson_file:
        return json.load(geojson_file)


def _load_zone_names(load_zones: dict[str, Any]) -> list[str]:
    return [feature["properties"]["NAME"] for feature in load_zones.get("features", [])]


def _load_zone_metrics_by_name(ercot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    zones = ercot.get("load_zones") or ercot.get("regions") or []
    return {
        str(zone.get("name")): zone
        for zone in zones
        if isinstance(zone, dict) and zone.get("name")
    }


def _load_zone_hover_data(zone_name: str, metrics: dict[str, Any]) -> list[str]:
    return [
        zone_name,
        _format_price(metrics.get("price_usd_mwh")),
        _format_mw(metrics.get("load_mw")),
        _format_mw(metrics.get("generation_mw")),
        _format_decimal(metrics.get("stress")),
        str(metrics.get("settlement_point") or f"LZ_{zone_name.upper()}"),
    ]


def _zone_numeric(metrics: dict[str, Any], key: str) -> float:
    value = metrics.get(key)
    return float(value) if _is_number(value) else 0


def _zone_optional_numeric(metrics: dict[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    return float(value) if _is_number(value) else None


def _z_range(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0, 1
    lower = min(values)
    upper = max(values)
    if lower == upper:
        return max(0, lower - 5), upper + 5
    padding = (upper - lower) * 0.12
    return max(0, lower - padding), upper + padding


def _format_price(value: Any) -> str:
    return f"${float(value):,.2f}/MWh" if _is_number(value) else "N/A"


def _format_price_label(value: Any) -> str:
    return f"${float(value):,.2f}" if _is_number(value) else "N/A"


def _format_mw(value: Any) -> str:
    return f"{float(value):,.0f} MW" if _is_number(value) else "N/A"


def _format_decimal(value: Any) -> str:
    return f"{float(value):.1f}" if _is_number(value) else "N/A"


def _weather_condition(airport: dict[str, Any]) -> dict[str, str]:
    description = " ".join(str(airport.get("description") or "").lower().split())
    for tokens, icon, label, color in WEATHER_ICON_RULES:
        if any(token in description for token in tokens):
            return {"icon": icon, "label": label, "color": color}

    precipitation = airport.get("precipitation_in")
    if _is_number(precipitation) and float(precipitation) >= 0.01:
        return {"icon": "rain", "label": "Rainy", "color": "#38bdf8"}

    wind_speed = airport.get("wind_speed_mph")
    if _is_number(wind_speed) and float(wind_speed) >= 20:
        return {"icon": "wind", "label": "Windy", "color": "#2dd4bf"}

    temperature = airport.get("temperature_f")
    if _is_number(temperature) and float(temperature) >= 82:
        return {"icon": "sun", "label": "Sunny", "color": "#fb923c"}

    return {"icon": "cloud", "label": "Cloudy", "color": "#cbd5e1"}


def _weather_temperature(airport: dict[str, Any], noaa: dict[str, Any]) -> float:
    value = airport.get("temperature_f")
    if _is_number(value):
        return float(value)

    fallback = noaa.get("temperature_f")
    return float(fallback) if _is_number(fallback) else 0.0


def _weather_number(value: Any) -> float:
    return float(value) if _is_number(value) else 0.0


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float)


def _load_zone_colorscale(zone_names: list[str]) -> list[list[float | str]]:
    if not zone_names:
        return [[0, "rgba(34, 211, 238, 0.18)"], [1, "rgba(34, 211, 238, 0.18)"]]

    if len(zone_names) == 1:
        color = ERCOT_LOAD_ZONE_COLORS.get(zone_names[0], "#38bdf8")
        return [[0, color], [1, color]]

    color_stops: list[list[float | str]] = []
    divisor = len(zone_names) - 1
    for index, zone_name in enumerate(zone_names):
        color_stops.append([index / divisor, ERCOT_LOAD_ZONE_COLORS.get(zone_name, "#38bdf8")])
    return color_stops


def build_fuel_mix(snapshot: dict[str, Any] | None) -> go.Figure:
    if not snapshot:
        return _blank_figure("Waiting for EIA fuel mix")

    fuel_mix = snapshot["eia"]["fuel_mix"]
    labels = list(fuel_mix.keys())
    values = list(fuel_mix.values())
    figure = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker={
                "color": ["#22c55e", "#38bdf8", "#facc15", "#fb923c", "#a78bfa", "#94a3b8"][: len(labels)],
                "line": {"color": "rgba(248,250,252,.18)", "width": 1},
            },
            hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
        )
    )
    figure.update_layout(
        height=260,
        margin={"l": 98, "r": 20, "t": 12, "b": 30},
        xaxis={
            "title": "",
            "ticksuffix": "%",
            "gridcolor": "rgba(148,163,184,.16)",
            "zerolinecolor": "rgba(148,163,184,.2)",
            "range": [0, max(values) * 1.18 if values else 100],
        },
        yaxis={"autorange": "reversed", "tickfont": {"size": 11}},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#dbeafe"},
        hoverlabel=DARK_HOVERLABEL,
        bargap=0.28,
    )
    return figure


def _sparkline_base() -> go.Figure:
    figure = go.Figure()
    figure.update_layout(
        height=108,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"visible": False, "fixedrange": True},
        yaxis={"visible": False, "fixedrange": True},
        showlegend=False,
    )
    return figure


def _rgba(hex_color: str, alpha: float) -> str:
    color = hex_color.lstrip("#")
    red = int(color[0:2], 16)
    green = int(color[2:4], 16)
    blue = int(color[4:6], 16)
    return f"rgba({red},{green},{blue},{alpha})"


def _pretty_key(value: str) -> str:
    return value.replace("_", " ").title()


def _timestamp_date(value: Any) -> str | None:
    if not value:
        return None

    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass

    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _add_supply_line(
    figure: go.Figure,
    points: list[dict[str, Any]],
    *,
    key: str,
    name: str,
    color: str,
    dash: str = "solid",
    width: float = 2.6,
) -> None:
    values = [(point.get("timestamp"), point.get(key)) for point in points if point.get(key) is not None]
    if not values:
        return
    x_values, y_values = zip(*values)
    figure.add_trace(
        go.Scatter(
            x=list(x_values),
            y=list(y_values),
            mode="lines",
            name=name,
            line={"color": color, "width": width, "dash": dash, "shape": "spline", "smoothing": 0.35},
            hovertemplate=f"{name}: %{{y:,.0f}} MW<extra></extra>",
        )
    )


def _add_trend_line(
    figure: go.Figure,
    points: list[dict[str, Any]],
    name: str,
    color: str,
    *,
    width: float = 2.4,
) -> None:
    if not points:
        return

    actual = [point for point in points if not point.get("is_forecast")]
    forecast = [point for point in points if point.get("is_forecast")]
    bridge = actual[-1:] if actual and forecast else []

    if actual:
        figure.add_trace(
            go.Scatter(
                x=[point.get("timestamp") for point in actual],
                y=[point.get("value") for point in actual],
                mode="lines",
                name=name,
                line={"color": color, "width": width, "shape": "spline", "smoothing": 0.35},
                hovertemplate=f"{name}: %{{y:,.0f}} MW<extra></extra>",
            )
        )
    if forecast:
        forecast_points = [*bridge, *forecast]
        figure.add_trace(
            go.Scatter(
                x=[point.get("timestamp") for point in forecast_points],
                y=[point.get("value") for point in forecast_points],
                mode="lines",
                name=f"{name} Forecast",
                line={"color": color, "width": max(1.8, width - 0.2), "dash": "dot", "shape": "spline", "smoothing": 0.35},
                hovertemplate=f"{name} forecast: %{{y:,.0f}} MW<extra></extra>",
            )
        )


def _dashboard_actual_forecast_series(
    rows: list[dict[str, Any]],
    actual_key: str,
    forecast_key: str,
) -> list[dict[str, Any]]:
    actual_points = [
        {
            "timestamp": row.get("timestamp", ""),
            "value": round(float(row[actual_key]), 2),
            "_parsed": _parse_figure_datetime(row.get("timestamp")),
        }
        for row in rows
        if _is_number(row.get(actual_key))
    ]
    latest_actual_time = max((point["_parsed"] for point in actual_points if point["_parsed"] is not None), default=None)

    series = [{key: value for key, value in point.items() if key != "_parsed"} for point in actual_points]
    for row in rows:
        timestamp = row.get("timestamp", "")
        parsed = _parse_figure_datetime(timestamp)
        if latest_actual_time and parsed and parsed <= latest_actual_time:
            continue
        if _is_number(row.get(forecast_key)):
            series.append(
                {
                    "timestamp": timestamp,
                    "value": round(float(row[forecast_key]), 2),
                    "is_forecast": True,
                }
            )
    return series


def _current_day_axis_range(rows: list[dict[str, Any]]) -> list[str] | None:
    parsed = [_parse_figure_datetime(row.get("timestamp")) for row in rows]
    parsed = [value for value in parsed if value is not None]
    if not parsed:
        return None
    operating_day = min(parsed).date()
    tz = parsed[0].tzinfo
    start = datetime.combine(operating_day, datetime.min.time(), tzinfo=tz)
    return [start.isoformat(), (start + timedelta(days=1)).isoformat()]


def _parse_figure_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _apply_chart_layout(
    figure: go.Figure,
    *,
    height: int,
    y_suffix: str = "",
    y_prefix: str = "",
    barmode: str | None = None,
    uirevision: str,
) -> go.Figure:
    layout: dict[str, Any] = {
        "height": height,
        "margin": {"l": 46, "r": 18, "t": 8, "b": 38},
        "hovermode": "x unified",
        "hoverlabel": DARK_HOVERLABEL,
        "legend": {
            "orientation": "h",
            "x": 0,
            "y": 1.12,
            "font": {"size": 10},
            "bgcolor": "rgba(2, 6, 23, 0)",
        },
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(2,6,23,.24)",
        "font": {"color": "#dbeafe"},
        "xaxis": {
            "title": "",
            "gridcolor": "rgba(148,163,184,.1)",
            "showline": False,
            "tickfont": {"size": 10},
        },
        "yaxis": {
            "title": "",
            "ticksuffix": y_suffix,
            "tickprefix": y_prefix,
            "tickformat": ",.0f" if not y_prefix else ",.2f",
            "gridcolor": "rgba(148,163,184,.14)",
            "zeroline": False,
            "tickfont": {"size": 10},
        },
        "uirevision": uirevision,
    }
    if barmode:
        layout["barmode"] = barmode
    figure.update_layout(**layout)
    return figure


def _blank_figure(message: str) -> go.Figure:
    figure = go.Figure()
    figure.add_annotation(text=message, x=0.5, y=0.5, showarrow=False, font={"color": "#94a3b8"})
    figure.update_layout(
        height=520,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"visible": False},
        yaxis={"visible": False},
    )
    return figure

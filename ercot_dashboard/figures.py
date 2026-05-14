from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import plotly.graph_objects as go

ERCOT_LOAD_ZONES_ASSET = Path(__file__).parent / "assets" / "ERCOT_Load_Zones.geojson"
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
DARK_HOVERLABEL = {
    "bgcolor": "rgba(8, 13, 23, 0.96)",
    "bordercolor": "rgba(34, 211, 238, 0.32)",
    "font": {"color": "#e8eef7", "size": 12},
    "namelength": -1,
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
    figure.add_trace(
        go.Scatter(
            x=[point["period"] for point in series],
            y=[point.get("lower_48_bcf") for point in series],
            mode="lines",
            name="Lower 48",
            line={"color": "#38bdf8", "width": 2.3},
            hovertemplate="Lower 48: %{y:,.0f} Bcf<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[point["period"] for point in series],
            y=[point.get("south_central_bcf") for point in series],
            mode="lines",
            name="South Central",
            line={"color": "#22c55e", "width": 2.3},
            yaxis="y2",
            hovertemplate="South Central: %{y:,.0f} Bcf<extra></extra>",
        )
    )
    figure = _apply_chart_layout(figure, height=292, y_suffix=" Bcf", uirevision="eia-storage")
    figure.update_layout(
        yaxis2={
            "overlaying": "y",
            "side": "right",
            "ticksuffix": " Bcf",
            "gridcolor": "rgba(0,0,0,0)",
            "zeroline": False,
            "tickfont": {"size": 10, "color": "#9be8b7"},
        }
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
            line={"color": "#facc15", "width": 2.4},
            hovertemplate="Henry Hub: $%{y:.2f}/MMBtu<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[point["period"] for point in series],
            y=[point.get("south_central_inventory_bcf") for point in series],
            mode="lines",
            name="SC Inventory",
            line={"color": "#a78bfa", "width": 2.1, "dash": "dot"},
            yaxis="y2",
            hovertemplate="Inventory: %{y:,.0f} Bcf<extra></extra>",
        )
    )
    figure = _apply_chart_layout(figure, height=292, y_prefix="$", uirevision="eia-steo")
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


def build_grid_map(snapshot: dict[str, Any] | None) -> go.Figure:
    if not snapshot:
        return _blank_figure("Waiting for FastAPI data")

    figure = go.Figure()
    load_zones = _ercot_load_zones_geojson()
    zone_names = _load_zone_names(load_zones)
    zone_metrics = _load_zone_metrics_by_name(snapshot.get("ercot", {}))
    z_key = "price_usd_mwh" if any(_is_number(zone.get("price_usd_mwh")) for zone in zone_metrics.values()) else "stress"
    z_values = [_zone_numeric(zone_metrics.get(name, {}), z_key) for name in zone_names]
    zmin, zmax = _z_range(z_values)
    figure.add_trace(
        go.Choroplethmapbox(
            geojson=load_zones,
            locations=zone_names,
            featureidkey="properties.NAME",
            z=z_values,
            zmin=zmin,
            zmax=zmax,
            colorscale=[
                [0.0, "#16a34a"],
                [0.52, "#facc15"],
                [1.0, "#ef4444"],
            ],
            marker={"line": {"color": "rgba(226, 232, 240, 0.58)", "width": 1.2}, "opacity": 0.54},
            customdata=[_load_zone_hover_data(name, zone_metrics.get(name, {})) for name in zone_names],
            hovertemplate=(
                "<b>%{customdata[0]} Load Zone</b><br>"
                "RT LMP: %{customdata[1]}<br>"
                "Load: %{customdata[2]}<br>"
                "Generation: %{customdata[3]}<br>"
                "Stress: %{customdata[4]}<br>"
                "Settlement point: %{customdata[5]}<extra></extra>"
            ),
            colorbar={
                "title": {"text": "RT LMP" if z_key == "price_usd_mwh" else "Stress", "font": {"color": "#d9e2ef"}},
                "thickness": 12,
                "tickfont": {"color": "#d9e2ef"},
                "tickprefix": "$" if z_key == "price_usd_mwh" else "",
            },
            name="Load zone operations",
            showlegend=False,
            showscale=True,
        )
    )

    airports = [
        airport
        for airport in snapshot.get("noaa", {}).get("airports", [])
        if airport.get("lat") is not None and airport.get("lon") is not None
    ]
    if airports:
        temperatures = [airport.get("temperature_f") or snapshot["noaa"]["temperature_f"] for airport in airports]
        figure.add_trace(
            go.Scattermapbox(
                lat=[airport["lat"] for airport in airports],
                lon=[airport["lon"] for airport in airports],
                mode="markers+text",
                text=[airport["airport"] for airport in airports],
                textposition="bottom center",
                textfont={"color": "#bae6fd", "size": 10},
                customdata=[
                    [
                        airport.get("name", airport["airport"]),
                        airport.get("wind_speed_mph", 0),
                        airport.get("daily_high_f") or airport.get("temperature_f") or 0,
                        airport.get("source", ""),
                    ]
                    for airport in airports
                ],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Temp: %{marker.color:.1f} F<br>"
                    "Wind: %{customdata[1]:.1f} mph<br>"
                    "24h high: %{customdata[2]:.1f} F<br>"
                    "Source: %{customdata[3]}<extra></extra>"
                ),
                marker={
                    "size": 12,
                    "color": temperatures,
                    "cmin": 55,
                    "cmax": 108,
                    "colorscale": [
                        [0.0, "#38bdf8"],
                        [0.5, "#facc15"],
                        [1.0, "#fb7185"],
                    ],
                    "opacity": 0.88,
                    "showscale": False,
                },
                name="Weather nodes",
            )
        )

    figure.update_layout(
        mapbox={
            "style": "carto-darkmatter",
            "center": {"lat": 31.0, "lon": -99.2},
            "zoom": 4.75,
        },
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#e8eef7"},
        hoverlabel=DARK_HOVERLABEL,
        height=520,
        legend={
            "orientation": "h",
            "x": 0.02,
            "y": 0.98,
            "bgcolor": "rgba(2, 6, 23, 0.55)",
            "font": {"size": 11},
        },
        uirevision="ercot-map",
    )
    return figure


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


def _format_mw(value: Any) -> str:
    return f"{float(value):,.0f} MW" if _is_number(value) else "N/A"


def _format_decimal(value: Any) -> str:
    return f"{float(value):.1f}" if _is_number(value) else "N/A"


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

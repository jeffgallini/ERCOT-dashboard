from __future__ import annotations

import asyncio

from ercot_dashboard.figures import (
    _ercot_load_zones_geojson,
    _load_zone_names,
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
from ercot_dashboard.services.dashboard import get_dashboard_snapshot


def test_ercot_load_zones_asset_has_expected_zones() -> None:
    load_zones = _ercot_load_zones_geojson()

    assert _load_zone_names(load_zones) == ["Houston", "North", "South", "West"]
    assert all(feature["geometry"]["type"] in {"Polygon", "MultiPolygon"} for feature in load_zones["features"])


def test_grid_map_renders_ercot_load_zones_geojson() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    figure = build_grid_map(snapshot)
    zone_trace = figure.data[0]

    assert zone_trace.type == "choroplethmapbox"
    assert zone_trace.name == "Load zone operations"
    assert zone_trace.featureidkey == "properties.NAME"
    assert list(zone_trace.locations) == ["Houston", "North", "South", "West"]
    assert "RT LMP" in zone_trace.hovertemplate
    assert "Load: %{customdata[2]}" in zone_trace.hovertemplate
    assert "Generation: %{customdata[3]}" in zone_trace.hovertemplate
    assert list(zone_trace.customdata[0])[:4] == [
        "Houston",
        f"${snapshot['ercot']['load_zones'][0]['price_usd_mwh']:,.2f}/MWh",
        f"{snapshot['ercot']['load_zones'][0]['load_mw']:,.0f} MW",
        f"{snapshot['ercot']['load_zones'][0]['generation_mw']:,.0f} MW",
    ]
    assert [feature["properties"]["NAME"] for feature in zone_trace.geojson["features"]] == [
        "Houston",
        "North",
        "South",
        "West",
    ]
    assert "Regional stress" not in [trace.name for trace in figure.data]
    assert any(trace.name == "Weather nodes" and "markers" in trace.mode for trace in figure.data)
    assert figure.layout.hoverlabel.bgcolor == "rgba(8, 13, 23, 0.96)"


def test_new_dashboard_replica_figures_render_demo_data() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    builders = [
        build_prc_chart,
        build_ercot_fuel_stack,
        build_storage_chart,
        build_outages_chart,
        build_ancillary_chart,
        build_eia_gas_storage_chart,
        build_steo_gas_chart,
        build_degree_day_chart,
    ]

    for builder in builders:
        figure = builder(snapshot)
        assert len(figure.data) >= 1
        assert figure.layout.height
        assert figure.layout.hoverlabel.bgcolor == "rgba(8, 13, 23, 0.96)"


def test_generation_fuel_mix_chart_only_plots_latest_day() -> None:
    snapshot = {
        "ercot_dashboards": {
            "fuel_mix": {
                "latest": {"mix": [{"fuel": "Natural Gas"}, {"fuel": "Wind"}]},
                "series": [
                    {
                        "timestamp": "2026-05-12T23:55:00-05:00",
                        "fuels": {"Natural Gas": 100, "Wind": 20},
                    },
                    {
                        "timestamp": "2026-05-13T00:00:00-05:00",
                        "fuels": {"Natural Gas": 110, "Wind": 25},
                    },
                    {
                        "timestamp": "2026-05-13T00:05:00-05:00",
                        "fuels": {"Natural Gas": 120, "Wind": 30},
                    },
                ],
            }
        }
    }

    figure = build_ercot_fuel_stack(snapshot)

    assert len(figure.data) == 2
    for trace in figure.data:
        assert list(trace.x) == ["2026-05-13T00:00:00-05:00", "2026-05-13T00:05:00-05:00"]


def test_system_price_chart_draws_rt_smooth_and_da_step_line() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))
    snapshot["ercot"]["status"] = {"source": "ERCOT", "state": "live", "message": ""}
    snapshot["ercot"]["price_status"] = {"source": "ERCOT RT/DA LMP", "state": "live", "message": ""}

    figure = build_system_price_chart(snapshot)

    assert [trace.name for trace in figure.data] == ["RT LMP", "DA LMP"]
    assert figure.data[0].line.shape == "spline"
    assert figure.data[1].line.shape == "hv"
    assert figure.layout.yaxis.tickprefix == "$"
    assert figure.layout.yaxis.ticksuffix == "/MWh"


def test_system_price_chart_does_not_plot_demo_prices_as_api_data() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    figure = build_system_price_chart(snapshot)

    assert not figure.data
    assert figure.layout.annotations[0].text == "ERCOT price API unavailable"


def test_system_price_chart_uses_price_status_not_broad_ercot_status() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))
    snapshot["ercot"]["status"] = {"source": "ERCOT", "state": "demo", "message": "grid fallback"}
    snapshot["ercot"]["price_status"] = {"source": "ERCOT RT/DA LMP", "state": "live", "message": ""}

    figure = build_system_price_chart(snapshot)

    assert [trace.name for trace in figure.data] == ["RT LMP", "DA LMP"]


def test_kpi_sparkline_draws_transparent_actual_and_dotted_forecast() -> None:
    figure = build_kpi_sparkline(
        [
            {"timestamp": "2026-05-13T10:00:00-05:00", "value": 10},
            {"timestamp": "2026-05-13T11:00:00-05:00", "value": 12},
            {"timestamp": "2026-05-13T12:00:00-05:00", "value": 14, "is_forecast": True},
            {"timestamp": "2026-05-13T13:00:00-05:00", "value": 15, "is_forecast": True},
        ],
        color="cyan",
    )

    assert len(figure.data) == 2
    assert figure.data[0].line.color == "rgba(34,211,238,0.42)"
    assert figure.data[0].line.dash == "solid"
    assert figure.data[1].line.color == "rgba(34,211,238,0.9)"
    assert figure.data[1].line.dash == "dot"
    assert list(figure.data[1].x) == [
        "2026-05-13T11:00:00-05:00",
        "2026-05-13T12:00:00-05:00",
        "2026-05-13T13:00:00-05:00",
    ]


def test_degree_day_chart_shows_hdd_up_cdd_down_and_net_line() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    figure = build_degree_day_chart(snapshot)

    assert [trace.name for trace in figure.data] == ["HDD mean", "CDD mean", "Net climate position"]
    assert all(value >= 0 for value in figure.data[0].y)
    assert all(value <= 0 for value in figure.data[1].y)
    expected_net = [
        round(row["heating_degree_days"]["mean"] - row["cooling_degree_days"]["mean"], 1)
        for row in snapshot["climate"]["rows"]
    ]
    assert list(figure.data[2].y) == expected_net


def test_standalone_figures_use_dark_hoverlabels() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    for builder in (build_supply_demand_chart, build_fuel_mix):
        figure = builder(snapshot)
        assert figure.layout.hoverlabel.bgcolor == "rgba(8, 13, 23, 0.96)"
        assert figure.layout.hoverlabel.font.color == "#e8eef7"

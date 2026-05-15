from __future__ import annotations

import asyncio

import dash_leaflet as dl

from ercot_dashboard.figures import (
    _ercot_load_zones_geojson,
    _load_zone_label_positions,
    _load_zone_names,
    build_ancillary_chart,
    build_combined_renewables_chart,
    build_dc_tie_flows_chart,
    build_degree_day_chart,
    build_eia_gas_balance_chart,
    build_eia_gas_storage_chart,
    build_ercot_fuel_stack,
    build_fuel_mix,
    build_grid_map,
    build_kpi_sparkline,
    build_load_zone_price_chart,
    build_outages_chart,
    build_prc_chart,
    build_steo_gas_chart,
    build_storage_chart,
    build_system_demand_chart,
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

    layers = build_grid_map(snapshot)
    zone_layers = [layer for layer in layers if isinstance(layer, dl.GeoJSON)]
    weather_markers = _markers_by_type(layers, "weather-marker")
    lmp_labels = _markers_by_type(layers, "load-zone-lmp-label")
    colorbar = next(layer for layer in layers if isinstance(layer, dl.Colorbar))

    assert isinstance(layers[0], dl.TileLayer)
    assert [layer.data["features"][0]["properties"]["NAME"] for layer in zone_layers] == [
        "Houston",
        "North",
        "South",
        "West",
    ]
    assert zone_layers[0].style["fillOpacity"] == 0.56
    assert zone_layers[0].style["fillColor"].startswith("#")
    assert _component_text(zone_layers[0]) == (
        "Houston Load Zone "
        f"RT LMP: ${snapshot['ercot']['load_zones'][0]['price_usd_mwh']:,.2f}/MWh "
        f"Load: {snapshot['ercot']['load_zones'][0]['load_mw']:,.0f} MW "
        f"Generation: {snapshot['ercot']['load_zones'][0]['generation_mw']:,.0f} MW "
        f"Stress: {snapshot['ercot']['load_zones'][0]['stress']:.1f} "
        "Settlement point: LZ_HOUSTON"
    )
    assert len(weather_markers) == snapshot["noaa"]["airport_count"]
    assert [label.id["name"] for label in lmp_labels] == ["Houston", "North", "South", "West"]
    assert "$" in lmp_labels[0].iconOptions["html"]
    label_positions = _load_zone_label_positions(_ercot_load_zones_geojson())
    assert [label.position for label in lmp_labels] == [
        label_positions["Houston"],
        label_positions["North"],
        label_positions["South"],
        label_positions["West"],
    ]
    assert lmp_labels[0].position != [
        snapshot["ercot"]["load_zones"][0]["lat"],
        snapshot["ercot"]["load_zones"][0]["lon"],
    ]
    assert colorbar.colorscale == ["#16a34a", "#facc15", "#ef4444"]
    assert colorbar.tickText[0].startswith("$")


def test_grid_map_weather_layer_uses_condition_icons() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))
    snapshot["noaa"]["airports"] = [
        {
            "airport": "RAIN",
            "name": "Rain Station",
            "lat": 32.0,
            "lon": -96.0,
            "temperature_f": 70,
            "daily_high_f": 74,
            "wind_speed_mph": 8,
            "precipitation_in": 0.05,
            "description": "Light Rain",
            "source": "test",
        },
        {
            "airport": "SUN",
            "name": "Sun Station",
            "lat": 31.5,
            "lon": -97.0,
            "temperature_f": 90,
            "daily_high_f": 96,
            "wind_speed_mph": 6,
            "precipitation_in": 0,
            "description": "Clear",
            "source": "test",
        },
        {
            "airport": "WIND",
            "name": "Wind Station",
            "lat": 31.0,
            "lon": -98.0,
            "temperature_f": 76,
            "daily_high_f": 80,
            "wind_speed_mph": 28,
            "precipitation_in": 0,
            "description": "Windy",
            "source": "test",
        },
        {
            "airport": "SNOW",
            "name": "Snow Station",
            "lat": 30.5,
            "lon": -99.0,
            "temperature_f": 31,
            "daily_high_f": 34,
            "wind_speed_mph": 12,
            "precipitation_in": 0,
            "description": "Snow",
            "source": "test",
        },
        {
            "airport": "CLD",
            "name": "Cloud Station",
            "lat": 30.0,
            "lon": -100.0,
            "temperature_f": 68,
            "daily_high_f": 72,
            "wind_speed_mph": 10,
            "precipitation_in": 0,
            "description": "Mostly Cloudy",
            "source": "test",
        },
    ]

    layers = build_grid_map(snapshot)
    weather_markers = _markers_by_type(layers, "weather-marker")

    assert [marker.id["airport"] for marker in weather_markers] == ["RAIN", "SUN", "WIND", "SNOW", "CLD"]
    assert [f"weather-marker-{name}" in marker.iconOptions["html"] for name, marker in zip(["rain", "sun", "wind", "snow", "cloud"], weather_markers)] == [
        True,
        True,
        True,
        True,
        True,
    ]
    assert all("weather-marker-svg" in marker.iconOptions["html"] for marker in weather_markers)
    assert [_weather_label(marker) for marker in weather_markers] == ["Rainy", "Sunny", "Windy", "Snowy", "Cloudy"]
    assert _component_text(weather_markers[0]) == (
        "Rain Station (RAIN) "
        "Condition: Rainy (Light Rain) "
        "Temp: 70.0 F "
        "Wind: 8.0 mph "
        "24h high: 74.0 F "
        "Source: test"
    )
    assert weather_markers[0].iconOptions["className"] == "weather-leaflet-icon"
    assert weather_markers[0].iconOptions["iconSize"] == [38, 38]


def test_grid_map_does_not_treat_missing_lmp_as_zero() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))
    snapshot["ercot"]["load_zones"][0]["price_usd_mwh"] = None
    snapshot["ercot"]["regions"][0]["price_usd_mwh"] = None

    layers = build_grid_map(snapshot)
    zone_layers = [layer for layer in layers if isinstance(layer, dl.GeoJSON)]
    lmp_labels = _markers_by_type(layers, "load-zone-lmp-label")
    colorbar = next(layer for layer in layers if isinstance(layer, dl.Colorbar))

    assert zone_layers[0].style["fillColor"] == "#334155"
    assert zone_layers[0].style["dashArray"] == "4 4"
    assert "N/A" in lmp_labels[0].iconOptions["html"]
    assert "$0" not in colorbar.tickText


def _weather_label(marker: dl.DivMarker) -> str:
    text = _component_text(marker)
    return text.split("Condition: ", 1)[1].split(" (", 1)[0]


def _markers_by_type(layers: list[object], marker_type: str) -> list[dl.DivMarker]:
    return [
        layer
        for layer in layers
        if isinstance(layer, dl.DivMarker) and isinstance(layer.id, dict) and layer.id.get("type") == marker_type
    ]


def _component_text(component: object) -> str:
    if component is None:
        return ""
    if isinstance(component, str | int | float):
        return str(component)
    if isinstance(component, list | tuple):
        return " ".join(text for text in (_component_text(child) for child in component) if text)

    children = getattr(component, "children", None)
    return _component_text(children)


def test_new_dashboard_replica_figures_render_available_data() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    builders = [
        build_prc_chart,
        build_system_demand_chart,
        build_ercot_fuel_stack,
        build_storage_chart,
        build_combined_renewables_chart,
        build_outages_chart,
        build_ancillary_chart,
        build_load_zone_price_chart,
        build_eia_gas_storage_chart,
        build_eia_gas_balance_chart,
        build_steo_gas_chart,
        build_degree_day_chart,
    ]

    for builder in builders:
        figure = builder(snapshot)
        assert len(figure.data) >= 1
        assert figure.layout.height
        assert figure.layout.hoverlabel.bgcolor == "rgba(8, 13, 23, 0.96)"


def test_eia_gas_figures_render_new_balance_and_wells_sections() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    balance = build_eia_gas_balance_chart(snapshot)

    assert "Supply" in [trace.name for trace in balance.data]
    assert "Consumption" in [trace.name for trace in balance.data]
    assert "Working Inventory" in [trace.name for trace in balance.data]
    assert balance.layout.barmode == "relative"


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


def test_load_zone_price_chart_uses_ercot_zone_prices() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    figure = build_load_zone_price_chart(snapshot)

    assert figure.data[0].name == "RT LMP"
    assert list(figure.data[0].x) == ["Houston", "North", "South", "West"]
    assert figure.layout.yaxis.tickprefix == "$"
    assert figure.layout.yaxis.ticksuffix == "/MWh"


def test_combined_renewables_chart_draws_wind_solar_and_combined() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    figure = build_combined_renewables_chart(snapshot)

    assert "Wind Gen Hourly Avg" in [trace.name for trace in figure.data]
    assert "Wind Gen Hourly Avg Forecast" in [trace.name for trace in figure.data]
    assert "Solar Gen Hourly Avg" in [trace.name for trace in figure.data]
    assert "Solar Gen Hourly Avg Forecast" in [trace.name for trace in figure.data]
    assert "Combined Gen Hourly Avg" in [trace.name for trace in figure.data]
    assert "Combined Gen Hourly Avg Forecast" in [trace.name for trace in figure.data]
    assert "T00:00:00" in figure.layout.xaxis.range[0]
    assert "T00:00:00" in figure.layout.xaxis.range[1]


def test_dc_tie_flow_chart_waits_for_live_data_and_renders_series() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    blank = build_dc_tie_flows_chart(snapshot)
    assert not blank.data
    assert blank.layout.annotations[0].text == "Waiting for DC tie flows"

    snapshot["ercot_dashboards"]["dc_ties"] = {
        "series": {
            "North": [{"timestamp": "2026-05-13T09:00:00", "value": 100}],
            "East": [{"timestamp": "2026-05-13T09:00:00", "value": -50}],
            "Laredo": [{"timestamp": "2026-05-13T09:00:00", "value": 25}],
            "Railroad": [{"timestamp": "2026-05-13T09:00:00", "value": 10}],
        }
    }
    dc_ties = build_dc_tie_flows_chart(snapshot)

    assert [trace.name for trace in dc_ties.data] == ["North", "East", "Laredo", "Railroad"]
    assert dc_ties.layout.xaxis.range == ("2026-05-13T00:00:00", "2026-05-14T00:00:00")


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

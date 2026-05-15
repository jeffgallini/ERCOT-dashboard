from __future__ import annotations

import asyncio

import httpx

import ercot_dashboard.services.clients as clients_service
import ercot_dashboard.services.dashboard as dashboard_service
from ercot_dashboard.services.dashboard import get_dashboard_snapshot
from ercot_dashboard.services.clients import (
    NOAA_AIRPORT_STATIONS,
    ERCOT_CLIENT_ID,
    _ercot_auth_params,
    _ercot_headers,
    _ercot_now,
    _ercot_params,
    _ercot_payload_cache_key,
    _day_ahead_price_series,
    demo_eia_natural_gas,
    demo_eia_snapshot,
    demo_ercot_public_dashboards,
    demo_ercot_snapshot,
    demo_noaa_snapshot,
    demo_supply_demand_snapshot,
    _load_zone_lmp_params,
    _load_zone_lmp_response,
    _load_zone_metrics,
    _normalize_supply_demand_payload,
    _parse_cpc_degree_day_forecast,
    demo_cpc_degree_day_forecast,
    list_ercot_reports,
    _normalize_nws_airport_observation,
    _nws_headers,
    _nws_observation_url,
    _price_proxy,
    _report_rows,
    _rt_lmp_report_params,
    _rt_lmp_query_params,
)
from ercot_dashboard.services.events import clear_operator_events, create_operator_event


def _as_live(snapshot: dict) -> dict:
    updated = dict(snapshot)
    status = dict(updated.get("status") or {})
    status["state"] = "live"
    status["message"] = ""
    updated["status"] = status
    if isinstance(updated.get("price_status"), dict):
        updated["price_status"] = {**updated["price_status"], "state": "live", "message": ""}
    return updated


def test_demo_snapshot_has_required_sections() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    assert set(snapshot) >= {"ercot", "eia", "noaa", "metrics", "events", "fanout"}
    assert set(snapshot) >= {"supply_demand", "trends"}
    assert snapshot["fanout"]["strategy"] == "asyncio.gather"
    assert set(snapshot["fanout"]["source_latency_ms"]) >= {
        "ercot",
        "eia",
        "noaa",
        "supply_demand",
        "ercot_dashboards",
        "eia_gas",
        "cpc",
    }
    assert snapshot["metrics"]["stress_index"] >= 0
    assert snapshot["ercot"]["regions"]
    assert [zone["name"] for zone in snapshot["ercot"]["load_zones"]] == ["Houston", "North", "South", "West"]
    assert all(zone["price_usd_mwh"] is not None for zone in snapshot["ercot"]["load_zones"])
    assert snapshot["ercot"]["price_series"]["rt_lmp"]
    assert snapshot["ercot"]["price_series"]["da_lmp"]
    assert snapshot["supply_demand"]["current_day"]
    assert snapshot["trends"]["load_mw"]
    assert snapshot["trends"]["net_load_mw"]
    for key in ("load_mw", "net_load_mw"):
        assert any(point.get("is_forecast") for point in snapshot["trends"][key])
    assert snapshot["ercot_dashboards"]["prc"]["series"]
    assert snapshot["eia_gas"]["storage"]["series"]
    assert snapshot["eia_gas"]["balance"]["series"]
    assert snapshot["climate"]["rows"]
    assert snapshot["diagnostics"]["fuels"]
    assert snapshot["diagnostics"]["summary"]["dispatchable_outages_mw"] > 0
    assert any(signal["source"] == "ERCOT Fuel Mix" for signal in snapshot["diagnostics"]["signals"])
    assert set(snapshot["source_status"]) >= {"ercot_dashboards", "eia_gas", "cpc"}


def test_diagnostics_feed_includes_realtime_fuel_availability_proxy() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    natural_gas = next(row for row in snapshot["diagnostics"]["fuels"] if row["fuel"] == "Natural Gas")

    assert natural_gas["hsl_mw"] > natural_gas["generation_mw"]
    assert natural_gas["unavailable_mw"] > 0
    assert natural_gas["class"] == "dispatchable"
    assert any(event["title"] == "Natural Gas availability proxy" for event in snapshot["events"])


def test_fuel_mix_dashboard_preserves_hsl_and_capacity_for_diagnostics() -> None:
    payload = {
        "types": ["Natural Gas"],
        "monthlyCapacity": {"Natural Gas": 5000},
        "data": {
            "currentDay": {
                "2026-05-14 15:05:00-0500": {
                    "Natural Gas": {"gen": 1000, "hsl": 2200, "seasonalCapacity": 5000}
                }
            }
        },
    }

    fuel_mix = clients_service._normalize_ercot_public_dashboard("fuel_mix", payload)

    latest = fuel_mix["latest"]["mix"][0]
    assert latest["generation_mw"] == 1000
    assert latest["hsl_mw"] == 2200
    assert latest["capacity_mw"] == 5000
    assert latest["unavailable_mw"] == 2800
    assert latest["headroom_mw"] == 1200


def test_diagnostics_wait_when_live_sources_are_empty() -> None:
    snapshot = dashboard_service.compose_dashboard_snapshot(
        ercot=clients_service.empty_ercot_snapshot("x", state="unavailable"),
        eia=clients_service.empty_eia_snapshot("x", state="unavailable"),
        noaa=clients_service.empty_noaa_snapshot("x", state="unavailable"),
        supply_demand=clients_service.empty_supply_demand_snapshot("x", state="unavailable"),
        ercot_dashboards=clients_service.empty_ercot_public_dashboards("x", state="unavailable"),
        eia_gas=clients_service.empty_eia_natural_gas("x", state="unavailable"),
        climate=clients_service.empty_cpc_degree_day_forecast("x", state="unavailable"),
        fanout={"strategy": "unit", "duration_ms": 0, "source_latency_ms": {}, "sources": 0, "live": False},
    )

    assert snapshot["diagnostics"]["status"]["state"] == "waiting"
    assert snapshot["diagnostics"]["signals"] == []


def test_operator_events_are_included_in_dashboard_snapshot() -> None:
    clear_operator_events()
    try:
        event = create_operator_event(
            {
                "level": "warning",
                "title": "Manual reserve watch",
                "message": "Operator-created events should appear in the feed.",
                "source": "Control room",
            }
        )

        snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

        assert snapshot["events"][0]["id"] == event["id"]
        assert snapshot["events"][0]["source"] == "Control room"
        assert snapshot["events"][0]["title"] == "Manual reserve watch"
    finally:
        clear_operator_events()


def test_kpi_forecasts_stop_at_dallas_midnight() -> None:
    supply_demand = {
        "current_day": [
            {
                "timestamp": "2026-05-13T22:15:00-05:00",
                "demand_mw": 50000,
                "is_forecast": False,
            },
            {
                "timestamp": "2026-05-13T23:00:00-05:00",
                "demand_mw": 51000,
                "is_forecast": True,
            },
            {
                "timestamp": "2026-05-13T23:30:00-05:00",
                "demand_mw": 51500,
                "is_forecast": True,
            },
            {
                "timestamp": "2026-05-14T00:00:00-05:00",
                "demand_mw": 52000,
                "is_forecast": True,
            },
        ],
        "six_day": [
            {
                "timestamp": "2026-05-14T01:00:00-05:00",
                "demand_mw": 53000,
            }
        ],
    }

    load_forecast = dashboard_service._supply_forecast_series(supply_demand, "demand_mw")
    wind_forecast = dashboard_service._renewable_hourly_forecast(
        [{"timestamp": "2026-05-13T21:30:00-05:00", "value": 12000}],
        12000,
        kind="wind",
    )

    assert [point["timestamp"] for point in load_forecast] == ["2026-05-13T23:00:00-05:00"]
    assert [point["timestamp"] for point in wind_forecast] == [
        "2026-05-13T22:00:00-05:00",
        "2026-05-13T23:00:00-05:00",
    ]


def test_live_snapshot_falls_back_when_one_source_raises(monkeypatch) -> None:
    def async_fetch(factory):
        async def fetch(_client):
            return factory()

        return fetch

    async def failed_eia_fetch(_client):
        raise RuntimeError("unexpected EIA shape")

    monkeypatch.setattr(dashboard_service, "fetch_ercot_snapshot", async_fetch(lambda: _as_live(demo_ercot_snapshot())))
    monkeypatch.setattr(dashboard_service, "fetch_eia_snapshot", failed_eia_fetch)
    monkeypatch.setattr(dashboard_service, "fetch_noaa_snapshot", async_fetch(lambda: _as_live(demo_noaa_snapshot())))
    monkeypatch.setattr(dashboard_service, "fetch_supply_demand_dashboard", async_fetch(lambda: _as_live(demo_supply_demand_snapshot())))
    monkeypatch.setattr(dashboard_service, "fetch_ercot_public_dashboards", async_fetch(lambda: _as_live(demo_ercot_public_dashboards())))
    monkeypatch.setattr(dashboard_service, "fetch_eia_natural_gas", async_fetch(lambda: _as_live(demo_eia_natural_gas())))
    monkeypatch.setattr(dashboard_service, "fetch_cpc_degree_day_forecast", async_fetch(lambda: _as_live(demo_cpc_degree_day_forecast())))

    snapshot = asyncio.run(get_dashboard_snapshot())

    assert snapshot["metrics"]["stress_index"] >= 0
    assert snapshot["source_status"]["eia"]["state"] == "unavailable"
    assert "RuntimeError" in snapshot["source_status"]["eia"]["message"]
    assert snapshot["source_status"]["ercot"]["state"] == "live"


def test_source_bundle_composition_tracks_group_health() -> None:
    timestamp = "2026-05-13T12:00:00+00:00"
    grid = {
        "name": "grid",
        "timestamp": timestamp,
        "duration_ms": 12.4,
        "latency_ms": {"ercot": 5.1, "supply_demand": 7.3},
        "source_count": 2,
        "status": {"source": "Source bundle", "state": "live", "message": ""},
        "refresh_policy": {"backoff_seconds": 0, "retry_after": ""},
        "data": {
            "ercot": _as_live(demo_ercot_snapshot()),
            "supply_demand": _as_live(demo_supply_demand_snapshot()),
        },
    }
    market_prices = _load_zone_lmp_response(
        {
            "Houston": {"data": [{"settlementPoint": "LZ_HOUSTON", "LMP": "21.15", "SCEDTimestamp": "2026-05-13T09:00:00"}]},
            "North": {"data": [{"settlementPoint": "LZ_NORTH", "LMP": "22.15", "SCEDTimestamp": "2026-05-13T09:00:00"}]},
            "South": {"data": [{"settlementPoint": "LZ_SOUTH", "LMP": "23.15", "SCEDTimestamp": "2026-05-13T09:00:00"}]},
            "West": {"data": [{"settlementPoint": "LZ_WEST", "LMP": "24.15", "SCEDTimestamp": "2026-05-13T09:00:00"}]},
        },
        {},
    )
    market = {
        "name": "market",
        "timestamp": timestamp,
        "duration_ms": 1.0,
        "latency_ms": {"load_zone_lmps": 1.0},
        "source_count": 1,
        "status": {"source": "Source bundle", "state": "live", "message": ""},
        "refresh_policy": {"backoff_seconds": 0, "retry_after": ""},
        "data": {"load_zone_lmps": market_prices},
    }

    snapshot = dashboard_service.compose_dashboard_from_source_bundles(grid=grid, market=market)

    assert snapshot["fanout"]["strategy"] == "source-specific async stores"
    assert snapshot["fanout"]["sources"] >= 3
    assert snapshot["source_groups"]["grid"]["status"]["state"] == "live"
    assert snapshot["source_groups"]["market"]["refresh_policy"]["backoff_seconds"] == 0
    assert snapshot["load_zone_lmps"]["zones"]


def test_supply_demand_payload_normalizes_current_day_rows() -> None:
    payload = {
        "lastUpdated": "2026-05-13 06:15:00-0500",
        "data": [
            {
                "timestamp": "2026-05-13 06:10:00-0500",
                "epoch": 1778671800000,
                "demand": 52000,
                "capacity": 69000,
                "forecast": 0,
            },
            {
                "timestamp": "2026-05-13 06:15:00-0500",
                "epoch": 1778672100000,
                "demand": 52500,
                "capacity": 69200,
                "available": 74000,
                "forecast": 1,
            },
        ],
        "forecast": [
            {
                "timestamp": "2026-05-14 01:00:00-0500",
                "epoch": 1778738400000,
                "forecastedDemand": 51000,
                "availCapGen": 95000,
            }
        ],
    }

    snapshot = _normalize_supply_demand_payload(payload)

    assert snapshot["last_updated"] == "2026-05-13T06:15:00-05:00"
    assert snapshot["latest"]["demand_mw"] == 52000
    assert snapshot["current_day"][1]["is_forecast"] is True
    assert snapshot["current_day"][1]["available_capacity_mw"] == 74000
    assert snapshot["six_day"][0]["available_capacity_mw"] == 95000
    assert snapshot["summary"]["forecast_points"] == 1


def test_combined_renewables_dashboard_keeps_today_through_midnight() -> None:
    payload = {
        "lastUpdated": "2026-05-14 14:55:12-0500",
        "currentDay": {
            "data": {
                "1778803200000": {
                    "hourEnding": 23,
                    "actualWind": 12000,
                    "actualSolar": 8000,
                    "stwpf": 12100,
                    "stppf": 7900,
                    "timestamp": "2026-05-14 23:00:00-0500",
                    "epoch": 1778803200000,
                },
                "1778806800000": {
                    "hourEnding": 24,
                    "actualWind": None,
                    "actualSolar": None,
                    "stwpf": 13000,
                    "stppf": 0,
                    "timestamp": "2026-05-15 00:00:00-0500",
                    "epoch": 1778806800000,
                },
                "1778810400000": {
                    "hourEnding": 1,
                    "actualWind": None,
                    "actualSolar": None,
                    "stwpf": 14000,
                    "stppf": 0,
                    "timestamp": "2026-05-15 01:00:00-0500",
                    "epoch": 1778810400000,
                },
            }
        },
    }

    snapshot = clients_service._normalize_ercot_public_dashboard("combined_renewables", payload)

    assert [point["timestamp"] for point in snapshot["current_day"]] == [
        "2026-05-14T23:00:00-05:00",
        "2026-05-15T00:00:00-05:00",
    ]
    assert snapshot["current_day"][0]["combined_actual_mw"] == 20000
    assert snapshot["current_day"][1]["combined_actual_mw"] is None
    assert snapshot["current_day"][1]["combined_forecast_mw"] == 13000
    assert snapshot["summary"]["actual_points"] == 1
    assert snapshot["summary"]["forecast_points"] == 1


def test_dc_tie_flows_dashboard_keeps_current_day_series() -> None:
    payload = {
        "lastUpdated": "2026-05-14 15:20:00-0500",
        "data": [
            {
                "currentFrequency": 60.005,
                "currentSystemInertia": 250751,
                "dcE": 405,
                "dcN": 0,
                "dcL": -1,
                "dcR": 0,
                "timestamp": "2026-05-14 00:00:00-0500",
                "epoch": 1778734800000,
                "interval": "00:00:00",
                "dstFlag": "N",
            },
            {
                "currentFrequency": 60.016,
                "currentSystemInertia": 216426,
                "dcE": -120,
                "dcN": 18,
                "dcL": 25,
                "dcR": 0,
                "timestamp": "2026-05-14 15:20:00-0500",
                "epoch": 1778790000000,
                "interval": "15:20:00",
                "dstFlag": "N",
            },
            {
                "dcE": 999,
                "dcN": 999,
                "dcL": 999,
                "dcR": 999,
                "timestamp": "2026-05-15 00:00:00-0500",
                "epoch": 1778821200000,
            },
        ],
    }

    snapshot = clients_service._normalize_ercot_public_dashboard("dc_ties", payload)

    assert [point["timestamp"] for point in snapshot["current_day"]] == [
        "2026-05-14T00:00:00-05:00",
        "2026-05-14T15:20:00-05:00",
    ]
    assert [point["value"] for point in snapshot["series"]["East"]] == [405, -120]
    assert [point["value"] for point in snapshot["series"]["North"]] == [0, 18]
    assert snapshot["latest"]["net_mw"] == -77
    assert snapshot["summary"]["points"] == 2


def test_ercot_price_query_targets_hb_north(monkeypatch) -> None:
    monkeypatch.setenv("ERCOT_RT_LMP_POINTS", "24")

    params = _ercot_params("price")

    assert params["settlementPoint"] == "HB_NORTH"
    assert params["size"] == 24
    assert params["sort"] == "SCEDTimestamp"
    assert "SCEDTimestampFrom" in params
    assert "SCEDTimestampTo" in params
    assert "settlementPointType" not in params


def test_ercot_price_cache_key_ignores_moving_time_window() -> None:
    first = _ercot_params("price")
    second = dict(first)
    second["SCEDTimestampFrom"] = "2026-05-13T00:00:00"
    second["SCEDTimestampTo"] = "2026-05-13T12:00:00"

    assert _ercot_payload_cache_key("price", first) == _ercot_payload_cache_key("price", second)


def test_rt_lmp_incremental_query_starts_after_latest_cached_sced(monkeypatch) -> None:
    monkeypatch.setenv("ERCOT_RT_LMP_UPDATE_POINTS", "6")
    rows = [
        {"settlementPoint": "HB_NORTH", "LMP": 20, "SCEDTimestamp": "2026-05-13T07:00:00"},
        {"settlementPoint": "HB_NORTH", "LMP": 21, "SCEDTimestamp": "2026-05-13T07:05:00"},
    ]

    params = _rt_lmp_query_params(rows)

    assert params["size"] == 6
    assert params["dir"] == "ASC"
    assert params["sort"] == "SCEDTimestamp"
    assert params["SCEDTimestampFrom"].endswith("07:05:01")
    assert params["settlementPoint"] == "HB_NORTH"


def test_rt_lmp_report_params_map_public_api_names() -> None:
    params = _rt_lmp_report_params(
        start_time="2026-05-13 07:00:00",
        end_time="2026-05-13T08:00:00-05:00",
        settlement_point="hb_west",
        size=288,
    )

    assert params == {
        "page": 1,
        "size": 288,
        "dir": "ASC",
        "sort": "SCEDTimestamp",
        "SCEDTimestampFrom": "2026-05-13T07:00:00",
        "SCEDTimestampTo": "2026-05-13T08:00:00",
        "settlementPoint": "HB_WEST",
    }


def test_live_zone_metrics_do_not_fabricate_prices_from_system_lmp() -> None:
    zones = _load_zone_metrics(50_000, 58_000, 35.25)

    assert all(zone["price_usd_mwh"] is None for zone in zones)


def test_load_zone_lmp_params_query_latest_sced_for_settlement_point() -> None:
    params = _load_zone_lmp_params("LZ_HOUSTON")

    assert params["settlementPoint"] == "LZ_HOUSTON"
    assert params["size"] == 1
    assert params["dir"] == "DESC"
    assert params["sort"] == "SCEDTimestamp"
    assert "SCEDTimestampFrom" in params
    assert "SCEDTimestampTo" in params


def test_load_zone_lmp_response_is_complete_when_all_prices_arrive() -> None:
    payloads = {
        "Houston": {"data": [{"settlementPoint": "LZ_HOUSTON", "LMP": "21.15", "SCEDTimestamp": "2026-05-13T09:00:00"}]},
        "North": {"data": [{"settlementPoint": "LZ_NORTH", "LMP": "22.15", "SCEDTimestamp": "2026-05-13T09:00:00"}]},
        "South": {"data": [{"settlementPoint": "LZ_SOUTH", "LMP": "23.15", "SCEDTimestamp": "2026-05-13T09:00:00"}]},
        "West": {"data": [{"settlementPoint": "LZ_WEST", "LMP": "24.15", "SCEDTimestamp": "2026-05-13T09:00:00"}]},
    }

    response = _load_zone_lmp_response(payloads, {})

    assert response["complete"] is True
    assert response["status"]["state"] == "live"
    assert [zone["settlement_point"] for zone in response["zones"]] == ["LZ_HOUSTON", "LZ_NORTH", "LZ_SOUTH", "LZ_WEST"]
    assert [zone["price_usd_mwh"] for zone in response["zones"]] == [21.15, 22.15, 23.15, 24.15]
    assert response["zones"][2]["diagnostic"]["matched_row_count"] == 1


def test_load_zone_lmp_response_marks_widened_south_query_stale() -> None:
    payloads = {
        "Houston": {"data": [{"settlementPoint": "LZ_HOUSTON", "LMP": "21.15", "SCEDTimestamp": "2026-05-13T09:00:00"}]},
        "North": {"data": [{"settlementPoint": "LZ_NORTH", "LMP": "22.15", "SCEDTimestamp": "2026-05-13T09:00:00"}]},
        "South": {
            "__load_zone_query_status": {"mode": "fallback", "hours": 24, "settlement_point": "LZ_SOUTH"},
            "data": [{"settlementPoint": "LZ_SOUTH", "LMP": "23.15", "SCEDTimestamp": "2026-05-13T02:00:00"}],
        },
        "West": {"data": [{"settlementPoint": "LZ_WEST", "LMP": "24.15", "SCEDTimestamp": "2026-05-13T09:00:00"}]},
    }

    response = _load_zone_lmp_response(payloads, {})
    south = response["zones"][2]

    assert response["complete"] is False
    assert response["status"]["state"] == "stale"
    assert "South" in response["status"]["message"]
    assert south["status"] == "stale"
    assert south["price_usd_mwh"] == 23.15
    assert south["diagnostic"]["message"] == "Matched after widening query window to 24h."


def test_ercot_day_ahead_price_query_targets_hb_north_current_day() -> None:
    params = _ercot_params("day_ahead_price")

    assert params["settlementPoint"] == "HB_NORTH"
    assert params["size"] == 48
    assert params["dir"] == "ASC"
    assert params["sort"] == "hourEnding"
    assert "deliveryDateFrom" in params
    assert params["deliveryDateFrom"] == params["deliveryDateTo"]
    assert "settlementPointType" not in params


def test_ercot_load_query_uses_small_report_without_time_window() -> None:
    params = _ercot_params("load")

    assert params["sort"] == "SCEDTimestamp"
    assert "SCEDTimestampFrom" not in params
    assert "SCEDTimestampTo" not in params


def test_ercot_public_api_interval_is_capped_at_30_requests_per_minute(monkeypatch) -> None:
    monkeypatch.setenv("ERCOT_PUBLIC_API_REQUESTS_PER_MINUTE", "60")
    monkeypatch.setenv("ERCOT_PUBLIC_API_RATE_CUSHION_MS", "0")

    assert clients_service._ercot_public_api_interval_seconds() == 2.0


def test_ercot_public_api_gets_are_throttled_server_side(monkeypatch) -> None:
    throttle_calls = []

    async def fake_throttle() -> None:
        throttle_calls.append("throttled")

    monkeypatch.setattr(clients_service, "_throttle_ercot_public_api_request", fake_throttle)

    async def run() -> None:
        transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"ok": True}))
        async with httpx.AsyncClient(transport=transport) as client:
            await clients_service._get_json(client, f"{clients_service.ERCOT_BASE_URL}/unit-test")
            await clients_service._get_json(client, "https://example.test/unit-test")

    asyncio.run(run())

    assert throttle_calls == ["throttled"]


def test_ercot_report_json_returns_local_payload_for_429(monkeypatch) -> None:
    async def fake_throttle() -> None:
        return None

    monkeypatch.setattr(clients_service, "_throttle_ercot_public_api_request", fake_throttle)

    async def run() -> dict:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                429,
                json={"error_key": "throttled", "error_message": "Too Many Requests"},
                headers={"Retry-After": "5"},
                request=request,
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await clients_service._get_ercot_report_json(
                client,
                "unit-rate-limit",
                "/unit-test",
                params={"size": 1},
                headers={},
            )

    payload = asyncio.run(run())

    assert payload["data"] == []
    assert payload["_meta"]["source"] == "local-ercot-rate-limit-guard"
    assert payload["__local_cache_status"]["state"] == "stale"
    assert "rate limit" in payload["__local_cache_status"]["message"]


def test_source_bundle_cache_coalesces_parallel_refreshes() -> None:
    name = "unit-cache-coalesce"
    dashboard_service._source_bundle_cache.pop(name, None)
    dashboard_service._source_bundle_cache_expires_at.pop(name, None)
    dashboard_service._source_bundle_locks.pop(name, None)
    calls = 0

    async def refresh() -> dict:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {
            "name": name,
            "timestamp": "2026-05-14T12:00:00+00:00",
            "duration_ms": 1.0,
            "latency_ms": {},
            "source_count": 1,
            "status": {"source": "Unit", "state": "live", "message": ""},
            "refresh_policy": {"backoff_seconds": 0, "retry_after": ""},
            "data": {"value": calls},
        }

    async def run() -> list[dict]:
        return await asyncio.gather(
            *[dashboard_service._source_bundle_with_cache(name, refresh) for _ in range(5)]
        )

    results = asyncio.run(run())

    assert calls == 1
    assert [result["data"]["value"] for result in results] == [1, 1, 1, 1, 1]


def test_ercot_now_does_not_require_windows_tzdata_at_import() -> None:
    assert _ercot_now().tzinfo is not None


def test_price_proxy_uses_latest_north_hub_row_and_ercot_field_aliases() -> None:
    rows = [
        {"SettlementPointName": "HB_WEST", "LMP": 10, "RTDTimestamp": "2026-05-13T07:10:00"},
        {"SettlementPointName": "HB_NORTH", "LMP": 25, "RTDTimestamp": "2026-05-13T07:10:00"},
        {"SettlementPointName": "HB_NORTH", "LMP": 35, "RTDTimestamp": "2026-05-13T07:05:00"},
    ]

    assert _price_proxy(rows, settlement_point="HB_NORTH") == 25


def test_day_ahead_price_series_uses_hour_ending_step_points() -> None:
    rows = [
        {
            "SettlementPointName": "HB_NORTH",
            "settlementPointPrice": "22.45",
            "deliveryDate": "2026-05-13",
            "hourEnding": "01:00",
        },
        {
            "SettlementPointName": "HB_NORTH",
            "settlementPointPrice": "31.10",
            "deliveryDate": "2026-05-13",
            "hourEnding": "24",
        },
        {
            "SettlementPointName": "HB_WEST",
            "settlementPointPrice": "99.99",
            "deliveryDate": "2026-05-13",
            "hourEnding": "01",
        },
    ]

    series = _day_ahead_price_series(rows, "HB_NORTH")

    assert series == [
        {"timestamp": "2026-05-13T00:00:00", "value": 22.45},
        {"timestamp": "2026-05-13T23:00:00", "value": 31.1},
    ]


def test_ercot_report_registry_exposes_local_debug_urls() -> None:
    reports = {report["name"]: report for report in list_ercot_reports()}

    assert "hb-north-lmp" in reports
    assert reports["hb-north-lmp"]["local_url"] == "/api/ercot/report/hb-north-lmp"
    assert reports["hb-north-lmp"]["default_params"]["settlementPoint"] == "HB_NORTH"
    assert reports["hb-north-da-lmp"]["default_params"]["settlementPoint"] == "HB_NORTH"
    assert reports["hb-north-da-lmp"]["default_params"]["deliveryDateFrom"]


def test_ercot_auth_params_match_public_api_flow() -> None:
    params = _ercot_auth_params("user@example.com", "secret")

    assert params["username"] == "user@example.com"
    assert params["password"] == "secret"
    assert params["grant_type"] == "password"
    assert params["scope"] == f"openid {ERCOT_CLIENT_ID} offline_access"
    assert params["client_id"] == ERCOT_CLIENT_ID
    assert params["response_type"] == "id_token"


def test_price_headers_prefer_secondary_subscription_key(monkeypatch) -> None:
    async def fake_bearer_token(_client: object) -> str:
        return "token"

    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "primary-key")
    monkeypatch.setenv("ERCOT_API_SECONDARY_SUBSCRIPTION_KEY", "secondary-key")
    monkeypatch.setattr(clients_service, "_ercot_bearer_token", fake_bearer_token)

    price_headers = asyncio.run(_ercot_headers(object(), for_price=True))
    grid_headers = asyncio.run(_ercot_headers(object()))

    assert price_headers["Ocp-Apim-Subscription-Key"] == "secondary-key"
    assert grid_headers["Ocp-Apim-Subscription-Key"] == "primary-key"


def test_price_headers_fall_back_to_primary_subscription_key(monkeypatch) -> None:
    async def fake_bearer_token(_client: object) -> str:
        return "token"

    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "primary-key")
    monkeypatch.delenv("ERCOT_API_SECONDARY_SUBSCRIPTION_KEY", raising=False)
    monkeypatch.setattr(clients_service, "_ercot_bearer_token", fake_bearer_token)

    price_headers = asyncio.run(_ercot_headers(object(), for_price=True))

    assert price_headers["Ocp-Apim-Subscription-Key"] == "primary-key"


def test_ercot_report_rows_maps_array_data_with_field_names() -> None:
    payload = {
        "fields": [{"name": "settlementPoint"}, {"name": "LMP"}],
        "data": [["HB_NORTH", 25.22]],
    }

    assert _report_rows(payload) == [{"settlementPoint": "HB_NORTH", "LMP": 25.22}]


def test_noaa_airport_query_uses_nws_current_observation_station() -> None:
    assert NOAA_AIRPORT_STATIONS["DFW"]["station_id"] == "KDFW"
    assert _nws_observation_url("kdfw") == "https://api.weather.gov/stations/KDFW/observations/latest"
    assert _nws_headers()["Accept"] == "application/geo+json"
    assert _nws_headers()["User-Agent"]


def test_noaa_airport_observation_normalizes_current_nws_units() -> None:
    payload = {
        "properties": {
            "timestamp": "2026-05-13T15:51:00+00:00",
            "textDescription": "Mostly Cloudy",
            "rawMessage": "KDFW 131551Z AUTO",
            "temperature": {"unitCode": "wmoUnit:degC", "value": 30},
            "maxTemperatureLast24Hours": {"unitCode": "wmoUnit:degC", "value": 35},
            "minTemperatureLast24Hours": {"unitCode": "wmoUnit:degC", "value": 20},
            "windSpeed": {"unitCode": "wmoUnit:km_h-1", "value": 16.0934},
            "precipitationLastHour": {"unitCode": "wmoUnit:m", "value": 0.00254},
        }
    }

    airport = _normalize_nws_airport_observation(payload, "DFW", NOAA_AIRPORT_STATIONS["DFW"])

    assert airport["airport"] == "DFW"
    assert airport["station_id"] == "KDFW"
    assert airport["observed_at"] == "2026-05-13T15:51:00+00:00"
    assert airport["observed_date"] == "2026-05-13"
    assert airport["temperature_f"] == 86
    assert airport["daily_high_f"] == 95
    assert airport["daily_low_f"] == 68
    assert airport["wind_speed_mph"] == 10
    assert airport["precipitation_in"] == 0.1
    assert airport["description"] == "Mostly Cloudy"
    assert airport["source"] == "live"


def test_cpc_degree_day_forecast_parses_texas_region() -> None:
    text = """
 MONTHLY TOTAL DEGREE DAY FORECAST
 300 PM EDT THU 16 APR 2026

 WEST SOUTH CENTRAL (AR LA OK TX)                         NORMALS       FORECAST
 HEATING             COOLING       (1981-2010)   DEPARTURE
 YEAR MONTH  90%   MEAN    10%     90%   MEAN    10%      HDD    CDD    HDD    CDD
 2026   5    10.    20.    30.    100.   120.   140.      25.   110.    -5.    10.
 TEXAS                                                     NORMALS       FORECAST
 HEATING             COOLING       (1981-2010)   DEPARTURE
 YEAR MONTH  90%   MEAN    10%     90%   MEAN    10%      HDD    CDD    HDD    CDD
 2026   5     0.     4.     8.    246.   318.   396.       5.   297.    -1.    21.
"""

    forecast = _parse_cpc_degree_day_forecast(text, region="Texas")

    assert forecast["region"] == "TEXAS"
    assert forecast["states"] == ["TX"]
    assert forecast["rows"][0]["period"] == "2026-05"
    assert forecast["rows"][0]["cooling_degree_days"]["mean"] == 318
    assert forecast["summary"]["cooling_departure_total"] == 21


def test_demo_cpc_forecast_targets_texas_only_region() -> None:
    forecast = demo_cpc_degree_day_forecast()

    assert forecast["region"] == "TEXAS"
    assert forecast["states"] == ["TX"]
    assert len(forecast["rows"]) == 15

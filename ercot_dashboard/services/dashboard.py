from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import os
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from ercot_dashboard.services.clients import (
    demo_cpc_degree_day_forecast,
    demo_eia_snapshot,
    demo_eia_natural_gas,
    demo_ercot_snapshot,
    demo_ercot_public_dashboards,
    demo_noaa_snapshot,
    demo_supply_demand_snapshot,
    fetch_cpc_degree_day_forecast,
    fetch_eia_snapshot,
    fetch_eia_natural_gas,
    fetch_ercot_load_zone_lmps,
    fetch_ercot_snapshot,
    fetch_ercot_public_dashboards,
    fetch_noaa_snapshot,
    fetch_supply_demand_dashboard,
    utc_now,
)
from ercot_dashboard.services.events import list_operator_events

DALLAS_TIMEZONE = "America/Chicago"
SOURCE_KEYS = (
    "ercot",
    "eia",
    "noaa",
    "supply_demand",
    "ercot_dashboards",
    "eia_gas",
    "cpc",
)
SOURCE_GROUPS = (
    "grid",
    "ercot_dashboards",
    "weather",
    "energy",
    "climate",
    "market",
)
_source_bundle_cache: dict[str, dict[str, Any]] = {}
_source_bundle_cache_expires_at: dict[str, datetime] = {}
_source_bundle_locks: dict[str, asyncio.Lock] = {}


async def get_dashboard_snapshot(*, use_live: bool = True) -> dict[str, Any]:
    if use_live:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            fanout_started = time.perf_counter()
            timed_results = await asyncio.gather(
                _timed_source("ercot", fetch_ercot_snapshot(client)),
                _timed_source("eia", fetch_eia_snapshot(client)),
                _timed_source("noaa", fetch_noaa_snapshot(client)),
                _timed_source("supply_demand", fetch_supply_demand_dashboard(client)),
                _timed_source("ercot_dashboards", fetch_ercot_public_dashboards(client)),
                _timed_source("eia_gas", fetch_eia_natural_gas(client)),
                _timed_source("cpc", fetch_cpc_degree_day_forecast(client)),
            )
            fanout_duration_ms = round((time.perf_counter() - fanout_started) * 1000, 1)
            results = {name: result for name, result, _duration in timed_results}
            source_latency_ms = {name: duration for name, _result, duration in timed_results}
            ercot = _snapshot_or_demo(results["ercot"], demo_ercot_snapshot)
            eia = _snapshot_or_demo(results["eia"], demo_eia_snapshot)
            noaa = _snapshot_or_demo(results["noaa"], demo_noaa_snapshot)
            supply_demand = _snapshot_or_demo(results["supply_demand"], demo_supply_demand_snapshot)
            ercot_dashboards = _snapshot_or_demo(results["ercot_dashboards"], demo_ercot_public_dashboards)
            eia_gas = _snapshot_or_demo(results["eia_gas"], demo_eia_natural_gas)
            climate = _snapshot_or_demo(results["cpc"], demo_cpc_degree_day_forecast)
    else:
        sources = demo_dashboard_sources()
        ercot = sources["ercot"]
        eia = sources["eia"]
        noaa = sources["noaa"]
        supply_demand = sources["supply_demand"]
        ercot_dashboards = sources["ercot_dashboards"]
        eia_gas = sources["eia_gas"]
        climate = sources["climate"]
        fanout_duration_ms = 0.0
        source_latency_ms = {name: 0.0 for name in SOURCE_KEYS}

    return compose_dashboard_snapshot(
        ercot=ercot,
        eia=eia,
        noaa=noaa,
        supply_demand=supply_demand,
        ercot_dashboards=ercot_dashboards,
        eia_gas=eia_gas,
        climate=climate,
        fanout={
            "strategy": "asyncio.gather",
            "duration_ms": fanout_duration_ms,
            "source_latency_ms": source_latency_ms,
            "sources": len(SOURCE_KEYS),
            "live": use_live,
        },
    )


def compose_dashboard_snapshot(
    *,
    ercot: dict[str, Any],
    eia: dict[str, Any],
    noaa: dict[str, Any],
    supply_demand: dict[str, Any],
    ercot_dashboards: dict[str, Any],
    eia_gas: dict[str, Any],
    climate: dict[str, Any],
    fanout: dict[str, Any],
    load_zone_lmps: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ercot = _align_ercot_with_supply_demand(ercot, supply_demand)
    metrics = _compute_metrics(ercot, noaa)
    timestamp = utc_now().astimezone(timezone.utc).isoformat()
    status = _system_status(metrics["stress_index"])

    source_status = {
        "ercot": ercot["status"],
        "ercot_dashboards": ercot_dashboards["status"],
        "eia": eia["status"],
        "eia_gas": eia_gas["status"],
        "noaa": noaa["status"],
        "cpc": climate["status"],
    }
    if load_zone_lmps:
        source_status["load_zone_lmps"] = load_zone_lmps.get("status", {})

    snapshot = {
        "timestamp": timestamp,
        "system_status": status,
        "ercot": ercot,
        "eia": eia,
        "noaa": noaa,
        "supply_demand": supply_demand,
        "ercot_dashboards": ercot_dashboards,
        "eia_gas": eia_gas,
        "climate": climate,
        "metrics": metrics,
        "trends": _build_kpi_trends(ercot, noaa, metrics, supply_demand),
        "events": [*list_operator_events(limit=10), *_build_events(ercot, eia, noaa, metrics, status, fanout)],
        "fanout": fanout,
        "source_status": source_status,
    }
    if load_zone_lmps:
        snapshot["load_zone_lmps"] = load_zone_lmps
    return snapshot


def demo_dashboard_sources(*, status_message: str = "") -> dict[str, dict[str, Any]]:
    sources = {
        "ercot": demo_ercot_snapshot(),
        "eia": demo_eia_snapshot(),
        "noaa": demo_noaa_snapshot(),
        "supply_demand": demo_supply_demand_snapshot(),
        "ercot_dashboards": demo_ercot_public_dashboards(),
        "eia_gas": demo_eia_natural_gas(),
        "climate": demo_cpc_degree_day_forecast(),
    }
    if status_message:
        for snapshot in sources.values():
            status = dict(snapshot.get("status") or {})
            status["state"] = "demo"
            status["message"] = status_message
            snapshot["status"] = status
    return sources


def compose_dashboard_from_source_bundles(
    *,
    grid: dict[str, Any] | None = None,
    ercot_dashboards: dict[str, Any] | None = None,
    weather: dict[str, Any] | None = None,
    energy: dict[str, Any] | None = None,
    climate: dict[str, Any] | None = None,
    market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    defaults = demo_dashboard_sources(status_message="Waiting for source-specific async refresh.")
    bundles = {
        "grid": grid,
        "ercot_dashboards": ercot_dashboards,
        "weather": weather,
        "energy": energy,
        "climate": climate,
        "market": market,
    }
    snapshot = compose_dashboard_snapshot(
        ercot=_bundle_data(grid, "ercot", defaults["ercot"]),
        supply_demand=_bundle_data(grid, "supply_demand", defaults["supply_demand"]),
        ercot_dashboards=_bundle_data(ercot_dashboards, "ercot_dashboards", defaults["ercot_dashboards"]),
        noaa=_bundle_data(weather, "noaa", defaults["noaa"]),
        eia=_bundle_data(energy, "eia", defaults["eia"]),
        eia_gas=_bundle_data(energy, "eia_gas", defaults["eia_gas"]),
        climate=_bundle_data(climate, "climate", defaults["climate"]),
        load_zone_lmps=_bundle_data(market, "load_zone_lmps", None),
        fanout=_source_bundle_fanout(list(bundles.values())),
    )
    snapshot["source_groups"] = _source_group_status(bundles)
    return snapshot


def _bundle_data(bundle: dict[str, Any] | None, key: str, fallback: Any) -> Any:
    data = bundle.get("data", {}) if isinstance(bundle, dict) else {}
    return data.get(key, fallback) if isinstance(data, dict) else fallback


def _source_bundle_fanout(bundles: list[dict[str, Any] | None]) -> dict[str, Any]:
    latency: dict[str, float] = {}
    duration = 0.0
    live = False
    sources = 0
    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        live = True
        duration += float(bundle.get("duration_ms") or 0)
        bundle_latency = bundle.get("latency_ms") or {}
        if isinstance(bundle_latency, dict):
            for key, value in bundle_latency.items():
                if isinstance(value, int | float):
                    latency[str(key)] = float(value)
        sources += int(bundle.get("source_count") or len(bundle_latency) or 1)

    return {
        "strategy": "source-specific async stores",
        "duration_ms": round(duration, 1),
        "source_latency_ms": latency,
        "sources": sources,
        "live": live,
    }


def _source_group_status(bundles: dict[str, dict[str, Any] | None]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for name, bundle in bundles.items():
        if isinstance(bundle, dict):
            status = bundle.get("status") if isinstance(bundle.get("status"), dict) else {}
            policy = bundle.get("refresh_policy") if isinstance(bundle.get("refresh_policy"), dict) else {}
            groups[name] = {
                "status": status or _status(name.replace("_", " ").title(), "unknown", "No source status returned."),
                "refresh_policy": policy,
                "timestamp": bundle.get("timestamp", ""),
                "source_count": bundle.get("source_count", 0),
            }
        else:
            groups[name] = {
                "status": _status(name.replace("_", " ").title(), "waiting", "Waiting for async source store."),
                "refresh_policy": {},
                "timestamp": "",
                "source_count": 0,
            }
    return groups


async def get_grid_source_bundle() -> dict[str, Any]:
    async def refresh() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await _source_bundle(
                "grid",
                {
                    "ercot": (fetch_ercot_snapshot(client), demo_ercot_snapshot),
                    "supply_demand": (fetch_supply_demand_dashboard(client), demo_supply_demand_snapshot),
                },
            )

    return await _source_bundle_with_cache("grid", refresh)


async def get_ercot_dashboards_source_bundle() -> dict[str, Any]:
    async def refresh() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await _source_bundle(
                "ercot_dashboards",
                {
                    "ercot_dashboards": (fetch_ercot_public_dashboards(client), demo_ercot_public_dashboards),
                },
            )

    return await _source_bundle_with_cache("ercot_dashboards", refresh)


async def get_weather_source_bundle() -> dict[str, Any]:
    async def refresh() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await _source_bundle(
                "weather",
                {"noaa": (fetch_noaa_snapshot(client), demo_noaa_snapshot)},
            )

    return await _source_bundle_with_cache("weather", refresh)


async def get_energy_source_bundle() -> dict[str, Any]:
    async def refresh() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await _source_bundle(
                "energy",
                {
                    "eia": (fetch_eia_snapshot(client), demo_eia_snapshot),
                    "eia_gas": (fetch_eia_natural_gas(client), demo_eia_natural_gas),
                },
            )

    return await _source_bundle_with_cache("energy", refresh)


async def get_market_source_bundle() -> dict[str, Any]:
    async def refresh() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            return await _source_bundle(
                "market",
                {"load_zone_lmps": (fetch_ercot_load_zone_lmps(client), demo_load_zone_lmps)},
            )

    return await _source_bundle_with_cache("market", refresh)


async def get_climate_source_bundle() -> dict[str, Any]:
    async def refresh() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await _source_bundle(
                "climate",
                {"climate": (fetch_cpc_degree_day_forecast(client), demo_cpc_degree_day_forecast)},
            )

    return await _source_bundle_with_cache("climate", refresh)


async def _source_bundle_with_cache(
    name: str,
    refresh: Callable[[], Any],
) -> dict[str, Any]:
    cached = _cached_source_bundle(name)
    if cached:
        return cached

    lock = _source_bundle_locks.setdefault(name, asyncio.Lock())
    async with lock:
        cached = _cached_source_bundle(name)
        if cached:
            return cached

        bundle = await refresh()
        _store_source_bundle(name, bundle)
        return bundle


def _cached_source_bundle(name: str) -> dict[str, Any] | None:
    bundle = _source_bundle_cache.get(name)
    expires_at = _source_bundle_cache_expires_at.get(name)
    if not bundle or not expires_at or expires_at <= utc_now():
        return None
    return deepcopy(bundle)


def _store_source_bundle(name: str, bundle: dict[str, Any]) -> None:
    _source_bundle_cache[name] = deepcopy(bundle)
    _source_bundle_cache_expires_at[name] = utc_now() + timedelta(seconds=_source_bundle_cache_seconds(name))


def _source_bundle_cache_seconds(name: str) -> int:
    defaults = {
        "grid": ("ERCOT_GRID_SOURCE_CACHE_SECONDS", 60, 20, 900),
        "ercot_dashboards": ("ERCOT_DASHBOARDS_SOURCE_CACHE_SECONDS", 60, 30, 900),
        "weather": ("WEATHER_SOURCE_CACHE_SECONDS", 60, 15, 900),
        "energy": ("ENERGY_SOURCE_CACHE_SECONDS", 300, 60, 1800),
        "market": ("ERCOT_MARKET_SOURCE_CACHE_SECONDS", 60, 30, 900),
        "climate": ("CLIMATE_SOURCE_CACHE_SECONDS", 900, 120, 3600),
    }
    env_name, default, minimum, maximum = defaults.get(name, ("SOURCE_BUNDLE_CACHE_SECONDS", 60, 10, 900))
    return _env_int(env_name, default, minimum=minimum, maximum=maximum)


async def _source_bundle(
    name: str,
    requests: dict[str, tuple[Any, Callable[[], dict[str, Any]]]],
) -> dict[str, Any]:
    started = time.perf_counter()
    timed_results = await asyncio.gather(
        *[_timed_source(source_name, awaitable) for source_name, (awaitable, _fallback) in requests.items()]
    )
    results = {source_name: result for source_name, result, _duration in timed_results}
    data = {
        source_name: _snapshot_or_demo(results[source_name], fallback_factory)
        for source_name, (_awaitable, fallback_factory) in requests.items()
    }
    latency = {source_name: duration for source_name, _result, duration in timed_results}
    status = _aggregate_source_status(data)
    return {
        "name": name,
        "timestamp": utc_now().astimezone(timezone.utc).isoformat(),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "latency_ms": latency,
        "source_count": len(requests),
        "status": status,
        "refresh_policy": _refresh_policy(status),
        "data": data,
    }


def _aggregate_source_status(data: dict[str, dict[str, Any]]) -> dict[str, str]:
    states = [str(snapshot.get("status", {}).get("state") or "unknown") for snapshot in data.values()]
    if all(state == "live" for state in states):
        state = "live"
    elif any(state in {"unavailable", "unknown"} for state in states):
        state = "partial"
    elif any(state == "demo" for state in states):
        state = "demo"
    elif any(state == "stale" for state in states):
        state = "stale"
    else:
        state = "partial"
    messages = [
        str(snapshot.get("status", {}).get("message") or "")
        for snapshot in data.values()
        if snapshot.get("status", {}).get("message")
    ]
    return _status("Source bundle", state, "; ".join(messages))


def _refresh_policy(status: dict[str, str]) -> dict[str, Any]:
    state = status.get("state")
    backoff_seconds = 0
    if state in {"unavailable", "unknown"}:
        backoff_seconds = 120
    elif state in {"demo", "partial", "stale"}:
        backoff_seconds = 60

    retry_after = ""
    if backoff_seconds:
        retry_after = (utc_now().astimezone(timezone.utc) + timedelta(seconds=backoff_seconds)).isoformat()

    return {
        "backoff_seconds": backoff_seconds,
        "retry_after": retry_after,
    }


def demo_load_zone_lmps() -> dict[str, Any]:
    zones = []
    for zone in demo_ercot_snapshot().get("load_zones", []):
        zones.append(
            {
                "name": zone.get("name", ""),
                "settlement_point": zone.get("settlement_point", ""),
                "price_usd_mwh": zone.get("price_usd_mwh"),
                "timestamp": utc_now().isoformat(),
                "status": "demo",
                "diagnostic": {
                    "raw_row_count": 0,
                    "matched_row_count": 0,
                    "sample_settlement_points": [],
                    "query": {},
                    "message": "Demo load-zone LMP value.",
                },
            }
        )
    return {
        "timestamp": utc_now().isoformat(),
        "complete": False,
        "status": _status("ERCOT Load Zone RT LMP", "demo", "Using demo load-zone LMP values."),
        "zones": zones,
    }


def _status(source: str, state: str, message: str = "") -> dict[str, str]:
    return {"source": source, "state": state, "message": message}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


async def _timed_source(name: str, awaitable: Any) -> tuple[str, dict[str, Any] | BaseException, float]:
    started = time.perf_counter()
    try:
        result = await awaitable
    except BaseException as exc:
        result = exc
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    return name, result, duration_ms


def _snapshot_or_demo(
    result: dict[str, Any] | BaseException,
    fallback_factory: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if isinstance(result, BaseException) and not isinstance(result, Exception):
        raise result
    if not isinstance(result, Exception):
        return result

    snapshot = fallback_factory()
    status = dict(snapshot.get("status") or {})
    status["state"] = "demo"
    status["message"] = f"Using demo data: {type(result).__name__} while refreshing source."
    snapshot["status"] = status
    return snapshot


def _align_ercot_with_supply_demand(
    ercot: dict[str, Any],
    supply_demand: dict[str, Any],
) -> dict[str, Any]:
    latest = supply_demand.get("latest") or {}
    load = latest.get("demand_mw")
    capacity = latest.get("committed_capacity_mw")
    if not isinstance(load, int | float) or not isinstance(capacity, int | float):
        return ercot

    ercot = dict(ercot)
    ercot["load_mw"] = round(float(load), 1)
    ercot["generation_mw"] = round(float(capacity), 1)
    ercot["reserve_margin_pct"] = round(((float(capacity) - float(load)) / max(float(load), 1)) * 100, 1)
    load_zones = _scale_regions_to_load(
        ercot.get("load_zones") or ercot.get("regions", []),
        float(load),
        float(capacity),
    )
    ercot["load_zones"] = load_zones
    ercot["regions"] = [dict(zone) for zone in load_zones]

    ercot_status = ercot.get("status", {})
    supply_status = supply_demand.get("status", {})
    if ercot_status.get("state") == "demo" and supply_status.get("state") == "live":
        ercot["status"] = {
            "source": "ERCOT",
            "state": "partial",
            "message": "Load and committed capacity use ERCOT Supply/Demand dashboard data.",
        }
    return ercot


def _scale_regions_to_load(
    regions: list[dict[str, Any]],
    load_mw: float,
    generation_mw: float,
) -> list[dict[str, Any]]:
    if not regions:
        return regions
    total_load = sum(float(region.get("load_mw") or 0) for region in regions) or load_mw
    total_generation = sum(float(region.get("generation_mw") or 0) for region in regions) or generation_mw
    scaled = []
    for region in regions:
        updated = dict(region)
        updated["load_mw"] = round((float(region.get("load_mw") or 0) / total_load) * load_mw, 1)
        updated["generation_mw"] = round(
            (float(region.get("generation_mw") or 0) / total_generation) * generation_mw,
            1,
        )
        updated["stress"] = round(
            min(100, max(5, (updated["load_mw"] / max(updated["generation_mw"], 1)) * 78)),
            1,
        )
        scaled.append(updated)
    return scaled


def _compute_metrics(ercot: dict[str, Any], noaa: dict[str, Any]) -> dict[str, float]:
    load = float(ercot["load_mw"])
    generation = float(ercot["generation_mw"])
    temp = float(noaa["temperature_f"])
    reserve_margin = float(ercot["reserve_margin_pct"])
    price_state = (ercot.get("price_status") or ercot.get("status", {})).get("state")
    price = 0 if price_state in {"demo", "unavailable"} else float(ercot["price_proxy"] or 0)

    weather_pressure = max(0, temp - 78) * 1.45
    reserve_pressure = max(0, 16 - reserve_margin) * 2.2
    price_pressure = max(0, price - 45) * 0.75
    renewable_relief = min(18, ((float(ercot["wind_mw"]) + float(ercot["solar_mw"])) / max(load, 1)) * 35)
    stress = 34 + weather_pressure + reserve_pressure + price_pressure - renewable_relief
    stress = round(min(100, max(0, stress)), 1)

    return {
        "stress_index": stress,
        "balance_mw": round(generation - load, 1),
        "renewable_share_pct": round(
            ((float(ercot["wind_mw"]) + float(ercot["solar_mw"])) / max(generation, 1)) * 100,
            1,
        ),
    }


def _system_status(stress_index: float) -> str:
    if stress_index >= 72:
        return "System Stress"
    if stress_index >= 52:
        return "Elevated"
    return "Normal"


def _build_kpi_trends(
    ercot: dict[str, Any],
    noaa: dict[str, Any],
    metrics: dict[str, float],
    supply_demand: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    load_actual = _supply_actual_series(supply_demand, "demand_mw")
    load_forecast = _supply_forecast_series(supply_demand, "demand_mw")
    generation_series = _supply_actual_series(supply_demand, "committed_capacity_mw")
    ercot_trends = ercot.get("trends", {})
    wind_actual = ercot_trends.get("wind_mw") or _fallback_series(float(ercot["wind_mw"]), spread=0.18)
    solar_actual = ercot_trends.get("solar_mw") or _fallback_series(float(ercot["solar_mw"]), spread=0.35, floor=0)

    trends = {
        "load_mw": _with_forecast(
            load_actual or ercot_trends.get("load_mw") or _fallback_series(float(ercot["load_mw"])),
            load_forecast,
        ),
        "generation_mw": generation_series
        or ercot_trends.get("generation_mw")
        or _fallback_series(float(ercot["generation_mw"])),
        "price_proxy": ercot_trends.get("price_proxy") or _optional_price_series(ercot.get("price_proxy")),
        "wind_mw": _with_forecast(
            wind_actual,
            _renewable_hourly_forecast(wind_actual, float(ercot["wind_mw"]), kind="wind"),
        ),
        "solar_mw": _with_forecast(
            solar_actual,
            _renewable_hourly_forecast(solar_actual, float(ercot["solar_mw"]), kind="solar"),
        ),
    }
    trends["net_load_mw"] = _net_load_trend(trends["load_mw"], trends["wind_mw"], trends["solar_mw"], ercot)
    trends["stress_index"] = _stress_trend(
        _actual_points(trends["load_mw"]),
        trends["generation_mw"],
        ercot,
        noaa,
        metrics,
    )
    return trends


def _optional_price_series(price: Any) -> list[dict[str, Any]]:
    return _fallback_series(float(price), spread=0.12) if isinstance(price, int | float) else []


def _supply_actual_series(supply_demand: dict[str, Any], key: str, *, limit: int = 96) -> list[dict[str, Any]]:
    points = [
        {"timestamp": point.get("timestamp", ""), "value": round(float(point[key]), 2)}
        for point in supply_demand.get("current_day", [])
        if not point.get("is_forecast") and isinstance(point.get(key), int | float)
    ]
    return points[-limit:]


def _supply_forecast_series(supply_demand: dict[str, Any], key: str) -> list[dict[str, Any]]:
    candidates = [
        point
        for point in supply_demand.get("current_day", [])
        if point.get("is_forecast") and isinstance(point.get(key), int | float)
    ]
    candidates.extend(
        point for point in supply_demand.get("six_day", []) if isinstance(point.get(key), int | float)
    )
    candidates.sort(key=_trend_sort_key)

    end = _forecast_reset_time(_latest_supply_actual_time(supply_demand) or _first_point_time(candidates))
    hourly_points = []
    seen_hours = set()
    for point in candidates:
        timestamp = _parse_trend_datetime(point.get("timestamp"))
        if not _is_before_forecast_reset(timestamp, end):
            continue

        hour_key = _hour_bucket(point.get("timestamp")) or str(point.get("timestamp", ""))
        if not hour_key or hour_key in seen_hours:
            continue
        seen_hours.add(hour_key)
        hourly_points.append(
            {
                "timestamp": point.get("timestamp", ""),
                "value": round(float(point[key]), 2),
                "is_forecast": True,
            }
        )
    return hourly_points


def _with_forecast(
    actual: list[dict[str, Any]],
    forecast: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actual_points = [
        {"timestamp": point.get("timestamp", ""), "value": round(float(point["value"]), 2)}
        for point in actual
        if isinstance(point.get("value"), int | float)
    ]
    actual_timestamps = {str(point.get("timestamp", "")) for point in actual_points}
    forecast_points = [
        {
            "timestamp": point.get("timestamp", ""),
            "value": round(float(point["value"]), 2),
            "is_forecast": True,
        }
        for point in forecast
        if isinstance(point.get("value"), int | float) and str(point.get("timestamp", "")) not in actual_timestamps
    ]
    return [*actual_points, *forecast_points]


def _renewable_hourly_forecast(
    actual: list[dict[str, Any]],
    latest: float,
    *,
    kind: str,
) -> list[dict[str, Any]]:
    values = [float(point["value"]) for point in actual if isinstance(point.get("value"), int | float)]
    latest_time = _latest_series_datetime(actual) or utc_now()
    latest_local = _as_dallas_time(latest_time)
    start = _next_hour(latest_local)
    end = _forecast_reset_time(latest_local)
    forecast = []

    if kind == "solar":
        current_hour = latest_local.hour + latest_local.minute / 60
        current_sun = _solar_daylight_factor(current_hour)
        recent_peak = max(values, default=max(latest, 1))
        inferred_peak = latest / current_sun if latest > 0 and current_sun > 0.08 else latest
        peak = max(recent_peak * 1.08, inferred_peak, latest, 500)
        for index, timestamp in enumerate(_hourly_forecast_times(start, end)):
            hour = timestamp.hour + timestamp.minute / 60
            cloud_signal = 0.96 + 0.04 * math.sin(((index + 2) / 9) * math.tau)
            value = max(0, peak * _solar_daylight_factor(hour) * cloud_signal)
            forecast.append(_forecast_point(timestamp, value))
        return forecast

    recent_average = sum(values[-24:]) / len(values[-24:]) if values else latest
    base = max(0, (recent_average * 0.62) + (latest * 0.38))
    for index, timestamp in enumerate(_hourly_forecast_times(start, end)):
        hour = timestamp.hour + timestamp.minute / 60
        target = base * (1 + 0.16 * math.sin(((hour + 2.5) / 18) * math.tau))
        ramp = min(1, (index + 1) / 5)
        value = max(0, latest + (target - latest) * ramp)
        forecast.append(_forecast_point(timestamp, value))
    return forecast


def _net_load_trend(
    load_series: list[dict[str, Any]],
    wind_series: list[dict[str, Any]],
    solar_series: list[dict[str, Any]],
    ercot: dict[str, Any],
) -> list[dict[str, Any]]:
    wind_samples = _series_samples(wind_series)
    solar_samples = _series_samples(solar_series)
    fallback_wind = float(ercot["wind_mw"])
    fallback_solar = float(ercot["solar_mw"])
    net_load = []

    for point in load_series:
        if not isinstance(point.get("value"), int | float):
            continue
        timestamp = point.get("timestamp", "")
        parsed = _parse_trend_datetime(timestamp)
        load = float(point["value"])
        wind = _nearest_value(wind_samples, parsed, fallback_wind)
        solar = _nearest_value(solar_samples, parsed, fallback_solar)
        net_point = {"timestamp": timestamp, "value": round(load - wind - solar, 2)}
        if point.get("is_forecast"):
            net_point["is_forecast"] = True
        net_load.append(net_point)

    return net_load


def _stress_trend(
    load_series: list[dict[str, Any]],
    generation_series: list[dict[str, Any]],
    ercot: dict[str, Any],
    noaa: dict[str, Any],
    metrics: dict[str, float],
) -> list[dict[str, Any]]:
    if not load_series:
        return _fallback_series(float(metrics["stress_index"]), spread=0.1, floor=0, ceiling=100)

    generation_by_time = {point["timestamp"]: point["value"] for point in generation_series}
    fallback_generation = float(ercot["generation_mw"])
    trend = []
    for point in load_series:
        load = float(point["value"])
        generation = float(generation_by_time.get(point["timestamp"], fallback_generation))
        reserve_margin = ((generation - load) / max(load, 1)) * 100
        derived = dict(ercot)
        derived["load_mw"] = load
        derived["generation_mw"] = generation
        derived["reserve_margin_pct"] = reserve_margin
        trend.append({"timestamp": point["timestamp"], "value": _compute_metrics(derived, noaa)["stress_index"]})
    return trend


def _actual_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [point for point in points if not point.get("is_forecast")]


def _series_samples(points: list[dict[str, Any]]) -> list[tuple[datetime, float]]:
    samples = []
    for point in points:
        parsed = _parse_trend_datetime(point.get("timestamp"))
        value = point.get("value")
        if parsed and isinstance(value, int | float):
            samples.append((parsed, float(value)))
    return sorted(samples, key=lambda sample: sample[0])


def _nearest_value(samples: list[tuple[datetime, float]], target: datetime | None, fallback: float) -> float:
    if not samples or target is None:
        return fallback

    nearest_time, nearest_value = min(samples, key=lambda sample: abs((sample[0] - target).total_seconds()))
    if abs((nearest_time - target).total_seconds()) > 3 * 60 * 60:
        return fallback
    return nearest_value


def _latest_series_datetime(points: list[dict[str, Any]]) -> datetime | None:
    parsed = [_parse_trend_datetime(point.get("timestamp")) for point in points]
    parsed = [value for value in parsed if value is not None]
    return max(parsed, default=None)


def _latest_supply_actual_time(supply_demand: dict[str, Any]) -> datetime | None:
    actual_times = [
        _parse_trend_datetime(point.get("timestamp"))
        for point in supply_demand.get("current_day", [])
        if not point.get("is_forecast")
    ]
    return max((value for value in actual_times if value is not None), default=None)


def _first_point_time(points: list[dict[str, Any]]) -> datetime | None:
    parsed = [_parse_trend_datetime(point.get("timestamp")) for point in points]
    return min((value for value in parsed if value is not None), default=None)


def _forecast_point(timestamp: datetime, value: float) -> dict[str, Any]:
    return {"timestamp": timestamp.isoformat(), "value": round(value, 2), "is_forecast": True}


def _solar_daylight_factor(hour: float) -> float:
    if hour < 6 or hour > 20:
        return 0
    return math.sin(((hour - 6) / 14) * math.pi) ** 1.35


def _next_hour(value: datetime) -> datetime:
    rounded = value.replace(minute=0, second=0, microsecond=0)
    if rounded <= value:
        return rounded + timedelta(hours=1)
    return rounded


def _hourly_forecast_times(start: datetime, end: datetime) -> list[datetime]:
    times = []
    timestamp = start
    while timestamp < end:
        times.append(timestamp)
        timestamp += timedelta(hours=1)
    return times


def _forecast_reset_time(reference: datetime | None) -> datetime:
    local_reference = _as_dallas_time(reference or utc_now())
    tomorrow = local_reference.date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=_dallas_tz())


def _is_before_forecast_reset(timestamp: datetime | None, reset_time: datetime) -> bool:
    if timestamp is None:
        return False
    return _as_dallas_time(timestamp) < reset_time


def _as_dallas_time(value: datetime) -> datetime:
    tz = _dallas_tz()
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _dallas_tz():
    try:
        return ZoneInfo(DALLAS_TIMEZONE)
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().tzinfo or timezone.utc


def _hour_bucket(value: Any) -> str:
    parsed = _parse_trend_datetime(value)
    if parsed:
        return _as_dallas_time(parsed).strftime("%Y-%m-%dT%H")
    text = str(value or "").strip()
    return text[:13]


def _trend_sort_key(point: dict[str, Any]) -> tuple[float, str]:
    parsed = _parse_trend_datetime(point.get("timestamp"))
    if parsed:
        return (parsed.timestamp(), str(point.get("timestamp", "")))
    epoch = point.get("epoch")
    if isinstance(epoch, int | float):
        return (float(epoch) / 1000, str(point.get("timestamp", "")))
    return (0, str(point.get("timestamp", "")))


def _parse_trend_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00").replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dallas_tz())
    return parsed


def _fallback_series(
    latest: float,
    *,
    spread: float = 0.06,
    floor: float | None = None,
    ceiling: float | None = None,
    count: int = 36,
) -> list[dict[str, Any]]:
    now = utc_now()
    series = []
    for index in range(count):
        phase = (index / max(count - 1, 1)) * math.tau
        value = latest * (1 + spread * math.sin(phase - math.pi / 3))
        if floor is not None:
            value = max(floor, value)
        if ceiling is not None:
            value = min(ceiling, value)
        series.append(
            {
                "timestamp": (now.replace(microsecond=0) - timedelta(minutes=(count - index - 1) * 5)).isoformat(),
                "value": round(value, 2),
            }
        )
    return series


def _build_events(
    ercot: dict[str, Any],
    eia: dict[str, Any],
    noaa: dict[str, Any],
    metrics: dict[str, float],
    status: str,
    fanout: dict[str, Any],
) -> list[dict[str, str]]:
    now = utc_now().strftime("%H:%M:%S UTC")
    fanout_duration = float(fanout.get("duration_ms") or 0)
    fanout_message = (
        f"{fanout.get('sources', len(SOURCE_KEYS))} source calls completed through FastAPI "
        f"fanout in {fanout_duration:,.0f} ms."
        if fanout.get("live")
        else "Demo data rendered without external source calls."
    )
    events = [
        {
            "time": now,
            "level": _event_level(status),
            "title": f"Grid status: {status}",
            "message": f"Stress index {metrics['stress_index']} with {metrics['balance_mw']:,.0f} MW balance.",
        },
        {
            "time": now,
            "level": "info",
            "title": "Async data refresh",
            "message": fanout_message,
        },
        {
            "time": now,
            "level": "info",
            "title": "Weather signal",
            "message": f"{noaa['temperature_f']} F current station average, {noaa['wind_speed_mph']} mph wind.",
        },
        {
            "time": now,
            "level": "info",
            "title": "Renewable mix",
            "message": f"Wind {ercot['wind_mw']:,.0f} MW, solar {ercot['solar_mw']:,.0f} MW.",
        },
        {
            "time": now,
            "level": "info",
            "title": "EIA fuel mix",
            "message": f"Latest period {eia['latest_period']}, {len(eia['fuel_mix'])} fuel categories normalized.",
        },
    ]

    for source in ("status",):
        if ercot[source]["state"] != "live" or eia[source]["state"] != "live" or noaa[source]["state"] != "live":
            events.append(
                {
                    "time": now,
                    "level": "warning",
                    "title": "Demo fallback active",
                    "message": "One or more external sources used fallback data. Check credentials and service reachability.",
                }
            )
            break

    return events


def _event_level(status: str) -> str:
    if status == "System Stress":
        return "danger"
    if status == "Elevated":
        return "warning"
    return "success"

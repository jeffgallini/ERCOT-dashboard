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
    empty_cpc_degree_day_forecast,
    empty_eia_snapshot,
    empty_eia_natural_gas,
    empty_ercot_snapshot,
    empty_ercot_public_dashboards,
    empty_load_zone_lmps,
    empty_noaa_snapshot,
    empty_supply_demand_snapshot,
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
DISPATCHABLE_FUELS = {"Natural Gas", "Coal and Lignite", "Nuclear", "Hydro", "Other"}
VARIABLE_RENEWABLE_FUELS = {"Wind", "Solar"}
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
            ercot = _snapshot_or_empty(results["ercot"], empty_ercot_snapshot)
            eia = _snapshot_or_empty(results["eia"], empty_eia_snapshot)
            noaa = _snapshot_or_empty(results["noaa"], empty_noaa_snapshot)
            supply_demand = _snapshot_or_empty(results["supply_demand"], empty_supply_demand_snapshot)
            ercot_dashboards = _snapshot_or_empty(results["ercot_dashboards"], empty_ercot_public_dashboards)
            eia_gas = _snapshot_or_empty(results["eia_gas"], empty_eia_natural_gas)
            climate = _snapshot_or_empty(results["cpc"], empty_cpc_degree_day_forecast)
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
    status = _system_status(metrics["stress_index"]) if _has_grid_measurements(ercot) else "Waiting for data"
    diagnostics = _build_system_diagnostics(
        ercot=ercot,
        supply_demand=supply_demand,
        ercot_dashboards=ercot_dashboards,
        metrics=metrics,
        system_status=status,
    )

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
        "diagnostics": diagnostics,
        "metrics": metrics,
        "trends": _build_kpi_trends(ercot, noaa, metrics, supply_demand),
        "events": [
            *list_operator_events(limit=10),
            *_build_events(ercot, eia, noaa, metrics, status, fanout),
            *diagnostics.get("signals", []),
        ],
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


def empty_dashboard_sources(*, status_message: str = "Waiting for source-specific async refresh.") -> dict[str, dict[str, Any]]:
    return {
        "ercot": empty_ercot_snapshot(status_message),
        "eia": empty_eia_snapshot(status_message),
        "noaa": empty_noaa_snapshot(status_message),
        "supply_demand": empty_supply_demand_snapshot(status_message),
        "ercot_dashboards": empty_ercot_public_dashboards(status_message),
        "eia_gas": empty_eia_natural_gas(status_message),
        "climate": empty_cpc_degree_day_forecast(status_message),
    }


def compose_dashboard_from_source_bundles(
    *,
    grid: dict[str, Any] | None = None,
    ercot_dashboards: dict[str, Any] | None = None,
    weather: dict[str, Any] | None = None,
    energy: dict[str, Any] | None = None,
    climate: dict[str, Any] | None = None,
    market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    defaults = empty_dashboard_sources(status_message="Waiting for source-specific async refresh.")
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
                    "ercot": (fetch_ercot_snapshot(client), empty_ercot_snapshot),
                    "supply_demand": (fetch_supply_demand_dashboard(client), empty_supply_demand_snapshot),
                },
            )

    return await _source_bundle_with_cache("grid", refresh)


async def get_ercot_dashboards_source_bundle() -> dict[str, Any]:
    async def refresh() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await _source_bundle(
                "ercot_dashboards",
                {
                    "ercot_dashboards": (fetch_ercot_public_dashboards(client), empty_ercot_public_dashboards),
                },
            )

    return await _source_bundle_with_cache("ercot_dashboards", refresh)


async def get_weather_source_bundle() -> dict[str, Any]:
    async def refresh() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await _source_bundle(
                "weather",
                {"noaa": (fetch_noaa_snapshot(client), empty_noaa_snapshot)},
            )

    return await _source_bundle_with_cache("weather", refresh)


async def get_energy_source_bundle() -> dict[str, Any]:
    async def refresh() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await _source_bundle(
                "energy",
                {
                    "eia": (fetch_eia_snapshot(client), empty_eia_snapshot),
                    "eia_gas": (fetch_eia_natural_gas(client), empty_eia_natural_gas),
                },
            )

    return await _source_bundle_with_cache("energy", refresh)


async def get_market_source_bundle() -> dict[str, Any]:
    async def refresh() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            return await _source_bundle(
                "market",
                {"load_zone_lmps": (fetch_ercot_load_zone_lmps(client), empty_load_zone_lmps)},
            )

    return await _source_bundle_with_cache("market", refresh)


async def get_climate_source_bundle() -> dict[str, Any]:
    async def refresh() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7.5, connect=3.0)) as client:
            return await _source_bundle(
                "climate",
                {"climate": (fetch_cpc_degree_day_forecast(client), empty_cpc_degree_day_forecast)},
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
        source_name: _snapshot_or_empty(results[source_name], fallback_factory)
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
    elif any(state == "partial" for state in states):
        state = "partial"
    elif any(state in {"stale"} for state in states):
        state = "stale"
    elif any(state in {"unavailable", "unknown"} for state in states):
        state = "unavailable"
    elif any(state == "waiting" for state in states):
        state = "waiting"
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
    elif state in {"partial", "stale"}:
        backoff_seconds = 60

    retry_after = ""
    if backoff_seconds:
        retry_after = (utc_now().astimezone(timezone.utc) + timedelta(seconds=backoff_seconds)).isoformat()

    return {
        "backoff_seconds": backoff_seconds,
        "retry_after": retry_after,
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


def _snapshot_or_empty(
    result: dict[str, Any] | BaseException,
    fallback_factory: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if isinstance(result, BaseException) and not isinstance(result, Exception):
        raise result
    if not isinstance(result, Exception):
        status = result.get("status") if isinstance(result, dict) else {}
        if isinstance(status, dict) and status.get("state") == "demo":
            return fallback_factory("Demo data is disabled for this dashboard.", state="unavailable")
        return result

    return fallback_factory(f"{type(result).__name__} while refreshing source.", state="unavailable")


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
    if load <= 0 or generation <= 0:
        return {
            "stress_index": 0.0,
            "balance_mw": 0.0,
            "renewable_share_pct": 0.0,
        }
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


def _has_grid_measurements(ercot: dict[str, Any]) -> bool:
    status = ercot.get("status") if isinstance(ercot.get("status"), dict) else {}
    return (
        status.get("state") in {"live", "partial", "stale"}
        and isinstance(ercot.get("load_mw"), int | float)
        and isinstance(ercot.get("generation_mw"), int | float)
        and float(ercot.get("load_mw") or 0) > 0
        and float(ercot.get("generation_mw") or 0) > 0
    )


def _build_kpi_trends(
    ercot: dict[str, Any],
    noaa: dict[str, Any],
    metrics: dict[str, float],
    supply_demand: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    if (
        not isinstance(ercot.get("load_mw"), int | float)
        or not isinstance(ercot.get("generation_mw"), int | float)
        or float(ercot.get("load_mw") or 0) <= 0
        or float(ercot.get("generation_mw") or 0) <= 0
    ):
        return {
            "load_mw": [],
            "generation_mw": [],
            "price_proxy": [],
            "wind_mw": [],
            "solar_mw": [],
            "net_load_mw": [],
            "stress_index": [],
        }

    load_actual = _supply_actual_series(supply_demand, "demand_mw")
    load_forecast = _supply_forecast_series(supply_demand, "demand_mw")
    generation_series = _supply_actual_series(supply_demand, "committed_capacity_mw")
    ercot_trends = ercot.get("trends", {})
    wind_actual = ercot_trends.get("wind_mw") or []
    solar_actual = ercot_trends.get("solar_mw") or []

    trends = {
        "load_mw": _with_forecast(
            load_actual or ercot_trends.get("load_mw") or [],
            load_forecast,
        ),
        "generation_mw": generation_series
        or ercot_trends.get("generation_mw")
        or [],
        "price_proxy": ercot_trends.get("price_proxy") or [],
        "wind_mw": wind_actual,
        "solar_mw": solar_actual,
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
        return []

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


def _build_system_diagnostics(
    *,
    ercot: dict[str, Any],
    supply_demand: dict[str, Any],
    ercot_dashboards: dict[str, Any],
    metrics: dict[str, float],
    system_status: str,
) -> dict[str, Any]:
    fuel_rows = _fuel_availability_rows(ercot_dashboards.get("fuel_mix", {}))
    outage = _outage_diagnostics(ercot_dashboards.get("outages", {}))
    ancillary = _ancillary_diagnostics(ercot_dashboards.get("ancillary", {}))
    renewables = _renewable_forecast_diagnostics(ercot_dashboards.get("combined_renewables", {}))
    fuel_gap = _largest_dispatchable_fuel_gap(fuel_rows)
    grid_available = _has_grid_measurements(ercot)
    summary = {
        "system_status": system_status,
        "stress_index": metrics.get("stress_index", 0.0),
        "reserve_margin_pct": ercot.get("reserve_margin_pct"),
        "price_usd_mwh": ercot.get("price_proxy"),
        "dispatchable_outages_mw": outage.get("dispatchable_mw"),
        "renewable_outages_mw": outage.get("renewable_mw"),
        "forced_outages_mw": outage.get("unplanned_mw"),
        "total_outages_mw": outage.get("total_mw"),
        "prc_mw": ancillary.get("prc_mw"),
        "online_reserve_mw": ancillary.get("online_reserve_mw"),
        "as_shortage_mw": ancillary.get("total_shortage_mw"),
        "renewable_forecast_delta_mw": renewables.get("combined_delta_mw"),
        "largest_fuel_gap_fuel": fuel_gap.get("fuel", "") if fuel_gap else "",
        "largest_fuel_gap_mw": fuel_gap.get("unavailable_mw") if fuel_gap else None,
        "minimum_margin_pct": (supply_demand.get("summary") or {}).get("minimum_margin_pct"),
    }
    signals = _diagnostic_signals(
        fuel_gap=fuel_gap,
        outage=outage,
        ancillary=ancillary,
        renewables=renewables,
        ercot=ercot,
        metrics=metrics,
        grid_available=grid_available,
    )
    status = _status(
        "System Diagnostics",
        "live" if signals or _has_diagnostic_measurements(fuel_rows, outage, ancillary, renewables, grid_available) else "waiting",
        "Real-time diagnostics are derived from ERCOT public dashboard feeds.",
    )
    return {
        "timestamp": utc_now().astimezone(timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
        "fuels": fuel_rows,
        "outages": outage,
        "ancillary": ancillary,
        "renewables": renewables,
        "signals": signals[:8],
    }


def _fuel_availability_rows(fuel_mix: dict[str, Any]) -> list[dict[str, Any]]:
    latest_mix = ((fuel_mix or {}).get("latest") or {}).get("mix") or []
    rows = []
    for item in latest_mix:
        if not isinstance(item, dict):
            continue
        fuel = str(item.get("fuel") or "").strip()
        if not fuel:
            continue
        generation = _number_or_none(item.get("generation_mw"))
        hsl = _number_or_none(item.get("hsl_mw"))
        capacity = _number_or_none(item.get("capacity_mw"))
        unavailable = _number_or_none(item.get("unavailable_mw"))
        if unavailable is None and hsl is not None and capacity is not None:
            unavailable = max(capacity - hsl, 0)
        headroom = _number_or_none(item.get("headroom_mw"))
        if headroom is None and generation is not None and hsl is not None:
            headroom = max(hsl - generation, 0)

        rows.append(
            {
                "fuel": fuel,
                "class": _fuel_class(fuel),
                "generation_mw": _rounded(generation),
                "hsl_mw": _rounded(hsl),
                "capacity_mw": _rounded(capacity),
                "unavailable_mw": _rounded(unavailable),
                "headroom_mw": _rounded(headroom),
                "share_pct": _rounded(_number_or_none(item.get("share_pct"))),
                "availability_pct": _availability_pct(hsl, capacity),
                "utilization_pct": _utilization_pct(generation, hsl),
            }
        )

    rows.sort(
        key=lambda row: (
            str(row.get("class")) != "dispatchable",
            -float(row.get("unavailable_mw") or 0),
            str(row.get("fuel") or ""),
        )
    )
    return rows


def _fuel_class(fuel: str) -> str:
    if fuel in DISPATCHABLE_FUELS:
        return "dispatchable"
    if fuel in VARIABLE_RENEWABLE_FUELS:
        return "variable renewable"
    if fuel == "Power Storage":
        return "storage"
    return "other"


def _availability_pct(hsl: float | None, capacity: float | None) -> float | None:
    if hsl is None or capacity is None or capacity <= 0:
        return None
    return round((hsl / capacity) * 100, 1)


def _utilization_pct(generation: float | None, hsl: float | None) -> float | None:
    if generation is None or hsl is None or hsl <= 0:
        return None
    return round((generation / hsl) * 100, 1)


def _largest_dispatchable_fuel_gap(fuel_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        row
        for row in fuel_rows
        if row.get("class") == "dispatchable" and isinstance(row.get("unavailable_mw"), int | float)
    ]
    return max(candidates, key=lambda row: float(row.get("unavailable_mw") or 0), default=None)


def _has_diagnostic_measurements(
    fuel_rows: list[dict[str, Any]],
    outage: dict[str, Any],
    ancillary: dict[str, Any],
    renewables: dict[str, Any],
    grid_available: bool,
) -> bool:
    return bool(
        grid_available
        or fuel_rows
        or any(_number_or_none(outage.get(key)) is not None for key in ("total_mw", "dispatchable_mw", "renewable_mw"))
        or any(_number_or_none(ancillary.get(key)) is not None for key in ("prc_mw", "online_reserve_mw"))
        or _number_or_none(renewables.get("combined_actual_mw")) is not None
    )


def _outage_diagnostics(outages: dict[str, Any]) -> dict[str, Any]:
    latest = (outages or {}).get("latest") or {}
    return {
        "timestamp": latest.get("timestamp") or (outages or {}).get("last_updated", ""),
        "planned_mw": _rounded(_number_or_none(latest.get("planned_mw"))),
        "unplanned_mw": _rounded(_number_or_none(latest.get("unplanned_mw"))),
        "total_mw": _rounded(_number_or_none(latest.get("total_mw"))),
        "dispatchable_mw": _rounded(_number_or_none(latest.get("dispatchable_mw"))),
        "renewable_mw": _rounded(_number_or_none(latest.get("renewable_mw"))),
        "source_url": (outages or {}).get("source_url", ""),
    }


def _ancillary_diagnostics(ancillary: dict[str, Any]) -> dict[str, Any]:
    products = []
    total_shortage = 0.0
    for product in (ancillary or {}).get("products", []) or []:
        if not isinstance(product, dict):
            continue
        capability = _number_or_none(product.get("capability_mw"))
        awards = _number_or_none(product.get("awards_mw"))
        shortage = max((awards or 0) - (capability or 0), 0) if awards is not None and capability is not None else 0
        total_shortage += shortage
        products.append(
            {
                "name": str(product.get("name") or "Ancillary service"),
                "capability_mw": _rounded(capability),
                "awards_mw": _rounded(awards),
                "shortage_mw": _rounded(shortage),
                "coverage_pct": _availability_pct(capability, awards) if awards else None,
            }
        )

    system = (ancillary or {}).get("system") or {}
    return {
        "timestamp": (ancillary or {}).get("last_updated", ""),
        "interval": (ancillary or {}).get("interval", ""),
        "prc_mw": _rounded(_number_or_none(system.get("prc_mw"))),
        "online_reserve_mw": _rounded(_number_or_none(system.get("online_reserve_mw"))),
        "online_offline_reserve_mw": _rounded(_number_or_none(system.get("online_offline_reserve_mw"))),
        "total_shortage_mw": _rounded(total_shortage),
        "products": products,
        "source_url": (ancillary or {}).get("source_url", ""),
    }


def _renewable_forecast_diagnostics(combined_renewables: dict[str, Any]) -> dict[str, Any]:
    latest = (combined_renewables or {}).get("latest_actual") or {}
    if not latest:
        actual_points = [
            point
            for point in (combined_renewables or {}).get("current_day", []) or []
            if isinstance(point, dict) and _number_or_none(point.get("combined_actual_mw")) is not None
        ]
        latest = actual_points[-1] if actual_points else {}

    actual = _number_or_none(latest.get("combined_actual_mw"))
    forecast = _number_or_none(latest.get("combined_forecast_mw"))
    wind_actual = _number_or_none(latest.get("wind_actual_mw"))
    wind_forecast = _number_or_none(latest.get("wind_forecast_mw"))
    solar_actual = _number_or_none(latest.get("solar_actual_mw"))
    solar_forecast = _number_or_none(latest.get("solar_forecast_mw"))
    return {
        "timestamp": latest.get("timestamp", ""),
        "combined_actual_mw": _rounded(actual),
        "combined_forecast_mw": _rounded(forecast),
        "combined_delta_mw": _rounded(actual - forecast) if actual is not None and forecast is not None else None,
        "wind_delta_mw": _rounded(wind_actual - wind_forecast)
        if wind_actual is not None and wind_forecast is not None
        else None,
        "solar_delta_mw": _rounded(solar_actual - solar_forecast)
        if solar_actual is not None and solar_forecast is not None
        else None,
        "source_url": (combined_renewables or {}).get("source_url", ""),
    }


def _diagnostic_signals(
    *,
    fuel_gap: dict[str, Any] | None,
    outage: dict[str, Any],
    ancillary: dict[str, Any],
    renewables: dict[str, Any],
    ercot: dict[str, Any],
    metrics: dict[str, float],
    grid_available: bool,
) -> list[dict[str, Any]]:
    event_time = utc_now().strftime("%H:%M:%S UTC")
    signals: list[dict[str, Any]] = []

    if fuel_gap and isinstance(fuel_gap.get("unavailable_mw"), int | float):
        gap = float(fuel_gap["unavailable_mw"])
        level = _high_signal_level(gap, warning=3_000, danger=8_000, success_below=1_500)
        title = f"{fuel_gap['fuel']} availability proxy"
        message = (
            f"{_mw(gap)} unavailable from seasonal capacity vs HSL; "
            f"generation {_mw(fuel_gap.get('generation_mw'))}, headroom {_mw(fuel_gap.get('headroom_mw'))}."
        )
        signals.append(_diagnostic_event(level, title, message, "ERCOT Fuel Mix", event_time))

    dispatchable = _number_or_none(outage.get("dispatchable_mw"))
    renewable = _number_or_none(outage.get("renewable_mw"))
    unplanned = _number_or_none(outage.get("unplanned_mw"))
    if any(value is not None and value > 0 for value in (dispatchable, renewable, unplanned)):
        outage_pressure = max(dispatchable or 0, unplanned or 0)
        level = _high_signal_level(outage_pressure, warning=12_000, danger=22_000, success_below=4_000)
        message = (
            f"Generation outage dashboard shows {_mw(dispatchable)} dispatchable, "
            f"{_mw(renewable)} renewable, and {_mw(unplanned)} forced/unplanned outage signal."
        )
        signals.append(_diagnostic_event(level, "Current outage mix", message, "ERCOT Generation Outages", event_time))

    prc = _number_or_none(ancillary.get("prc_mw"))
    reserve_margin = _number_or_none(ercot.get("reserve_margin_pct"))
    if prc is not None and prc > 0:
        level = "danger" if prc < 3_000 else "warning" if prc < 5_000 else "success"
        message = f"Physical responsive capability is {_mw(prc)}; reserve margin is {_pct(reserve_margin)}."
        signals.append(_diagnostic_event(level, "Reserve cushion", message, "ERCOT Ancillary Services", event_time))
    elif grid_available and reserve_margin is not None:
        level = "danger" if reserve_margin < 8 else "warning" if reserve_margin < 14 else "success"
        signals.append(
            _diagnostic_event(
                level,
                "Reserve margin",
                f"Dashboard reserve margin proxy is {_pct(reserve_margin)}.",
                "ERCOT Supply/Demand",
                event_time,
            )
        )

    shortage = _number_or_none(ancillary.get("total_shortage_mw"))
    if shortage is not None and shortage > 25:
        worst = max(
            ancillary.get("products", []),
            key=lambda product: float(product.get("shortage_mw") or 0),
            default={},
        )
        level = _high_signal_level(shortage, warning=100, danger=500)
        message = (
            f"AS awards exceed displayed capability by {_mw(shortage)}; "
            f"largest gap is {worst.get('name', 'an AS product')} at {_mw(worst.get('shortage_mw'))}."
        )
        signals.append(_diagnostic_event(level, "Ancillary service coverage", message, "ERCOT Ancillary Services", event_time))

    renewable_delta = _number_or_none(renewables.get("combined_delta_mw"))
    if renewable_delta is not None and abs(renewable_delta) >= 500:
        level = "danger" if renewable_delta <= -3_000 else "warning" if renewable_delta < -1_000 else "success"
        direction = "under forecast" if renewable_delta < 0 else "above forecast"
        message = (
            f"Combined wind and solar are {_mw(abs(renewable_delta))} {direction}; "
            f"wind delta {_mw(renewables.get('wind_delta_mw'))}, solar delta {_mw(renewables.get('solar_delta_mw'))}."
        )
        signals.append(_diagnostic_event(level, "Renewable forecast miss", message, "ERCOT Wind/Solar", event_time))

    price = _number_or_none(ercot.get("price_proxy"))
    if grid_available and price is not None and price >= 45:
        level = "danger" if price >= 250 else "warning" if price >= 100 else "info"
        label = ercot.get("price_label") or ercot.get("price_settlement_point") or "ERCOT RT LMP"
        message = f"{label} is ${price:,.2f}/MWh with stress index {metrics.get('stress_index', 0):.1f}."
        signals.append(_diagnostic_event(level, "Real-time price pressure", message, "ERCOT Market", event_time))

    if not signals and grid_available:
        signals.append(
            _diagnostic_event(
                "success",
                "Diagnostics nominal",
                "Fuel, reserve, outage, renewable, and price signals are inside demo thresholds.",
                "System Diagnostics",
                event_time,
            )
        )
    return signals


def _diagnostic_event(
    level: str,
    title: str,
    message: str,
    source: str,
    event_time: str,
) -> dict[str, Any]:
    return {
        "time": event_time,
        "level": level if level in {"danger", "warning", "success", "info"} else "info",
        "title": title,
        "message": message,
        "source": source,
    }


def _high_signal_level(
    value: float,
    *,
    warning: float,
    danger: float,
    success_below: float | None = None,
) -> str:
    if value >= danger:
        return "danger"
    if value >= warning:
        return "warning"
    if success_below is not None and value <= success_below:
        return "success"
    return "info"


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _rounded(value: float | None, *, ndigits: int = 1) -> float | None:
    return round(float(value), ndigits) if value is not None else None


def _mw(value: Any) -> str:
    number = _number_or_none(value)
    return f"{number:,.0f} MW" if number is not None else "N/A"


def _pct(value: Any) -> str:
    number = _number_or_none(value)
    return f"{number:.1f}%" if number is not None else "N/A"


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
            "message": (
                f"{noaa['temperature_f']} F current station average, {noaa['wind_speed_mph']} mph wind."
                if noaa.get("status", {}).get("state") in {"live", "partial", "stale"}
                else "Waiting for live NOAA/NWS station observations."
            ),
        },
        {
            "time": now,
            "level": "info",
            "title": "Renewable mix",
            "message": (
                f"Wind {ercot['wind_mw']:,.0f} MW, solar {ercot['solar_mw']:,.0f} MW."
                if _has_grid_measurements(ercot)
                else "Waiting for live ERCOT wind and solar telemetry."
            ),
        },
        {
            "time": now,
            "level": "info",
            "title": "EIA fuel mix",
            "message": f"Latest period {eia['latest_period']}, {len(eia['fuel_mix'])} fuel categories normalized.",
        },
    ]

    if ercot["status"]["state"] != "live" or eia["status"]["state"] != "live" or noaa["status"]["state"] != "live":
        events.append(
            {
                "time": now,
                "level": "warning",
                "title": "Live source pending",
                "message": "One or more external sources are waiting, partial, stale, or unavailable.",
            }
        )

    return events


def _event_level(status: str) -> str:
    if status == "System Stress":
        return "danger"
    if status == "Elevated":
        return "warning"
    return "success"

from __future__ import annotations

import asyncio
from copy import deepcopy
from collections.abc import Callable
from typing import Any

from ercot_dashboard.services.clients import utc_now
from ercot_dashboard.services.dashboard import _build_kpi_trends, _compute_metrics, _system_status


async def preview_scenarios(state: dict[str, Any]) -> dict[str, Any]:
    base, heatwave, wind = await asyncio.gather(
        _scenario_preview("Base case", state, None),
        _scenario_preview("Heatwave", state, apply_heatwave_scenario),
        _scenario_preview("Wind ramp", state, apply_wind_ramp_scenario),
    )
    return {
        "timestamp": utc_now().isoformat(),
        "strategy": "asyncio.gather",
        "cards": [base, heatwave, wind],
    }


async def _scenario_preview(
    label: str,
    state: dict[str, Any],
    transform: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> dict[str, Any]:
    await asyncio.sleep(0)
    baseline_stress = float(state["metrics"]["stress_index"])
    candidate = deepcopy(state) if transform is None else transform(state)
    ercot = candidate["ercot"]
    noaa = candidate["noaa"]
    metrics = candidate["metrics"]
    price = ercot.get("price_proxy")
    active_scenario = candidate.get("active_scenario") if transform is not None else None
    impacts = _scenario_impacts(state, candidate) if transform is not None else []
    return {
        "label": label,
        "status": candidate["system_status"],
        "summary": active_scenario.get("summary", "") if isinstance(active_scenario, dict) else "Current operating case.",
        "color": active_scenario.get("color", "cyan") if isinstance(active_scenario, dict) else "cyan",
        "stress_index": round(float(metrics["stress_index"]), 1),
        "stress_delta": round(float(metrics["stress_index"]) - baseline_stress, 1),
        "load_mw": round(float(ercot["load_mw"]), 1),
        "generation_mw": round(float(ercot["generation_mw"]), 1),
        "wind_mw": round(float(ercot["wind_mw"]), 1),
        "reserve_margin_pct": round(float(ercot["reserve_margin_pct"]), 1),
        "temperature_f": round(float(noaa["temperature_f"]), 1),
        "balance_mw": round(float(metrics["balance_mw"]), 1),
        "price_proxy": round(float(price), 2) if isinstance(price, int | float) else None,
        "impacts": impacts[:4],
    }


def apply_heatwave_scenario(state: dict[str, Any]) -> dict[str, Any]:
    baseline = deepcopy(state)
    updated = deepcopy(state)
    ercot = updated["ercot"]
    noaa = updated["noaa"]

    ercot["load_mw"] = round(float(ercot["load_mw"]) * 1.075, 1)
    ercot["solar_mw"] = round(float(ercot["solar_mw"]) * 0.965, 1)
    if isinstance(ercot.get("price_proxy"), int | float):
        ercot["price_proxy"] = round(float(ercot["price_proxy"]) * 1.18 + 6, 2)
    _shift_price_series(ercot, rt_multiplier=1.18, rt_increment=6, da_multiplier=1.08, da_increment=3)
    ercot["reserve_margin_pct"] = round(
        ((float(ercot["generation_mw"]) - float(ercot["load_mw"])) / max(float(ercot["load_mw"]), 1)) * 100,
        1,
    )
    noaa["temperature_f"] = round(float(noaa["temperature_f"]) + 8.5, 1)
    noaa["daily_high_f"] = round(float(noaa["daily_high_f"]) + 9.0, 1)

    _shift_supply_demand(updated, demand_multiplier=1.075)

    for zone in _load_zones(ercot):
        zone["load_mw"] = round(float(zone["load_mw"]) * 1.08, 1)
        if isinstance(zone.get("price_usd_mwh"), int | float):
            zone["price_usd_mwh"] = round(float(zone["price_usd_mwh"]) * 1.18 + 6, 2)
        zone["stress"] = round(min(100, float(zone["stress"]) + 13), 1)
    _sync_legacy_regions(ercot)

    _refresh_metrics(updated, "Heatwave simulation")
    _set_active_scenario(
        updated,
        baseline=baseline,
        scenario_id="heatwave",
        label="Heatwave Simulation",
        color="red",
        icon="tabler:temperature-sun",
        summary="Demand, temperature, and price pressure are layered onto the current ERCOT operating case.",
        steps=[
            {
                "label": "Demand shock",
                "value": "+7.5%",
                "message": "System load and current-day demand curves are lifted to reflect cooling demand.",
            },
            {
                "label": "Weather pressure",
                "value": "+8.5 F",
                "message": "NOAA current temperature and daily high are pushed into heat-stress territory.",
            },
            {
                "label": "Market pressure",
                "value": "+18%",
                "message": "Real-time price proxy and load-zone LMPs rise with scarcity pressure.",
            },
            {
                "label": "Renewable drag",
                "value": "-3.5%",
                "message": "Solar output eases down to model heat-related panel efficiency loss.",
            },
        ],
    )
    _prepend_event(
        updated,
        "danger",
        "Heatwave scenario applied",
        "Demand shock increased load and price pressure while solar efficiency eased downward.",
    )
    return updated


def apply_wind_ramp_scenario(state: dict[str, Any]) -> dict[str, Any]:
    baseline = deepcopy(state)
    updated = deepcopy(state)
    ercot = updated["ercot"]

    wind_gain = max(1800, float(ercot["wind_mw"]) * 0.18)
    ercot["wind_mw"] = round(float(ercot["wind_mw"]) + wind_gain, 1)
    ercot["generation_mw"] = round(float(ercot["generation_mw"]) + wind_gain * 0.9, 1)
    if isinstance(ercot.get("price_proxy"), int | float):
        ercot["price_proxy"] = round(max(12, float(ercot["price_proxy"]) * 0.88 - 3), 2)
    _shift_price_series(ercot, rt_multiplier=0.88, rt_increment=-3, da_multiplier=0.94, da_increment=-1)
    ercot["reserve_margin_pct"] = round(
        ((float(ercot["generation_mw"]) - float(ercot["load_mw"])) / max(float(ercot["load_mw"]), 1)) * 100,
        1,
    )

    _shift_supply_demand(updated, capacity_increment=wind_gain * 0.9, available_increment=wind_gain)

    for zone in _load_zones(ercot):
        zone["generation_mw"] = round(float(zone["generation_mw"]) * 1.035, 1)
        if isinstance(zone.get("price_usd_mwh"), int | float):
            zone["price_usd_mwh"] = round(max(0, float(zone["price_usd_mwh"]) * 0.88 - 3), 2)
        zone["stress"] = round(max(0, float(zone["stress"]) - 8), 1)
    _sync_legacy_regions(ercot)

    _refresh_metrics(updated, "Wind ramp simulation")
    _set_active_scenario(
        updated,
        baseline=baseline,
        scenario_id="wind",
        label="Wind Ramp Simulation",
        color="green",
        icon="tabler:wind",
        summary="A renewable ramp adds wind output, improves the reserve picture, and softens market pressure.",
        steps=[
            {
                "label": "Wind gain",
                "value": f"+{wind_gain:,.0f} MW",
                "message": "Wind generation increases by the larger of 1,800 MW or 18% of current output.",
            },
            {
                "label": "Capacity carry",
                "value": "90%",
                "message": "Most of the new wind output is carried into committed generation capacity.",
            },
            {
                "label": "Market relief",
                "value": "-12%",
                "message": "Real-time and day-ahead price series move lower as net load pressure falls.",
            },
            {
                "label": "Zone balance",
                "value": "-8",
                "message": "Load-zone stress scores ease while generation availability improves.",
            },
        ],
    )
    _prepend_event(
        updated,
        "success",
        "Wind ramp scenario applied",
        "Wind generation increased, reserve margin improved, and the price proxy moved lower.",
    )
    return updated


def _refresh_metrics(state: dict[str, Any], status_message: str) -> None:
    metrics = _compute_metrics(state["ercot"], state["noaa"])
    state["metrics"] = metrics
    state["system_status"] = _system_status(metrics["stress_index"])
    if state.get("supply_demand"):
        state["trends"] = _build_kpi_trends(state["ercot"], state["noaa"], metrics, state["supply_demand"])
    state["timestamp"] = utc_now().isoformat()
    state["scenario"] = status_message


def _load_zones(ercot: dict[str, Any]) -> list[dict[str, Any]]:
    zones = ercot.get("load_zones")
    if isinstance(zones, list) and zones:
        return zones
    return ercot.get("regions", [])


def _sync_legacy_regions(ercot: dict[str, Any]) -> None:
    if isinstance(ercot.get("load_zones"), list):
        ercot["regions"] = [dict(zone) for zone in ercot["load_zones"]]


def _shift_supply_demand(
    state: dict[str, Any],
    *,
    demand_multiplier: float = 1,
    capacity_increment: float = 0,
    available_increment: float = 0,
) -> None:
    supply_demand = state.get("supply_demand")
    if not supply_demand:
        return

    for point in supply_demand.get("current_day", []):
        if isinstance(point.get("demand_mw"), int | float):
            point["demand_mw"] = round(float(point["demand_mw"]) * demand_multiplier, 1)
        if isinstance(point.get("committed_capacity_mw"), int | float):
            point["committed_capacity_mw"] = round(float(point["committed_capacity_mw"]) + capacity_increment, 1)
        if isinstance(point.get("available_capacity_mw"), int | float):
            point["available_capacity_mw"] = round(float(point["available_capacity_mw"]) + available_increment, 1)

    for point in supply_demand.get("six_day", []):
        if isinstance(point.get("demand_mw"), int | float):
            point["demand_mw"] = round(float(point["demand_mw"]) * demand_multiplier, 1)
        if isinstance(point.get("available_capacity_mw"), int | float):
            point["available_capacity_mw"] = round(float(point["available_capacity_mw"]) + available_increment, 1)

    _refresh_supply_demand_summary(supply_demand)


def _shift_price_series(
    ercot: dict[str, Any],
    *,
    rt_multiplier: float,
    rt_increment: float,
    da_multiplier: float,
    da_increment: float,
) -> None:
    trends = ercot.get("trends", {})
    _shift_price_points(trends.get("price_proxy", []), multiplier=rt_multiplier, increment=rt_increment)

    price_series = ercot.get("price_series", {})
    _shift_price_points(price_series.get("rt_lmp", []), multiplier=rt_multiplier, increment=rt_increment)
    _shift_price_points(price_series.get("da_lmp", []), multiplier=da_multiplier, increment=da_increment)


def _shift_price_points(points: Any, *, multiplier: float, increment: float) -> None:
    if not isinstance(points, list):
        return
    for point in points:
        if not isinstance(point, dict):
            continue
        value = point.get("value")
        if isinstance(value, int | float):
            point["value"] = round(max(0, float(value) * multiplier + increment), 2)


def _refresh_supply_demand_summary(supply_demand: dict[str, Any]) -> None:
    points = supply_demand.get("current_day", [])
    actual = [point for point in points if not point.get("is_forecast")]
    source = actual or points
    supply_demand["latest"] = dict(source[-1]) if source else {}

    if not points:
        return
    peak = max(points, key=lambda point: float(point.get("demand_mw") or 0))
    margins = []
    for point in points:
        demand = float(point.get("demand_mw") or 0)
        capacity = float(point.get("available_capacity_mw") or point.get("committed_capacity_mw") or 0)
        if demand and capacity:
            margins.append((capacity - demand, ((capacity - demand) / demand) * 100))
    min_margin, min_margin_pct = min(margins, key=lambda margin: margin[0]) if margins else (0, 0)
    supply_demand["summary"] = {
        "actual_points": len(actual),
        "forecast_points": len([point for point in points if point.get("is_forecast")]),
        "peak_demand_mw": round(float(peak.get("demand_mw") or 0), 1),
        "peak_demand_timestamp": peak.get("timestamp", ""),
        "minimum_margin_mw": round(min_margin, 1),
        "minimum_margin_pct": round(min_margin_pct, 1),
    }


def _prepend_event(state: dict[str, Any], level: str, title: str, message: str) -> None:
    event = {
        "time": utc_now().strftime("%H:%M:%S UTC"),
        "level": level,
        "title": title,
        "message": message,
    }
    state["events"] = [event, *state.get("events", [])[:8]]


def _set_active_scenario(
    state: dict[str, Any],
    *,
    baseline: dict[str, Any],
    scenario_id: str,
    label: str,
    color: str,
    icon: str,
    summary: str,
    steps: list[dict[str, str]],
) -> None:
    state["active_scenario"] = {
        "id": scenario_id,
        "label": label,
        "color": color,
        "icon": icon,
        "summary": summary,
        "applied_at": utc_now().isoformat(),
        "status": state["system_status"],
        "impacts": _scenario_impacts(baseline, state),
        "steps": steps,
    }


def _scenario_impacts(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    specs = [
        ("Load", ("ercot", "load_mw"), "MW", 0, "down"),
        ("Generation", ("ercot", "generation_mw"), "MW", 0, "up"),
        ("Wind", ("ercot", "wind_mw"), "MW", 0, "up"),
        ("Solar", ("ercot", "solar_mw"), "MW", 0, "up"),
        ("Price", ("ercot", "price_proxy"), "$/MWh", 2, "down"),
        ("Reserve", ("ercot", "reserve_margin_pct"), "%", 1, "up"),
        ("Temperature", ("noaa", "temperature_f"), "F", 1, "down"),
        ("Stress", ("metrics", "stress_index"), "index", 1, "down"),
        ("Balance", ("metrics", "balance_mw"), "MW", 0, "up"),
    ]
    impacts = []
    for label, path, unit, precision, favorable_when in specs:
        impact = _metric_impact(
            label,
            _path_number(before, path),
            _path_number(after, path),
            unit=unit,
            precision=precision,
            favorable_when=favorable_when,
        )
        if impact:
            impacts.append(impact)
    return impacts


def _metric_impact(
    label: str,
    before: float | None,
    after: float | None,
    *,
    unit: str,
    precision: int,
    favorable_when: str,
) -> dict[str, Any] | None:
    if before is None or after is None:
        return None

    delta = round(after - before, precision)
    direction = "flat"
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"

    color = "gray"
    if direction == favorable_when:
        color = "green"
    elif direction != "flat":
        color = "red"

    return {
        "label": label,
        "unit": unit,
        "before": round(before, precision),
        "after": round(after, precision),
        "delta": delta,
        "direction": direction,
        "color": color,
        "after_label": _format_metric(after, unit=unit, precision=precision),
        "delta_label": _format_delta(delta, unit=unit, precision=precision),
    }


def _path_number(state: dict[str, Any], path: tuple[str, str]) -> float | None:
    section = state.get(path[0])
    if not isinstance(section, dict):
        return None
    value = section.get(path[1])
    return float(value) if isinstance(value, int | float) else None


def _format_metric(value: float, *, unit: str, precision: int) -> str:
    formatted = f"{value:,.{precision}f}"
    if unit == "$/MWh":
        return f"${formatted}"
    return f"{formatted} {unit}"


def _format_delta(value: float, *, unit: str, precision: int) -> str:
    formatted = f"{value:+,.{precision}f}"
    if unit == "$/MWh":
        return f"{formatted} $/MWh"
    return f"{formatted} {unit}"

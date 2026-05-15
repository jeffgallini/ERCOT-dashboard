from __future__ import annotations

import asyncio
from copy import deepcopy
import math
import os
import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True) or Path.cwd() / ".env")

ERCOT_BASE_URL = "https://api.ercot.com/api/public-reports"
ERCOT_SUPPLY_DEMAND_URL = "https://www.ercot.com/api/1/services/read/dashboards/supply-demand.json"
ERCOT_DASHBOARD_BASE_URL = "https://www.ercot.com/api/1/services/read/dashboards"
ERCOT_AUTH_URL = "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
ERCOT_CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"
ERCOT_SCOPE = f"openid {ERCOT_CLIENT_ID} offline_access"
ERCOT_PRICE_SETTLEMENT_POINT = "HB_NORTH"
ERCOT_PRICE_SETTLEMENT_POINT_LABEL = "North Hub RT LMP"
ERCOT_PRICE_SETTLEMENT_POINT_KEYS = (
    "settlementPoint",
    "settlementPointName",
    "settlementPointShortName",
    "Settlement Point",
    "Settlement Point Name",
    "settlement_point",
    "settlement_point_name",
)
ERCOT_PRICE_VALUE_KEYS = ("LMP", "lmp", "price", "rtLmp", "RTLMP", "RT LMP")
ERCOT_PRICE_TIMESTAMP_KEYS = ("RTDTimestamp", "rtdTimestamp", "timestamp", "SCEDTimestamp")
ERCOT_DAY_AHEAD_PRICE_VALUE_KEYS = (
    "settlementPointPrice",
    "SettlementPointPrice",
    "Settlement Point Price",
    "SPP",
    "price",
    "DALMP",
    "DA LMP",
    "LMP",
)
ERCOT_DAY_AHEAD_PRICE_DATE_KEYS = ("deliveryDate", "DeliveryDate", "delivery_date")
ERCOT_DAY_AHEAD_PRICE_HOUR_KEYS = ("hourEnding", "HourEnding", "deliveryHour", "DeliveryHour")
EIA_FUEL_MIX_URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
EIA_GAS_STORAGE_URL = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
EIA_DPR_PAGE_URL = "https://www.eia.gov/petroleum/drilling/"
EIA_STEO_URL = "https://api.eia.gov/v2/steo/data/"
NWS_API_BASE_URL = "https://api.weather.gov"
DEFAULT_NWS_USER_AGENT = "ERCOT Grid Pulse Demo (local development)"
CPC_DEGREE_DAY_FORECAST_URL = "https://www.cpc.ncep.noaa.gov/pacdir/DDdir/ddforecast.txt"
CPC_DEFAULT_REGION = "TEXAS"
ERCOT_PRIMARY_SUBSCRIPTION_KEY_NAMES = ("ERCOT_API_SUBSCRIPTION_KEY", "ERCOT_SUBSCRIPTION_KEY")
ERCOT_PRICE_SUBSCRIPTION_KEY_NAMES = (
    "ERCOT_API_SECONDARY_SUBSCRIPTION_KEY",
    "ERCOT_SECONDARY_SUBSCRIPTION_KEY",
)
CPC_HEADER_MARKER = (
    "NORMALS FORECAST HEATING COOLING (1981-2010) DEPARTURE YEAR MONTH "
    "90% MEAN 10% 90% MEAN 10% HDD CDD HDD CDD"
)
CPC_ROW_PATTERN = re.compile(
    r"\b(?P<year>\d{4})\s+(?P<month>\d{1,2})\s+"
    r"(?P<hdd_p90>-?\d+(?:\.\d*)?)\s+"
    r"(?P<hdd_mean>-?\d+(?:\.\d*)?)\s+"
    r"(?P<hdd_p10>-?\d+(?:\.\d*)?)\s+"
    r"(?P<cdd_p90>-?\d+(?:\.\d*)?)\s+"
    r"(?P<cdd_mean>-?\d+(?:\.\d*)?)\s+"
    r"(?P<cdd_p10>-?\d+(?:\.\d*)?)\s+"
    r"(?P<hdd_normal>-?\d+(?:\.\d*)?)\s+"
    r"(?P<cdd_normal>-?\d+(?:\.\d*)?)\s+"
    r"(?P<hdd_departure>-?\d+(?:\.\d*)?)\s+"
    r"(?P<cdd_departure>-?\d+(?:\.\d*)?)"
)

# NWS observation station IDs for the requested ERCOT-region airport weather points.
NOAA_AIRPORT_STATIONS: dict[str, dict[str, Any]] = {
    "DFW": {
        "name": "Dallas/Fort Worth",
        "station_id": "KDFW",
        "lat": 32.89744,
        "lon": -97.02196,
    },
    "IAH": {
        "name": "Houston Intercontinental",
        "station_id": "KIAH",
        "lat": 29.98438,
        "lon": -95.36072,
    },
    "AUS": {
        "name": "Austin Bergstrom",
        "station_id": "KAUS",
        "lat": 30.18311,
        "lon": -97.67989,
    },
    "LBB": {
        "name": "Lubbock",
        "station_id": "KLBB",
        "lat": 33.66578,
        "lon": -101.82330,
    },
    "SAT": {
        "name": "San Antonio",
        "station_id": "KSAT",
        "lat": 29.54429,
        "lon": -98.48395,
    },
    "ELP": {
        "name": "El Paso",
        "station_id": "KELP",
        "lat": 31.81234,
        "lon": -106.37737,
    },
}

REGION_POINTS = {
    "Houston": {"lat": 29.7604, "lon": -95.3698},
    "North": {"lat": 32.7767, "lon": -96.7970},
    "South": {"lat": 29.4241, "lon": -98.4936},
    "West": {"lat": 31.7619, "lon": -106.4850},
}

LOAD_ENDPOINTS = {
    "Houston": "/np3-910-er/2d_agg_load_summary_houston",
    "North": "/np3-910-er/2d_agg_load_summary_north",
    "South": "/np3-910-er/2d_agg_load_summary_south",
    "West": "/np3-910-er/2d_agg_load_summary_west",
}

LOAD_ZONE_SETTLEMENT_POINTS = {
    "Houston": "LZ_HOUSTON",
    "North": "LZ_NORTH",
    "South": "LZ_SOUTH",
    "West": "LZ_WEST",
}
LOAD_ZONE_FALLBACK_HOURS = 24

ERCOT_ENDPOINTS = {
    "load": "/np3-910-er/2d_agg_load_summary",
    "generation": "/np3-910-er/2d_agg_gen_summary",
    "wind": "/np4-733-cd/wpp_actual_5min_avg_values",
    "solar": "/np4-738-cd/spp_actual_5min_avg_values",
    "price": "/np6-788-cd/lmp_node_zone_hub",
    "day_ahead_price": "/np4-190-cd/dam_stlmnt_pnt_prices",
}

ERCOT_PUBLIC_DASHBOARDS = {
    "prc": "daily-prc.json",
    "fuel_mix": "fuel-mix.json",
    "storage": "energy-storage-resources.json",
    "combined_renewables": "combine-wind-solar.json",
    "dc_ties": "dc-tie-flows.json",
    "outages": "generation-outages.json",
    "ancillary": "ancillary-service-capacity-monitor.json",
}

ERCOT_PUBLIC_DASHBOARD_FEEDS = {
    "prc": {
        "title": "Physical Responsive Capability",
        "description": "ERCOT grid condition state and PRC time series.",
    },
    "fuel_mix": {
        "title": "Fuel Mix",
        "description": "Five-minute generation mix by resource type.",
    },
    "storage": {
        "title": "Energy Storage Resources",
        "description": "Current-day battery charging and discharging.",
    },
    "combined_renewables": {
        "title": "Combined Wind and Solar",
        "description": "Current-day wind and solar actuals plus hourly forecast.",
    },
    "dc_ties": {
        "title": "DC Tie Flows",
        "description": "Current-day DC tie flows by interface.",
    },
    "outages": {
        "title": "Generation Outages",
        "description": "Planned and unplanned generation outage signals.",
    },
    "ancillary": {
        "title": "Ancillary Service Capacity Monitor",
        "description": "Ancillary service capability and awards.",
    },
}

GENERATION_ENDPOINTS = {
    "Houston": "/np3-910-er/2d_agg_gen_summary_houston",
    "North": "/np3-910-er/2d_agg_gen_summary_north",
    "South": "/np3-910-er/2d_agg_gen_summary_south",
    "West": "/np3-910-er/2d_agg_gen_summary_west",
}

EIA_GAS_STORAGE_SERIES = {
    "east": "NW2_EPG0_SWO_R31_BCF",
    "midwest": "NW2_EPG0_SWO_R32_BCF",
    "lower_48": "NW2_EPG0_SWO_R48_BCF",
    "mountain": "NW2_EPG0_SWO_R34_BCF",
    "pacific": "NW2_EPG0_SWO_R35_BCF",
    "south_central": "NW2_EPG0_SWO_R33_BCF",
}

EIA_STEO_GAS_BALANCE_SERIES = {
    "supply_bcf_d": "NGPSUPP",
    "consumption_bcf_d": "NGTCPUS",
    "working_inventory_bcf": "NGWGPUS",
}

EIA_STEO_SERIES = {
    "henry_hub": "NGHHUUS",
    "south_central_inventory": "NGWG_SC",
}
EIA_STEO_DRILLING_SERIES = {
    "appalachia": {
        "label": "Appalachia",
        "active_rigs": "RIGSAP",
        "duc_wells": "DUCSAP",
        "new_wells_drilled": "NWDAP",
        "new_wells_completed": "NWCAP",
        "gas_per_rig_mmcf_d": "NGNWRAP",
    },
    "haynesville": {
        "label": "Haynesville",
        "active_rigs": "RIGSHA",
        "duc_wells": "DUCSHA",
        "new_wells_drilled": "NWDHA",
        "new_wells_completed": "NWCHA",
        "gas_per_rig_mmcf_d": "NGNWRHA",
    },
    "permian": {
        "label": "Permian",
        "active_rigs": "RIGSPM",
        "duc_wells": "DUCSPM",
        "new_wells_drilled": "NWDPM",
        "new_wells_completed": "NWCPM",
        "gas_per_rig_mmcf_d": "NGNWRPM",
    },
    "eagle_ford": {
        "label": "Eagle Ford",
        "active_rigs": "RIGSEF",
        "duc_wells": "DUCSEF",
        "new_wells_drilled": "NWDEF",
        "new_wells_completed": "NWCEF",
        "gas_per_rig_mmcf_d": "NGNWREF",
    },
    "bakken": {
        "label": "Bakken",
        "active_rigs": "RIGSBK",
        "duc_wells": "DUCSBK",
        "new_wells_drilled": "NWDBK",
        "new_wells_completed": "NWCBK",
        "gas_per_rig_mmcf_d": "NGNWRBK",
    },
    "rest_lower_48": {
        "label": "Rest of Lower 48",
        "active_rigs": "RIGSR48",
        "duc_wells": "DUCSR48",
        "new_wells_drilled": "NWDR48",
        "new_wells_completed": "NWCR48",
        "gas_per_rig_mmcf_d": "NGNWRR48",
    },
}

EIA_NATURAL_GAS_FEEDS = {
    "storage": {
        "title": "Weekly Natural Gas Storage",
        "description": "Lower 48 and regional working gas in underground storage.",
        "source_url": EIA_GAS_STORAGE_URL,
    },
    "balance": {
        "title": "Natural Gas Supply, Demand, and Inventory",
        "description": "STEO monthly supply, consumption, and working inventory.",
        "source_url": EIA_STEO_URL,
    },
    "steo": {
        "title": "Natural Gas STEO Outlook",
        "description": "Henry Hub price and South Central inventory outlook.",
        "source_url": EIA_STEO_URL,
    },
}

_ercot_token_lock = asyncio.Lock()
_ercot_cached_token: str | None = None
_ercot_token_expires_at: datetime | None = None
_ercot_cached_token_kind: str | None = None
_ercot_snapshot_cache: dict[str, Any] | None = None
_ercot_snapshot_expires_at: datetime | None = None
_ercot_payload_cache: dict[str, dict[str, Any]] = {}
_ercot_payload_cache_expires_at: dict[str, datetime] = {}
_ercot_payload_cache_stored_at: dict[str, datetime] = {}
_rt_lmp_rows_cache: dict[str, list[dict[str, Any]]] = {}
_rt_lmp_last_refresh_at: dict[str, datetime] = {}
_ercot_public_api_rate_lock = asyncio.Lock()
_ercot_public_api_last_request_at: float | None = None

ERCOT_REPORTS = {
    "system-load": {
        "title": "2 Day Aggregated Load Summary",
        "endpoint": ERCOT_ENDPOINTS["load"],
        "params": "load",
    },
    "system-generation": {
        "title": "2 Day Aggregated Generation Summary",
        "endpoint": ERCOT_ENDPOINTS["generation"],
        "params": "generation",
    },
    "wind-5min": {
        "title": "Wind Power Production - Actual 5-Minute Averaged Values",
        "endpoint": ERCOT_ENDPOINTS["wind"],
        "params": "wind",
    },
    "solar-5min": {
        "title": "Solar Power Production - Actual 5-Minute Averaged Values",
        "endpoint": ERCOT_ENDPOINTS["solar"],
        "params": "solar",
    },
    "hb-north-lmp": {
        "title": ERCOT_PRICE_SETTLEMENT_POINT_LABEL,
        "endpoint": ERCOT_ENDPOINTS["price"],
        "params": "price",
    },
    "hb-north-da-lmp": {
        "title": "North Hub DA LMP",
        "endpoint": ERCOT_ENDPOINTS["day_ahead_price"],
        "params": "day_ahead_price",
    },
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _demo_wave(base: float, amplitude: float, period_hours: float, offset: float = 0) -> float:
    now = utc_now()
    hour = now.hour + now.minute / 60
    return base + amplitude * math.sin(((hour + offset) / period_hours) * math.tau)


def _status(source: str, state: str, message: str = "") -> dict[str, str]:
    return {"source": source, "state": state, "message": message}


def empty_ercot_snapshot(message: str = "Waiting for live ERCOT grid data.", *, state: str = "waiting") -> dict[str, Any]:
    load_zones = [
        {
            "name": name,
            "settlement_point": LOAD_ZONE_SETTLEMENT_POINTS[name],
            "lat": point["lat"],
            "lon": point["lon"],
            "load_mw": 0.0,
            "generation_mw": 0.0,
            "price_usd_mwh": None,
            "stress": 0.0,
        }
        for name, point in REGION_POINTS.items()
    ]
    return {
        "load_mw": 0.0,
        "generation_mw": 0.0,
        "wind_mw": 0.0,
        "solar_mw": 0.0,
        "price_proxy": None,
        "price_settlement_point": ERCOT_PRICE_SETTLEMENT_POINT,
        "price_label": ERCOT_PRICE_SETTLEMENT_POINT_LABEL,
        "price_series": {"settlement_point": ERCOT_PRICE_SETTLEMENT_POINT, "label": "North Hub", "rt_lmp": [], "da_lmp": []},
        "price_status": _status("ERCOT RT/DA LMP", state, message),
        "reserve_margin_pct": 0.0,
        "load_zones": load_zones,
        "regions": [dict(zone) for zone in load_zones],
        "trends": {"load_mw": [], "generation_mw": [], "wind_mw": [], "solar_mw": [], "price_proxy": []},
        "status": _status("ERCOT", state, message),
    }


def empty_supply_demand_snapshot(message: str = "Waiting for live ERCOT supply and demand data.", *, state: str = "waiting") -> dict[str, Any]:
    return {
        "timestamp": utc_now().isoformat(),
        "last_updated": "",
        "latest": {},
        "current_day": [],
        "six_day": [],
        "summary": {
            "peak_demand_mw": 0.0,
            "minimum_margin_pct": 0.0,
            "forecast_points": 0,
        },
        "status": _status("ERCOT Supply/Demand", state, message),
    }


def empty_ercot_public_dashboards(message: str = "Waiting for live ERCOT public dashboard feeds.", *, state: str = "waiting") -> dict[str, Any]:
    return {
        "timestamp": utc_now().isoformat(),
        "prc": {"last_updated": "", "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['prc']}", "condition": {}, "latest_prc_mw": None, "series": []},
        "fuel_mix": {"last_updated": "", "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['fuel_mix']}", "fuel_types": [], "series": [], "latest": {"mix": []}},
        "storage": {"last_updated": "", "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['storage']}", "current_day": [], "previous_day": [], "latest": {}, "summary": {}},
        "combined_renewables": {
            "last_updated": "",
            "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['combined_renewables']}",
            "current_day": [],
            "latest_actual": {},
            "summary": {},
        },
        "outages": {"last_updated": "", "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['outages']}", "current_outages_mw": None, "types": [], "current": [], "previous": [], "latest": {}},
        "ancillary": {"last_updated": "", "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['ancillary']}", "interval": "", "products": [], "system": {}, "groups": {}},
        "dc_ties": {
            "last_updated": "",
            "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['dc_ties']}",
            "current_day": [],
            "series": {},
            "latest": {},
            "summary": {},
        },
        "status": _status("ERCOT Dashboards", state, message),
    }


def empty_eia_snapshot(message: str = "Waiting for live EIA fuel data.", *, state: str = "waiting") -> dict[str, Any]:
    return {
        "fuel_mix": {},
        "latest_period": "",
        "total_mwh": 0.0,
        "status": _status("EIA", state, message),
    }


def empty_eia_natural_gas(message: str = "Waiting for live EIA natural gas data.", *, state: str = "waiting") -> dict[str, Any]:
    return {
        "timestamp": utc_now().isoformat(),
        "storage": {"source_url": EIA_GAS_STORAGE_URL, "series": [], "latest": {}, "summary": {}},
        "balance": {"source_url": EIA_STEO_URL, "series": [], "latest": {}, "summary": {}},
        "steo": {"source_url": EIA_STEO_URL, "series": [], "latest": {}, "summary": {}},
        "wells": {
            "source_url": EIA_STEO_URL,
            "source_page": EIA_DPR_PAGE_URL,
            "series": [],
            "regions": [],
            "latest": {},
            "summary": {},
        },
        "status": _status("EIA Natural Gas", state, message),
    }


def empty_noaa_snapshot(message: str = "Waiting for live NOAA/NWS observations.", *, state: str = "waiting") -> dict[str, Any]:
    return {
        "timestamp": utc_now().isoformat(),
        "temperature_f": 0.0,
        "daily_high_f": 0.0,
        "daily_low_f": 0.0,
        "wind_speed_mph": 0.0,
        "precipitation_in": 0.0,
        "observed_date": "",
        "observed_at": "",
        "airport_count": 0,
        "airports": [],
        "station": "NWS current airport observations",
        "stream_url": "/ws/weather",
        "status": _status("NOAA", state, message),
    }


def empty_cpc_degree_day_forecast(
    message: str = "Waiting for live NOAA CPC degree-day forecast.",
    *,
    region: str = CPC_DEFAULT_REGION,
    state: str = "waiting",
) -> dict[str, Any]:
    normalized_region = _normalize_region_name(region)
    return {
        "timestamp": utc_now().isoformat(),
        "issued": "",
        "region": normalized_region,
        "states": _cpc_states(normalized_region, ""),
        "source_url": CPC_DEGREE_DAY_FORECAST_URL,
        "rows": [],
        "regions": [],
        "summary": _degree_day_summary([]),
        "status": _status("NOAA CPC", state, message),
    }


def empty_load_zone_lmps(message: str = "Waiting for live ERCOT load-zone LMPs.", *, state: str = "waiting") -> dict[str, Any]:
    return {
        "timestamp": utc_now().isoformat(),
        "complete": False,
        "status": _status("ERCOT Load Zone RT LMP", state, message),
        "zones": [
            {
                "name": zone,
                "settlement_point": settlement_point,
                "price_usd_mwh": None,
                "timestamp": "",
                "status": state,
                "diagnostic": {"message": message},
            }
            for zone, settlement_point in LOAD_ZONE_SETTLEMENT_POINTS.items()
        ],
    }


def _ercot_failure_message(failures: dict[str, BaseException]) -> str:
    parts = []
    for name, exc in failures.items():
        parts.append(f"{name}: {_short_error(exc)}")
    return "; ".join(parts)


def _short_error(exc: BaseException) -> str:
    message = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    return message[:180]


def _latest_row(payload: dict[str, Any]) -> dict[str, Any]:
    rows = _report_rows(payload)
    return rows[0] if rows else {}


def _report_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _coerce_rows(payload.get("data", []))
    if rows:
        return rows

    data = payload.get("data", [])
    fields = payload.get("fields", [])
    field_names = []
    for field in fields:
        if isinstance(field, dict) and field.get("name"):
            field_names.append(str(field["name"]))
        elif field:
            field_names.append(str(field))

    if not isinstance(data, list) or not field_names:
        return []

    mapped_rows = []
    for row in data:
        if isinstance(row, list | tuple):
            mapped_rows.append(dict(zip(field_names, row)))
    return mapped_rows


def _coerce_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]

    if not isinstance(data, dict):
        return []

    for key in ("records", "items", "rows", "results"):
        nested = data.get(key)
        if isinstance(nested, list):
            return [row for row in nested if isinstance(row, dict)]

    list_values = {key: value for key, value in data.items() if isinstance(value, list)}
    if not list_values:
        return [data]

    length = max(len(value) for value in list_values.values())
    rows: list[dict[str, Any]] = []
    for index in range(length):
        rows.append(
            {
                key: value[index] if isinstance(value, list) and index < len(value) else value
                for key, value in data.items()
            }
        )
    return rows


def _num(row: dict[str, Any], *keys: str, default: float = 0) -> float:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is None:
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            continue
    return default


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | list[tuple[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = await _get_response(client, url, params=params, headers=headers)
    response.raise_for_status()
    return response.json()


async def _get_response(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | list[tuple[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    if _is_ercot_public_api_url(url):
        await _throttle_ercot_public_api_request()
    return await client.get(url, params=params, headers=headers)


def _is_ercot_public_api_url(url: str) -> bool:
    return url.startswith(ERCOT_BASE_URL)


async def _throttle_ercot_public_api_request() -> None:
    global _ercot_public_api_last_request_at

    interval_seconds = _ercot_public_api_interval_seconds()
    loop = asyncio.get_running_loop()
    async with _ercot_public_api_rate_lock:
        if _ercot_public_api_last_request_at is not None:
            elapsed = loop.time() - _ercot_public_api_last_request_at
            delay = interval_seconds - elapsed
            if delay > 0:
                await asyncio.sleep(delay)
        _ercot_public_api_last_request_at = loop.time()


def _ercot_public_api_interval_seconds() -> float:
    requests_per_minute = _env_int("ERCOT_PUBLIC_API_REQUESTS_PER_MINUTE", 30, minimum=1, maximum=30)
    cushion_ms = _env_int("ERCOT_PUBLIC_API_RATE_CUSHION_MS", 150, minimum=0, maximum=1000)
    return (60 / requests_per_minute) + (cushion_ms / 1000)


async def _get_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> str:
    response = await client.get(url, headers=headers)
    response.raise_for_status()
    return response.text


def _env_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return ""


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


def list_ercot_reports() -> list[dict[str, Any]]:
    reports = []
    for report_name, config in ERCOT_REPORTS.items():
        endpoint = str(config["endpoint"])
        reports.append(
            {
                "name": report_name,
                "title": config["title"],
                "ercot_url": ERCOT_BASE_URL + endpoint,
                "local_url": f"/api/ercot/report/{report_name}",
                "default_params": _ercot_params(str(config["params"])),
            }
        )
    return reports


def list_ercot_zone_reports() -> list[dict[str, Any]]:
    reports = []
    for zone in LOAD_ZONE_SETTLEMENT_POINTS:
        reports.extend(
            [
                {
                    "name": f"{zone.lower()}-load",
                    "title": f"{zone} Load Zone Load Summary",
                    "ercot_url": ERCOT_BASE_URL + LOAD_ENDPOINTS[zone],
                    "local_url": f"/api/ercot/load-zones/{zone.lower()}/load",
                    "default_params": _ercot_params("load"),
                },
                {
                    "name": f"{zone.lower()}-generation",
                    "title": f"{zone} Load Zone Generation Summary",
                    "ercot_url": ERCOT_BASE_URL + GENERATION_ENDPOINTS[zone],
                    "local_url": f"/api/ercot/load-zones/{zone.lower()}/generation",
                    "default_params": _ercot_params("generation"),
                },
            ]
        )
    return reports


def list_ercot_public_dashboard_feeds() -> list[dict[str, Any]]:
    feeds = []
    for name, filename in ERCOT_PUBLIC_DASHBOARDS.items():
        config = ERCOT_PUBLIC_DASHBOARD_FEEDS[name]
        feeds.append(
            {
                "name": name,
                "title": config["title"],
                "description": config["description"],
                "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{filename}",
                "local_url": f"/api/ercot/public-dashboards/{name.replace('_', '-')}",
            }
        )
    return feeds


def list_eia_natural_gas_feeds() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "title": str(config["title"]),
            "description": str(config["description"]),
            "source_url": str(config["source_url"]),
            "local_url": f"/api/eia/natural-gas/{name}",
        }
        for name, config in EIA_NATURAL_GAS_FEEDS.items()
    ]


async def get_ercot_debug_status(client: httpx.AsyncClient, *, check_reports: bool = False) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "timestamp": utc_now().isoformat(),
        "environment": _ercot_environment_status(),
        "auth": {"ok": False, "message": ""},
        "reports": [],
        "documentation": {
            "authentication": "https://developer.ercot.com/applications/pubapi/user-guide/registration-and-authentication/",
            "using_api": "https://developer.ercot.com/applications/pubapi/user-guide/using-api/",
            "specs": "https://github.com/ercot/api-specs",
        },
    }

    try:
        headers = await _ercot_headers(client)
    except Exception as exc:
        diagnostics["auth"] = {"ok": False, "error_type": type(exc).__name__, "message": str(exc)}
        return diagnostics

    try:
        response = await _get_response(client, ERCOT_BASE_URL, headers=headers)
        diagnostics["auth"] = {
            "ok": 200 <= response.status_code < 300,
            "status_code": response.status_code,
            "message": _response_message(response),
        }
    except Exception as exc:
        diagnostics["auth"] = {"ok": False, "error_type": type(exc).__name__, "message": str(exc)}
        return diagnostics

    if check_reports and diagnostics["auth"]["ok"]:
        for report in list_ercot_reports():
            try:
                payload = await fetch_ercot_report(client, report["name"], size=1)
                diagnostics["reports"].append(
                    {
                        "name": report["name"],
                        "ok": True,
                        "row_count": payload["row_count"],
                        "sample_keys": payload["sample_keys"],
                    }
                )
            except Exception as exc:
                diagnostics["reports"].append(
                    {"name": report["name"], "ok": False, "error_type": type(exc).__name__, "message": str(exc)}
                )

    return diagnostics


async def fetch_ercot_report(
    client: httpx.AsyncClient,
    report_name: str,
    *,
    size: int = 5,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    settlement_point: str | None = None,
) -> dict[str, Any]:
    normalized_name = report_name.strip().lower()
    if normalized_name not in ERCOT_REPORTS:
        valid = ", ".join(sorted(ERCOT_REPORTS))
        raise ValueError(f"Unknown ERCOT report '{report_name}'. Valid reports: {valid}.")

    size = max(1, min(1000, int(size)))
    config = ERCOT_REPORTS[normalized_name]
    if normalized_name == "hb-north-lmp":
        params = _rt_lmp_report_params(
            start_time=start_time,
            end_time=end_time,
            settlement_point=settlement_point,
            size=size,
        )
    else:
        params = _ercot_params(str(config["params"])) | {"size": min(size, 50)}
        if settlement_point and normalized_name == "hb-north-da-lmp":
            params["settlementPoint"] = settlement_point.strip().upper()
    headers = await _ercot_headers(client, for_price=_is_price_report(normalized_name))
    if normalized_name == "hb-north-lmp":
        payload = await _get_ercot_report_json(
            client,
            normalized_name,
            str(config["endpoint"]),
            params=params,
            headers=headers,
            cache_time_window=True,
        )
    else:
        payload = await _get_ercot_report_json(
            client,
            normalized_name,
            str(config["endpoint"]),
            params=params,
            headers=headers,
        )
    rows = _report_rows(payload)

    return {
        "timestamp": utc_now().isoformat(),
        "name": normalized_name,
        "title": config["title"],
        "ercot_url": ERCOT_BASE_URL + str(config["endpoint"]),
        "params": params,
        "row_count": len(rows),
        "sample_keys": sorted({str(key) for row in rows[:size] for key in row}),
        "rows": rows[:size],
        "meta": payload.get("_meta", {}),
        "report": payload.get("report", {}),
        "cache_status": payload.get("__local_cache_status"),
    }


async def fetch_ercot_zone_report(
    client: httpx.AsyncClient,
    zone_name: str,
    report_kind: str,
    *,
    size: int = 20,
) -> dict[str, Any]:
    zone = _normalize_load_zone_name(zone_name)
    kind = _normalize_feed_name(report_kind)
    if kind not in {"load", "generation"}:
        raise ValueError("ERCOT zone report kind must be 'load' or 'generation'.")

    size = max(1, min(50, int(size)))
    endpoint = LOAD_ENDPOINTS[zone] if kind == "load" else GENERATION_ENDPOINTS[zone]
    title = f"{zone} Load Zone {'Load Summary' if kind == 'load' else 'Generation Summary'}"
    params = _ercot_params(kind) | {"size": size}
    headers = await _ercot_headers(client)
    payload = await _get_ercot_report_json(
        client,
        f"{kind}-zone-{zone.lower()}",
        endpoint,
        params=params,
        headers=headers,
    )
    rows = _report_rows(payload)

    return {
        "timestamp": utc_now().isoformat(),
        "name": f"{zone.lower()}-{kind}",
        "title": title,
        "ercot_url": ERCOT_BASE_URL + endpoint,
        "params": params,
        "row_count": len(rows),
        "sample_keys": sorted({str(key) for row in rows[:size] for key in row}),
        "rows": rows[:size],
        "meta": payload.get("_meta", {}),
        "report": payload.get("report", {}),
        "cache_status": payload.get("__local_cache_status"),
    }


def _normalize_load_zone_name(value: str) -> str:
    normalized = str(value).strip().replace("-", " ").replace("_", " ").lower()
    for zone in LOAD_ZONE_SETTLEMENT_POINTS:
        if zone.lower() == normalized:
            return zone
    valid = ", ".join(zone.lower() for zone in LOAD_ZONE_SETTLEMENT_POINTS)
    raise ValueError(f"Unknown ERCOT load zone '{value}'. Valid zones: {valid}.")


async def fetch_ercot_load_zone_lmps(client: httpx.AsyncClient) -> dict[str, Any]:
    try:
        headers = await _ercot_headers(client, for_price=True)
    except Exception as exc:
        return _load_zone_lmp_response({}, {"auth": exc})

    requests = {
        zone: _get_ercot_report_json(
            client,
            f"map-price-{zone.lower()}",
            ERCOT_ENDPOINTS["price"],
            params=_load_zone_lmp_params(settlement_point),
            headers=headers,
        )
        for zone, settlement_point in LOAD_ZONE_SETTLEMENT_POINTS.items()
    }
    responses = await asyncio.gather(*requests.values(), return_exceptions=True)
    payloads: dict[str, dict[str, Any]] = {}
    failures: dict[str, BaseException] = {}
    for zone, response in zip(requests.keys(), responses):
        if isinstance(response, BaseException):
            failures[zone] = response
        else:
            response["__load_zone_query_status"] = {
                "mode": "primary",
                "hours": 2,
                "settlement_point": LOAD_ZONE_SETTLEMENT_POINTS[zone],
            }
            payloads[zone] = response

    missing_zones = _missing_load_zone_lmp_zones(payloads, failures)
    if missing_zones:
        fallback_requests = {
            zone: _get_ercot_report_json(
                client,
                f"map-price-{zone.lower()}-fallback",
                ERCOT_ENDPOINTS["price"],
                params=_load_zone_lmp_params(
                    LOAD_ZONE_SETTLEMENT_POINTS[zone],
                    hours=LOAD_ZONE_FALLBACK_HOURS,
                    size=12,
                ),
                headers=headers,
            )
            for zone in missing_zones
        }
        fallback_responses = await asyncio.gather(*fallback_requests.values(), return_exceptions=True)
        for zone, response in zip(fallback_requests.keys(), fallback_responses):
            if isinstance(response, BaseException):
                failures[f"{zone} fallback"] = response
                continue
            response["__load_zone_query_status"] = {
                "mode": "fallback",
                "hours": LOAD_ZONE_FALLBACK_HOURS,
                "settlement_point": LOAD_ZONE_SETTLEMENT_POINTS[zone],
            }
            if _payload_has_lmp(response, LOAD_ZONE_SETTLEMENT_POINTS[zone]):
                payloads[zone] = response

    return _load_zone_lmp_response(payloads, failures)


def _missing_load_zone_lmp_zones(
    payloads: dict[str, dict[str, Any]],
    failures: dict[str, BaseException],
) -> list[str]:
    missing = []
    for zone, settlement_point in LOAD_ZONE_SETTLEMENT_POINTS.items():
        if zone in failures:
            continue
        payload = payloads.get(zone, {})
        if not _payload_has_lmp(payload, settlement_point):
            missing.append(zone)
    return missing


def _payload_has_lmp(payload: dict[str, Any], settlement_point: str) -> bool:
    rows = _price_rows_for_settlement(_report_rows(payload), settlement_point)
    return bool(_latest_price_row(rows))


def _load_zone_lmp_response(
    payloads: dict[str, dict[str, Any]],
    failures: dict[str, BaseException],
) -> dict[str, Any]:
    zones = []
    cache_messages = []
    for zone, settlement_point in LOAD_ZONE_SETTLEMENT_POINTS.items():
        payload = payloads.get(zone, {})
        raw_rows = _report_rows(payload)
        rows = _price_rows_for_settlement(raw_rows, settlement_point)
        row = _latest_price_row(rows)
        price = _maybe_num(row, *ERCOT_PRICE_VALUE_KEYS) if row else None
        cache_status = payload.get("__local_cache_status")
        query_status = payload.get("__load_zone_query_status") if isinstance(payload, dict) else {}
        if isinstance(cache_status, dict) and cache_status.get("message"):
            cache_messages.append(str(cache_status["message"]))
        zone_status = _load_zone_price_status(price, zone, failures, query_status)
        zones.append(
            {
                "name": zone,
                "settlement_point": settlement_point,
                "price_usd_mwh": round(price, 2) if price is not None else None,
                "timestamp": _raw_text(row, *ERCOT_PRICE_TIMESTAMP_KEYS) if row else "",
                "status": zone_status,
                "diagnostic": _load_zone_lmp_diagnostic(raw_rows, rows, settlement_point, query_status),
            }
        )

    missing = [zone["name"] for zone in zones if zone["price_usd_mwh"] is None]
    stale = [zone["name"] for zone in zones if zone["status"] == "stale"]
    messages = []
    if failures:
        messages.append(_ercot_failure_message(failures))
    if missing:
        messages.append(f"Missing load zone LMP rows: {', '.join(missing)}")
    if stale:
        messages.append(f"Stale load zone LMP rows from widened query window: {', '.join(stale)}")
    messages.extend(cache_messages)

    if not missing and not stale and not failures and not cache_messages:
        status = _status("ERCOT Load Zone RT LMP", "live")
    elif any(zone["price_usd_mwh"] is not None for zone in zones):
        status_state = "stale" if (cache_messages or stale) and not failures and not missing else "partial"
        status = _status("ERCOT Load Zone RT LMP", status_state, "; ".join(messages))
    else:
        status = _status("ERCOT Load Zone RT LMP", "unavailable", "; ".join(messages))

    return {
        "timestamp": utc_now().isoformat(),
        "complete": status["state"] == "live",
        "status": status,
        "zones": zones,
    }


def _load_zone_price_status(
    price: float | None,
    zone: str,
    failures: dict[str, BaseException],
    query_status: Any,
) -> str:
    if price is None or zone in failures:
        return "unavailable"
    if isinstance(query_status, dict) and query_status.get("mode") == "fallback":
        return "stale"
    return "live"


def _load_zone_lmp_diagnostic(
    raw_rows: Sequence[dict[str, Any]],
    matched_rows: Sequence[dict[str, Any]],
    settlement_point: str,
    query_status: Any,
) -> dict[str, Any]:
    sampled_settlement_points = []
    for row in raw_rows[:8]:
        point = _settlement_point(row)
        if point and point not in sampled_settlement_points:
            sampled_settlement_points.append(point)
    return {
        "raw_row_count": len(raw_rows),
        "matched_row_count": len(matched_rows),
        "sample_settlement_points": sampled_settlement_points,
        "query": query_status if isinstance(query_status, dict) else {},
        "message": _load_zone_lmp_diagnostic_message(
            settlement_point,
            raw_rows,
            matched_rows,
            sampled_settlement_points,
            query_status,
        ),
    }


def _load_zone_lmp_diagnostic_message(
    settlement_point: str,
    raw_rows: Sequence[dict[str, Any]],
    matched_rows: Sequence[dict[str, Any]],
    sampled_settlement_points: Sequence[str],
    query_status: Any,
) -> str:
    if matched_rows:
        mode = query_status.get("mode") if isinstance(query_status, dict) else "primary"
        if mode == "fallback":
            hours = query_status.get("hours", LOAD_ZONE_FALLBACK_HOURS) if isinstance(query_status, dict) else LOAD_ZONE_FALLBACK_HOURS
            return f"Matched after widening query window to {hours}h."
        return "Matched primary 2h query."
    if raw_rows:
        samples = ", ".join(sampled_settlement_points) or "none"
        return f"No rows matched {settlement_point}; sample settlement points: {samples}."
    return f"No rows returned for {settlement_point}."


def _ercot_environment_status() -> dict[str, Any]:
    price_key_source = _ercot_subscription_key_source(for_price=True)
    token_source = "missing"
    if _env_value(
        "ERCOT_API_ID_TOKEN",
        "ERCOT_ID_TOKEN",
        "ERCOT_API_ACCESS_TOKEN",
        "ERCOT_ACCESS_TOKEN",
        "ERCOT_API_BEARER_TOKEN",
        "ERCOT_BEARER_TOKEN",
        "ERCOT_TOKEN",
    ):
        token_source = "direct_token"
    elif _env_value("ERCOT_API_USERNAME", "ERCOT_USERNAME", "ERCOT_API_EMAIL", "ERCOT_EMAIL") and _env_value(
        "ERCOT_API_PASSWORD",
        "ERCOT_PASSWORD",
    ):
        token_source = "username_password"

    return {
        "subscription_key_present": bool(_env_value(*ERCOT_PRIMARY_SUBSCRIPTION_KEY_NAMES)),
        "secondary_subscription_key_present": bool(_env_value(*ERCOT_PRICE_SUBSCRIPTION_KEY_NAMES)),
        "price_subscription_key_source": price_key_source or "missing",
        "token_source": token_source,
        "username_present": bool(_env_value("ERCOT_API_USERNAME", "ERCOT_USERNAME", "ERCOT_API_EMAIL", "ERCOT_EMAIL")),
        "password_present": bool(_env_value("ERCOT_API_PASSWORD", "ERCOT_PASSWORD")),
        "cached_token_present": bool(_ercot_cached_token),
        "cached_token_kind": _ercot_cached_token_kind,
        "cached_token_expires_at": _ercot_token_expires_at.isoformat() if _ercot_token_expires_at else None,
    }


def _response_message(response: httpx.Response) -> str:
    if 200 <= response.status_code < 300:
        return "ERCOT accepted subscription key and bearer token."
    text = response.text[:500].strip()
    return text or response.reason_phrase


async def _ercot_headers(client: httpx.AsyncClient, *, for_price: bool = False) -> dict[str, str]:
    subscription_key, _ = _ercot_subscription_key(for_price=for_price)

    token = await _ercot_bearer_token(client)
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Ocp-Apim-Subscription-Key": subscription_key,
    }


def _ercot_subscription_key(*, for_price: bool = False) -> tuple[str, str]:
    if for_price:
        secondary_key = _env_value(*ERCOT_PRICE_SUBSCRIPTION_KEY_NAMES)
        if secondary_key:
            return secondary_key, "secondary"

    primary_key = _env_value(*ERCOT_PRIMARY_SUBSCRIPTION_KEY_NAMES)
    if primary_key:
        return primary_key, "primary"

    if for_price:
        raise RuntimeError(
            "ERCOT price API subscription key is not set. Set ERCOT_API_SECONDARY_SUBSCRIPTION_KEY "
            "or ERCOT_API_SUBSCRIPTION_KEY."
        )
    raise RuntimeError("ERCOT_API_SUBSCRIPTION_KEY is not set.")


def _ercot_subscription_key_source(*, for_price: bool = False) -> str | None:
    if for_price and _env_value(*ERCOT_PRICE_SUBSCRIPTION_KEY_NAMES):
        return "secondary"
    if _env_value(*ERCOT_PRIMARY_SUBSCRIPTION_KEY_NAMES):
        return "primary"
    return None


async def _ercot_bearer_token(client: httpx.AsyncClient) -> str:
    direct_token = _env_value(
        "ERCOT_API_ID_TOKEN",
        "ERCOT_ID_TOKEN",
        "ERCOT_API_ACCESS_TOKEN",
        "ERCOT_ACCESS_TOKEN",
        "ERCOT_API_BEARER_TOKEN",
        "ERCOT_BEARER_TOKEN",
        "ERCOT_TOKEN",
    )
    if direct_token:
        return direct_token

    async with _ercot_token_lock:
        now = utc_now()
        if _ercot_cached_token and _ercot_token_expires_at and _ercot_token_expires_at > now + timedelta(minutes=5):
            return _ercot_cached_token

        username = _env_value("ERCOT_API_USERNAME", "ERCOT_USERNAME", "ERCOT_API_EMAIL", "ERCOT_EMAIL")
        password = _env_value("ERCOT_API_PASSWORD", "ERCOT_PASSWORD")
        if not username or not password:
            raise RuntimeError(
                "ERCOT subscription key is present, but Public API also requires a bearer token. "
                "Set ERCOT_API_ID_TOKEN or ERCOT_API_USERNAME/ERCOT_API_PASSWORD."
            )

        response = await client.post(
            ERCOT_AUTH_URL,
            params=_ercot_auth_params(username, password),
            content=b"",
        )
        response.raise_for_status()
        payload = response.json()
        token_kind = "access_token" if payload.get("access_token") else "id_token"
        token = payload.get("access_token") or payload.get("id_token")
        if not token:
            raise RuntimeError("ERCOT authentication response did not include a bearer token.")

        expires_in = int(payload.get("expires_in", 3600))
        globals()["_ercot_cached_token"] = token
        globals()["_ercot_token_expires_at"] = now + timedelta(seconds=max(60, expires_in - 60))
        globals()["_ercot_cached_token_kind"] = token_kind
        return token


def _ercot_auth_params(username: str, password: str) -> dict[str, str]:
    return {
        "username": username,
        "password": password,
        "grant_type": "password",
        "scope": ERCOT_SCOPE,
        "client_id": ERCOT_CLIENT_ID,
        "response_type": "id_token",
    }


async def _get_ercot_report_json(
    client: httpx.AsyncClient,
    name: str,
    endpoint: str,
    *,
    params: dict[str, Any],
    headers: dict[str, str],
    cache_time_window: bool = False,
) -> dict[str, Any]:
    cache_key = _ercot_payload_cache_key(name, params, include_time_window=cache_time_window)
    cached_payload = _cached_ercot_payload(cache_key)
    if cached_payload:
        return cached_payload

    try:
        payload = await _get_json(client, ERCOT_BASE_URL + endpoint, params=params, headers=headers)
    except Exception as exc:
        stale_payload = _cached_ercot_payload(
            cache_key,
            allow_expired=True,
            max_age_seconds=_ercot_payload_stale_seconds(name),
        )
        if stale_payload:
            stale_payload["__local_cache_status"] = _status(
                "ERCOT",
                "stale",
                f"{name}: using cached ERCOT payload after API error: {_short_error(exc)}",
            )
            return stale_payload
        if _is_ercot_rate_limit_error(exc):
            return _ercot_rate_limited_payload(name, exc)
        raise

    _store_ercot_payload(cache_key, payload, ttl_seconds=_ercot_payload_cache_seconds(name))
    return payload


async def _fetch_rt_lmp_payload(client: httpx.AsyncClient, *, headers: dict[str, str]) -> dict[str, Any]:
    settlement_point = ERCOT_PRICE_SETTLEMENT_POINT
    cached_rows = _rt_lmp_rows_cache.get(settlement_point, [])
    if cached_rows and _rt_lmp_cache_is_current_day(cached_rows) and not _rt_lmp_refresh_due(settlement_point):
        return _rt_lmp_payload(cached_rows)

    seed_rows = cached_rows if _rt_lmp_cache_is_current_day(cached_rows) else []
    params = _rt_lmp_query_params(seed_rows)
    try:
        payload = await _get_json(client, ERCOT_BASE_URL + ERCOT_ENDPOINTS["price"], params=params, headers=headers)
    except Exception as exc:
        if seed_rows:
            return _rt_lmp_payload(
                seed_rows,
                cache_status=_status(
                    "ERCOT",
                    "stale",
                    f"price: using cached RT LMP rows after API error: {_short_error(exc)}",
                ),
            )
        if _is_ercot_rate_limit_error(exc):
            return _ercot_rate_limited_payload("price", exc)
        raise

    rows = _report_rows(payload)
    merged_rows = _merge_rt_lmp_rows(seed_rows, rows)
    _rt_lmp_rows_cache[settlement_point] = merged_rows
    _rt_lmp_last_refresh_at[settlement_point] = utc_now()

    payload = dict(payload)
    payload["data"] = _rt_lmp_rows_desc(merged_rows)
    return payload


def _is_ercot_rate_limit_error(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429


def _ercot_rate_limited_payload(name: str, exc: BaseException) -> dict[str, Any]:
    retry_after = ""
    if isinstance(exc, httpx.HTTPStatusError):
        retry_after = str(exc.response.headers.get("Retry-After") or "").strip()
    message = (
        f"{name}: ERCOT Public API rate limit response received; serving server-held data "
        "until the local request budget allows another refresh."
    )
    if retry_after:
        message = f"{message} Retry after {retry_after}s."
    return {
        "data": [],
        "_meta": {"totalRecords": 0, "source": "local-ercot-rate-limit-guard"},
        "__local_cache_status": _status("ERCOT", "stale", message),
    }


def _rt_lmp_query_params(cached_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    now = _ercot_now()
    latest = _latest_price_row(cached_rows)
    latest_timestamp = _price_local_timestamp(latest) if latest else None
    if latest_timestamp:
        start = latest_timestamp + timedelta(seconds=1)
        size = _env_int("ERCOT_RT_LMP_UPDATE_POINTS", 12, minimum=1, maximum=100)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        size = _env_int("ERCOT_RT_LMP_INITIAL_POINTS", 300, minimum=12, maximum=1000)

    return {
        "page": 1,
        "size": size,
        "dir": "ASC",
        "sort": "SCEDTimestamp",
        "SCEDTimestampFrom": _ercot_timestamp(start),
        "SCEDTimestampTo": _ercot_timestamp(now),
        "settlementPoint": ERCOT_PRICE_SETTLEMENT_POINT,
    }


def _rt_lmp_report_params(
    *,
    start_time: str | datetime | None,
    end_time: str | datetime | None,
    settlement_point: str | None,
    size: int,
) -> dict[str, Any]:
    default_start, default_end = _ercot_time_window(hours=12)
    params = {
        "page": 1,
        "size": max(1, min(1000, int(size))),
        "dir": "ASC",
        "sort": "SCEDTimestamp",
        "SCEDTimestampFrom": _ercot_query_timestamp(start_time) if start_time else default_start,
        "SCEDTimestampTo": _ercot_query_timestamp(end_time) if end_time else default_end,
        "settlementPoint": (settlement_point or ERCOT_PRICE_SETTLEMENT_POINT).strip().upper(),
    }
    return params


def _load_zone_lmp_params(settlement_point: str, *, hours: int = 2, size: int = 1) -> dict[str, Any]:
    start, end = _ercot_time_window(hours=hours)
    return {
        "page": 1,
        "size": size,
        "dir": "DESC",
        "sort": "SCEDTimestamp",
        "SCEDTimestampFrom": start,
        "SCEDTimestampTo": end,
        "settlementPoint": settlement_point,
    }


def _ercot_query_timestamp(value: str | datetime) -> str:
    if isinstance(value, datetime):
        return _ercot_timestamp(_to_ercot_local(value))

    text = str(value).strip().replace(" ", "T")
    if not text:
        raise ValueError("ERCOT timestamp query values cannot be empty.")

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text

    if parsed.tzinfo is not None:
        parsed = _to_ercot_local(parsed)
    return _ercot_timestamp(parsed)


def _rt_lmp_refresh_due(settlement_point: str) -> bool:
    last_refresh = _rt_lmp_last_refresh_at.get(settlement_point)
    if not last_refresh:
        return True
    refresh_seconds = _env_int("ERCOT_RT_LMP_REFRESH_SECONDS", 300, minimum=60, maximum=900)
    return last_refresh + timedelta(seconds=refresh_seconds) <= utc_now()


def _rt_lmp_cache_is_current_day(rows: Sequence[dict[str, Any]]) -> bool:
    if not rows:
        return False
    latest = _latest_price_row(rows)
    latest_timestamp = _price_local_timestamp(latest)
    return bool(latest_timestamp and latest_timestamp.date() == _ercot_now().date())


def _merge_rt_lmp_rows(
    cached_rows: Sequence[dict[str, Any]],
    new_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_timestamp = {
        _raw_text(row, *ERCOT_PRICE_TIMESTAMP_KEYS): dict(row)
        for row in cached_rows
        if _raw_text(row, *ERCOT_PRICE_TIMESTAMP_KEYS)
    }
    for row in _price_rows_for_settlement(new_rows, ERCOT_PRICE_SETTLEMENT_POINT):
        timestamp = _raw_text(row, *ERCOT_PRICE_TIMESTAMP_KEYS)
        if timestamp:
            rows_by_timestamp[timestamp] = dict(row)

    rows = sorted(rows_by_timestamp.values(), key=_rt_lmp_row_sort_key)
    return rows[-_env_int("ERCOT_RT_LMP_MAX_POINTS", 288, minimum=12, maximum=1000) :]


def _rt_lmp_payload(
    rows: Sequence[dict[str, Any]],
    *,
    cache_status: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "data": _rt_lmp_rows_desc(rows),
        "_meta": {"totalRecords": len(rows), "source": "local-rt-lmp-cache"},
    }
    if cache_status:
        payload["__local_cache_status"] = cache_status
    return payload


def _rt_lmp_rows_desc(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted([dict(row) for row in rows], key=_rt_lmp_row_sort_key, reverse=True)


def _rt_lmp_row_sort_key(row: dict[str, Any]) -> datetime:
    return _price_local_timestamp(row) or datetime.min


def _price_local_timestamp(row: dict[str, Any]) -> datetime | None:
    return _parse_ercot_local_datetime(_raw_text(row, *ERCOT_PRICE_TIMESTAMP_KEYS))


def _parse_ercot_local_datetime(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(microsecond=0)
    return _to_ercot_local(parsed)


def _to_ercot_local(value: datetime) -> datetime:
    try:
        return value.astimezone(ZoneInfo("America/Chicago")).replace(tzinfo=None, microsecond=0)
    except ZoneInfoNotFoundError:
        return value.astimezone().replace(tzinfo=None, microsecond=0)


async def fetch_ercot_snapshot(client: httpx.AsyncClient) -> dict[str, Any]:
    cached_snapshot = _cached_ercot_snapshot()
    if cached_snapshot:
        return cached_snapshot

    try:
        headers = await _ercot_headers(client)
        price_headers = await _ercot_headers(client, for_price=True)
    except Exception as exc:
        return empty_ercot_snapshot(f"ERCOT credentials or token request failed: {exc}", state="unavailable")

    requests = {
        name: (
            _fetch_rt_lmp_payload(client, headers=price_headers)
            if name == "price"
            else _get_ercot_report_json(
                client,
                name,
                endpoint,
                params=_ercot_params(name),
                headers=price_headers if _is_price_report(name) else headers,
            )
        )
        for name, endpoint in ERCOT_ENDPOINTS.items()
    }
    requests.update(
        {
            f"load_zone_{zone.lower()}": _get_ercot_report_json(
                client,
                f"load-zone-{zone.lower()}",
                endpoint,
                params=_ercot_params("load"),
                headers=headers,
            )
            for zone, endpoint in LOAD_ENDPOINTS.items()
        }
    )
    requests.update(
        {
            f"generation_zone_{zone.lower()}": _get_ercot_report_json(
                client,
                f"generation-zone-{zone.lower()}",
                endpoint,
                params=_ercot_params("generation"),
                headers=headers,
            )
            for zone, endpoint in GENERATION_ENDPOINTS.items()
        }
    )
    responses = await asyncio.gather(*requests.values(), return_exceptions=True)
    ercot_payloads: dict[str, dict[str, Any]] = {}
    failures: dict[str, BaseException] = {}
    for name, response in zip(requests.keys(), responses):
        if isinstance(response, BaseException):
            failures[name] = response
        else:
            ercot_payloads[name] = response

    price_rows = _report_rows(ercot_payloads.get("price", {}))
    day_ahead_price_rows = _report_rows(ercot_payloads.get("day_ahead_price", {}))
    price_status = _market_price_status(ercot_payloads, failures, price_rows, day_ahead_price_rows)

    critical_failures = {name: failures[name] for name in ("load", "generation", "wind", "solar") if name in failures}
    if critical_failures:
        cached_snapshot = _cached_ercot_snapshot(allow_expired=True)
        message = _ercot_failure_message(critical_failures)
        if cached_snapshot:
            if price_rows or day_ahead_price_rows:
                cached_snapshot = _with_market_price_data(
                    cached_snapshot,
                    price_rows,
                    day_ahead_price_rows,
                    price_status,
                )
            elif cached_snapshot.get("price_series"):
                cached_snapshot["price_status"] = _status(
                    "ERCOT RT/DA LMP",
                    "stale",
                    f"Using cached price rows after ERCOT API error: {message}",
                )
            cached_snapshot["status"] = _status("ERCOT", "stale", f"Using cached ERCOT data after API error: {message}")
            return cached_snapshot
        empty = empty_ercot_snapshot(f"ERCOT grid data unavailable after API error: {message}", state="partial" if price_rows or day_ahead_price_rows else "unavailable")
        empty = _with_market_price_data(empty, price_rows, day_ahead_price_rows, price_status)
        empty["status"] = _status(
            "ERCOT",
            "partial" if price_rows or day_ahead_price_rows else "unavailable",
            f"ERCOT grid data unavailable after API error: {message}",
        )
        return empty

    load_rows = _report_rows(ercot_payloads.get("load", {}))
    generation_rows = _report_rows(ercot_payloads.get("generation", {}))
    wind_rows = _report_rows(ercot_payloads.get("wind", {}))
    solar_rows = _report_rows(ercot_payloads.get("solar", {}))
    load_zone_rows = {
        zone: _report_rows(ercot_payloads.get(f"load_zone_{zone.lower()}", {}))
        for zone in LOAD_ZONE_SETTLEMENT_POINTS
    }
    generation_zone_rows = {
        zone: _report_rows(ercot_payloads.get(f"generation_zone_{zone.lower()}", {}))
        for zone in LOAD_ZONE_SETTLEMENT_POINTS
    }
    price_zone_rows = {
        zone: _report_rows(ercot_payloads.get(f"price_zone_{zone.lower()}", {}))
        for zone in LOAD_ZONE_SETTLEMENT_POINTS
    }

    load_row = load_rows[0] if load_rows else {}
    generation_row = generation_rows[0] if generation_rows else {}
    wind_row = wind_rows[0] if wind_rows else {}
    solar_row = solar_rows[0] if solar_rows else {}

    load_mw = _num(load_row, "aggLoadSummary", "load", "demand", default=0)
    generation_mw = _num(generation_row, "sumGenTelemMW", "sumBasePointNonIRR", "sumHASLNonIRR", default=load_mw * 1.05)
    wind_mw = _num(
        wind_row,
        "genSystemWide",
        "systemWide",
        "actualSystemWide",
        "ACTUAL_SYSTEM_WIDE",
        "wind",
        default=0,
    )
    solar_mw = _num(
        solar_row,
        "genSystemWide",
        "systemWide",
        "actualSystemWide",
        "ACTUAL_SYSTEM_WIDE",
        "solar",
        default=0,
    )
    price_proxy = _price_proxy(price_rows, settlement_point=ERCOT_PRICE_SETTLEMENT_POINT)

    if not load_rows or not generation_rows or not wind_rows or not solar_rows or load_mw <= 0 or generation_mw <= 0:
        empty = empty_ercot_snapshot("Live ERCOT response did not include expected grid fields.", state="partial" if price_rows or day_ahead_price_rows else "unavailable")
        empty = _with_market_price_data(empty, price_rows, day_ahead_price_rows, price_status)
        empty["status"] = _status(
            "ERCOT",
            "partial" if price_rows or day_ahead_price_rows else "unavailable",
            "Live ERCOT response did not include expected grid fields.",
        )
        return empty

    cache_messages = [
        str(payload["__local_cache_status"]["message"])
        for payload in ercot_payloads.values()
        if isinstance(payload.get("__local_cache_status"), dict)
    ]
    status_message = "; ".join(message for message in [_ercot_failure_message(failures), *cache_messages] if message)
    load_zones = _load_zone_metrics(
        load_mw,
        generation_mw,
        price_proxy,
        load_zone_rows=load_zone_rows,
        generation_zone_rows=generation_zone_rows,
        price_zone_rows=price_zone_rows,
    )
    snapshot = {
        "load_mw": round(load_mw, 1),
        "generation_mw": round(generation_mw, 1),
        "wind_mw": round(wind_mw, 1),
        "solar_mw": round(solar_mw, 1),
        "price_proxy": round(price_proxy, 2) if price_proxy is not None else None,
        "price_settlement_point": ERCOT_PRICE_SETTLEMENT_POINT,
        "price_label": ERCOT_PRICE_SETTLEMENT_POINT_LABEL,
        "price_series": _market_price_series(price_rows, day_ahead_price_rows),
        "price_status": price_status,
        "reserve_margin_pct": round(((generation_mw - load_mw) / max(load_mw, 1)) * 100, 1),
        "load_zones": load_zones,
        "regions": [dict(zone) for zone in load_zones],
        "trends": _ercot_report_trends(load_rows, generation_rows, wind_rows, solar_rows, price_rows),
        "status": _status("ERCOT", "partial", status_message) if status_message else _status("ERCOT", "live"),
    }
    _store_ercot_snapshot(snapshot)
    return snapshot


async def fetch_supply_demand_dashboard(client: httpx.AsyncClient) -> dict[str, Any]:
    try:
        payload = await _get_json(client, ERCOT_SUPPLY_DEMAND_URL)
    except Exception as exc:
        return empty_supply_demand_snapshot(f"ERCOT Supply/Demand dashboard unavailable: {exc}", state="unavailable")

    snapshot = _normalize_supply_demand_payload(payload)
    if not snapshot["current_day"]:
        return empty_supply_demand_snapshot("Live ERCOT dashboard response did not include current-day rows.", state="unavailable")

    snapshot["status"] = _status("ERCOT Supply/Demand", "live")
    return snapshot


async def fetch_ercot_public_dashboards(client: httpx.AsyncClient) -> dict[str, Any]:
    requests = {
        name: _get_json(client, f"{ERCOT_DASHBOARD_BASE_URL}/{filename}")
        for name, filename in ERCOT_PUBLIC_DASHBOARDS.items()
    }
    responses = await asyncio.gather(*requests.values(), return_exceptions=True)

    snapshot = empty_ercot_public_dashboards()
    failures: list[str] = []
    live_count = 0

    for name, result in zip(requests, responses):
        if isinstance(result, Exception):
            failures.append(f"{name}: {type(result).__name__}")
            continue
        try:
            snapshot[name] = _normalize_ercot_public_dashboard(name, result)
            live_count += 1
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}")

    if live_count == len(requests):
        snapshot["status"] = _status("ERCOT Dashboards", "live")
    elif live_count:
        snapshot["status"] = _status(
            "ERCOT Dashboards",
            "partial",
            f"{live_count}/{len(requests)} public dashboard feeds normalized. "
            + "; ".join(failures),
        )
    else:
        snapshot["status"] = _status(
            "ERCOT Dashboards",
            "unavailable",
            "ERCOT public dashboard feeds unavailable. " + "; ".join(failures),
        )

    snapshot["timestamp"] = utc_now().isoformat()
    return snapshot


async def fetch_ercot_public_dashboard_feed(client: httpx.AsyncClient, feed_name: str) -> dict[str, Any]:
    normalized_name = _normalize_feed_name(feed_name)
    if normalized_name not in ERCOT_PUBLIC_DASHBOARDS:
        valid = ", ".join(name.replace("_", "-") for name in ERCOT_PUBLIC_DASHBOARDS)
        raise ValueError(f"Unknown ERCOT public dashboard feed '{feed_name}'. Valid feeds: {valid}.")

    title = str(ERCOT_PUBLIC_DASHBOARD_FEEDS[normalized_name]["title"])
    source_url = f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS[normalized_name]}"
    try:
        payload = await _get_json(client, source_url)
        data = _normalize_ercot_public_dashboard(normalized_name, payload)
    except Exception as exc:
        data = empty_ercot_public_dashboards(
            f"ERCOT public dashboard feed '{normalized_name}' unavailable: {exc}",
            state="unavailable",
        )[normalized_name]
        return _feed_snapshot(
            f"ercot-{normalized_name}",
            provider="ERCOT",
            title=title,
            source_url=source_url,
            status=_status("ERCOT Dashboards", "unavailable", f"{type(exc).__name__}: {exc}"),
            data=data,
        )

    return _feed_snapshot(
        f"ercot-{normalized_name}",
        provider="ERCOT",
        title=title,
        source_url=source_url,
        status=_status("ERCOT Dashboards", "live"),
        data=data,
    )


def _normalize_feed_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _feed_snapshot(
    name: str,
    *,
    provider: str,
    title: str,
    source_url: str,
    status: dict[str, str],
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "timestamp": utc_now().isoformat(),
        "name": name,
        "provider": provider,
        "title": title,
        "source_url": source_url,
        "status": status,
        "data": data,
    }


def _normalize_ercot_public_dashboard(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if name == "prc":
        return _normalize_prc_dashboard(payload)
    if name == "fuel_mix":
        return _normalize_ercot_fuel_mix_dashboard(payload)
    if name == "storage":
        return _normalize_storage_dashboard(payload)
    if name == "combined_renewables":
        return _normalize_combined_renewables_dashboard(payload)
    if name == "dc_ties":
        return _normalize_dc_tie_flows_dashboard(payload)
    if name == "outages":
        return _normalize_generation_outages_dashboard(payload)
    if name == "ancillary":
        return _normalize_ancillary_dashboard(payload)
    raise ValueError(f"Unknown ERCOT public dashboard '{name}'.")


def _normalize_prc_dashboard(payload: dict[str, Any]) -> dict[str, Any]:
    points = [
        {
            "timestamp": _ercot_dashboard_timestamp(row.get("timestamp")),
            "epoch": _maybe_int(row.get("epoch")),
            "prc_mw": round(_to_float(row.get("prc")), 1),
        }
        for row in _coerce_rows(payload.get("data", []))
        if _maybe_num(row, "prc") is not None
    ]
    points.sort(key=_time_point_sort_key)
    points = _limit_points(points, 420)

    condition = payload.get("current_condition", {})
    if not isinstance(condition, dict):
        condition = {}
    latest_prc = _to_float(condition.get("prc_value"), default=points[-1]["prc_mw"] if points else 0)
    energy_level = _to_float(condition.get("energy_level_value"), default=0)

    return {
        "last_updated": _ercot_dashboard_timestamp(payload.get("lastUpdated")),
        "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['prc']}",
        "condition": {
            "title": str(condition.get("title") or "Normal Conditions"),
            "note": str(condition.get("condition_note") or ""),
            "eea_level": _maybe_int(condition.get("eea_level")) or 0,
            "state": str(condition.get("state") or "normal"),
            "energy_level_value": round(energy_level, 1),
        },
        "latest_prc_mw": round(latest_prc, 1),
        "series": points,
    }


def _normalize_ercot_fuel_mix_dashboard(payload: dict[str, Any]) -> dict[str, Any]:
    raw_data = payload.get("data", {})
    fuel_types = [str(fuel) for fuel in payload.get("types", []) if fuel]
    monthly_capacity = payload.get("monthlyCapacity") if isinstance(payload.get("monthlyCapacity"), dict) else {}
    series = []
    if isinstance(raw_data, dict):
        for day_data in raw_data.values():
            if not isinstance(day_data, dict):
                continue
            for timestamp, fuels in day_data.items():
                if not isinstance(fuels, dict):
                    continue
                fuel_values = {
                    str(fuel): round(_fuel_mix_metric(values, "gen") or 0, 2)
                    for fuel, values in fuels.items()
                }
                fuel_details = {
                    str(fuel): _fuel_mix_detail(str(fuel), values, monthly_capacity)
                    for fuel, values in fuels.items()
                }
                total = sum(fuel_values.values())
                series.append(
                    {
                        "timestamp": _ercot_dashboard_timestamp(timestamp),
                        "total_mw": round(total, 2),
                        "fuels": fuel_values,
                        "fuel_details": fuel_details,
                    }
                )

    series.sort(key=lambda point: str(point.get("timestamp", "")))
    series = _limit_points(series, 288)
    latest = series[-1] if series else {"fuels": {}, "total_mw": 0, "timestamp": ""}
    latest_total = float(latest.get("total_mw") or 0)
    latest_mix = [
        _latest_fuel_mix_item(fuel, value, latest_total, latest.get("fuel_details", {}), monthly_capacity)
        for fuel, value in sorted(latest.get("fuels", {}).items(), key=lambda item: item[1], reverse=True)
    ]

    return {
        "last_updated": _ercot_dashboard_timestamp(payload.get("lastUpdated")),
        "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['fuel_mix']}",
        "fuel_types": fuel_types or [item["fuel"] for item in latest_mix],
        "series": series,
        "latest": {
            "timestamp": latest.get("timestamp", ""),
            "total_mw": round(latest_total, 1),
            "mix": latest_mix,
        },
    }


def _fuel_mix_metric(values: Any, *keys: str) -> float | None:
    if isinstance(values, dict):
        lowered = {str(key).lower(): value for key, value in values.items()}
        for key in keys:
            if key.lower() in lowered:
                return _to_float(lowered[key.lower()])
        return None
    return _to_float(values) if "gen" in {key.lower() for key in keys} else None


def _fuel_mix_detail(fuel: str, values: Any, monthly_capacity: dict[str, Any]) -> dict[str, float | None]:
    generation = _fuel_mix_metric(values, "gen")
    hsl = _fuel_mix_metric(values, "hsl")
    seasonal_capacity = _fuel_mix_metric(values, "seasonalCapacity", "seasonal_capacity", "capacity")
    if seasonal_capacity is None:
        seasonal_capacity = _fuel_mix_metric(monthly_capacity.get(fuel), "gen")

    return {
        "generation_mw": round(generation, 2) if generation is not None else None,
        "hsl_mw": round(hsl, 2) if hsl is not None else None,
        "capacity_mw": round(seasonal_capacity, 2) if seasonal_capacity is not None else None,
    }


def _latest_fuel_mix_item(
    fuel: str,
    generation_mw: float,
    latest_total_mw: float,
    details: Any,
    monthly_capacity: dict[str, Any],
) -> dict[str, Any]:
    detail = details.get(fuel, {}) if isinstance(details, dict) else {}
    hsl_mw = detail.get("hsl_mw") if isinstance(detail, dict) else None
    capacity_mw = detail.get("capacity_mw") if isinstance(detail, dict) else None
    if capacity_mw is None:
        capacity_mw = _fuel_mix_metric(monthly_capacity.get(fuel), "gen")

    unavailable_mw = None
    if isinstance(capacity_mw, int | float) and isinstance(hsl_mw, int | float):
        unavailable_mw = round(max(float(capacity_mw) - float(hsl_mw), 0), 1)

    headroom_mw = None
    if isinstance(hsl_mw, int | float):
        headroom_mw = round(max(float(hsl_mw) - float(generation_mw), 0), 1)

    availability_pct = None
    if isinstance(capacity_mw, int | float) and float(capacity_mw) > 0 and isinstance(hsl_mw, int | float):
        availability_pct = round((float(hsl_mw) / float(capacity_mw)) * 100, 1)

    utilization_pct = None
    if isinstance(hsl_mw, int | float) and float(hsl_mw) > 0:
        utilization_pct = round((float(generation_mw) / float(hsl_mw)) * 100, 1)

    return {
        "fuel": fuel,
        "generation_mw": round(generation_mw, 1),
        "share_pct": round((generation_mw / latest_total_mw) * 100, 1) if latest_total_mw else 0,
        "hsl_mw": round(float(hsl_mw), 1) if isinstance(hsl_mw, int | float) else None,
        "capacity_mw": round(float(capacity_mw), 1) if isinstance(capacity_mw, int | float) else 0,
        "unavailable_mw": unavailable_mw,
        "headroom_mw": headroom_mw,
        "availability_pct": availability_pct,
        "utilization_pct": utilization_pct,
    }


def _normalize_storage_dashboard(payload: dict[str, Any]) -> dict[str, Any]:
    current_day = _normalize_storage_day(payload.get("currentDay", {}))
    previous_day = _normalize_storage_day(payload.get("previousDay", {}))
    latest = current_day[-1] if current_day else {}

    return {
        "last_updated": _ercot_dashboard_timestamp(payload.get("lastUpdated")),
        "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['storage']}",
        "current_day": current_day,
        "previous_day": previous_day,
        "latest": latest,
        "summary": {
            "max_charging_mw": round(max((point["charging_mw"] for point in current_day), default=0), 1),
            "max_discharging_mw": round(max((point["discharging_mw"] for point in current_day), default=0), 1),
            "latest_net_mw": round(float(latest.get("net_mw") or 0), 1),
        },
    }


def _normalize_storage_day(day_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(day_payload, dict):
        return []
    points = []
    for row in _coerce_rows(day_payload.get("data", [])):
        charging_raw = _to_float(row.get("totalCharging"))
        discharging = _to_float(row.get("totalDischarging"))
        points.append(
            {
                "timestamp": _ercot_dashboard_timestamp(row.get("tagCLastTime")),
                "charging_mw": round(abs(charging_raw), 1),
                "discharging_mw": round(discharging, 1),
                "net_mw": round(discharging + charging_raw, 1),
            }
        )
    points.sort(key=lambda point: str(point.get("timestamp", "")))
    return _limit_points(points, 288)


def _normalize_combined_renewables_dashboard(payload: dict[str, Any]) -> dict[str, Any]:
    current_day_payload = payload.get("currentDay", {})
    raw_data = current_day_payload.get("data", {}) if isinstance(current_day_payload, dict) else {}
    rows = [row for row in raw_data.values() if isinstance(row, dict)] if isinstance(raw_data, dict) else _coerce_rows(raw_data)

    points = []
    for row in rows:
        timestamp = _ercot_dashboard_timestamp(row.get("timestamp"))
        if not timestamp:
            continue

        actual_wind = _maybe_num(row, "actualWind")
        actual_solar = _maybe_num(row, "actualSolar")
        forecast_wind = _maybe_num(row, "stwpf", "wgrpp", "copHslWind", "stwpfDayAhead", "wgrppDayAhead")
        forecast_solar = _maybe_num(row, "stppf", "pvgrpp", "copHslSolar", "stppfDayAhead", "pvgrppDayAhead")
        has_actual = actual_wind is not None or actual_solar is not None
        has_forecast = forecast_wind is not None or forecast_solar is not None
        if not has_actual and not has_forecast:
            continue

        point = {
            "timestamp": timestamp,
            "epoch": _maybe_int(row.get("epoch")),
            "hour_ending": _maybe_int(row.get("hourEnding")),
            "dst_flag": str(row.get("dstFlag") or ""),
            "wind_actual_mw": _round_or_none(actual_wind),
            "solar_actual_mw": _round_or_none(actual_solar),
            "combined_actual_mw": round(float(actual_wind or 0) + float(actual_solar or 0), 1) if has_actual else None,
            "wind_forecast_mw": _round_or_none(forecast_wind),
            "solar_forecast_mw": _round_or_none(forecast_solar),
            "combined_forecast_mw": round(float(forecast_wind or 0) + float(forecast_solar or 0), 1)
            if has_forecast
            else None,
        }
        points.append(point)

    points.sort(key=_time_point_sort_key)
    points = _combined_current_day_points(points)
    actual_points = [point for point in points if point.get("combined_actual_mw") is not None]
    forecast_points = [
        point
        for point in points
        if point.get("combined_actual_mw") is None and point.get("combined_forecast_mw") is not None
    ]

    return {
        "last_updated": _ercot_dashboard_timestamp(payload.get("lastUpdated")),
        "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['combined_renewables']}",
        "current_day": points,
        "latest_actual": actual_points[-1] if actual_points else {},
        "summary": {
            "actual_points": len(actual_points),
            "forecast_points": len(forecast_points),
            "peak_actual_mw": round(max((float(point["combined_actual_mw"]) for point in actual_points), default=0), 1),
            "peak_forecast_mw": round(
                max((float(point["combined_forecast_mw"]) for point in points if point.get("combined_forecast_mw") is not None), default=0),
                1,
            ),
        },
        "forecast_fields": {"wind": "stwpf", "solar": "stppf"},
    }


def _combined_current_day_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed_points = [(point, _parse_dashboard_datetime(point.get("timestamp"))) for point in points]
    parsed_times = [parsed for _point, parsed in parsed_points if parsed is not None]
    if not parsed_times:
        return points

    operating_day = min(parsed_times).date()
    reset_at = datetime.combine(operating_day + timedelta(days=1), datetime.min.time(), tzinfo=parsed_times[0].tzinfo)
    return [
        point
        for point, parsed in parsed_points
        if parsed is not None and (parsed.date() == operating_day or parsed == reset_at)
    ]


def _parse_dashboard_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_dc_tie_flows_dashboard(payload: dict[str, Any]) -> dict[str, Any]:
    rows = [
        _dc_tie_flow_point(row)
        for row in _coerce_rows(payload.get("data", []))
        if isinstance(row, dict)
    ]
    points = [point for point in rows if point is not None]
    points.sort(key=_time_point_sort_key)
    points = _dc_tie_current_day_points(points)
    series = {
        "North": _dc_tie_series(points, "north_mw"),
        "East": _dc_tie_series(points, "east_mw"),
        "Laredo": _dc_tie_series(points, "laredo_mw"),
        "Railroad": _dc_tie_series(points, "railroad_mw"),
    }
    latest = points[-1] if points else {}
    return {
        "last_updated": _ercot_dashboard_timestamp(payload.get("lastUpdated")),
        "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['dc_ties']}",
        "current_day": points,
        "series": series,
        "latest": latest,
        "summary": {
            "points": len(points),
            "max_import_mw": round(max((float(point.get("total_import_mw") or 0) for point in points), default=0), 1),
            "max_export_mw": round(min((float(point.get("total_export_mw") or 0) for point in points), default=0), 1),
        },
    }


def _dc_tie_flow_point(row: dict[str, Any]) -> dict[str, Any] | None:
    timestamp = _ercot_dashboard_timestamp(row.get("timestamp"))
    if not timestamp:
        return None

    values = {
        "north_mw": _maybe_num(row, "dcN"),
        "east_mw": _maybe_num(row, "dcE"),
        "laredo_mw": _maybe_num(row, "dcL"),
        "railroad_mw": _maybe_num(row, "dcR"),
    }
    if all(value is None for value in values.values()):
        return None

    usable = [float(value) for value in values.values() if value is not None]
    imports = sum(value for value in usable if value > 0)
    exports = sum(value for value in usable if value < 0)
    return {
        "timestamp": timestamp,
        "epoch": _maybe_int(row.get("epoch")),
        "interval": str(row.get("interval") or ""),
        "dst_flag": str(row.get("dstFlag") or ""),
        "frequency_hz": _round_or_none(_maybe_num(row, "currentFrequency"), ndigits=3),
        "system_inertia": _round_or_none(_maybe_num(row, "currentSystemInertia"), ndigits=0),
        **{key: _round_or_none(value) for key, value in values.items()},
        "total_import_mw": round(imports, 1),
        "total_export_mw": round(exports, 1),
        "net_mw": round(sum(usable), 1),
    }


def _dc_tie_current_day_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed_points = [(point, _parse_dashboard_datetime(point.get("timestamp"))) for point in points]
    parsed_times = [parsed for _point, parsed in parsed_points if parsed is not None]
    if not parsed_times:
        return points

    operating_day = min(parsed_times).date()
    return [
        point
        for point, parsed in parsed_points
        if parsed is not None and parsed.date() == operating_day
    ]


def _dc_tie_series(points: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [
        {"timestamp": point.get("timestamp", ""), "value": round(float(point[key]), 1)}
        for point in points
        if isinstance(point.get(key), int | float)
    ]


def _normalize_generation_outages_dashboard(payload: dict[str, Any]) -> dict[str, Any]:
    current = _normalize_outage_series(payload.get("current", {}))
    previous = _normalize_outage_series(payload.get("previous", {}))
    latest = current[-1] if current else {}

    return {
        "last_updated": _ercot_dashboard_timestamp(payload.get("lastUpdated")),
        "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['outages']}",
        "current_outages_mw": round(_to_float(payload.get("currentOutages"), default=latest.get("total_mw", 0)), 1),
        "types": [str(value) for value in payload.get("types", [])],
        "current": current,
        "previous": previous,
        "latest": latest,
    }


def _normalize_outage_series(raw_series: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_series, dict):
        return []
    points = []
    for epoch, row in raw_series.items():
        if not isinstance(row, dict):
            continue
        combined = row.get("Combined") if isinstance(row.get("Combined"), dict) else {}
        dispatchable = row.get("Dispatchable") if isinstance(row.get("Dispatchable"), dict) else {}
        renewable = row.get("Renewable") if isinstance(row.get("Renewable"), dict) else {}
        points.append(
            {
                "timestamp": _ercot_dashboard_timestamp(row.get("deliveryTime")),
                "epoch": _maybe_int(epoch),
                "planned_mw": round(_to_float(combined.get("planned")), 1),
                "unplanned_mw": round(_to_float(combined.get("unplanned")), 1),
                "total_mw": round(_to_float(combined.get("total")), 1),
                "dispatchable_mw": round(_to_float(dispatchable.get("total")), 1),
                "renewable_mw": round(_to_float(renewable.get("total")), 1),
            }
        )
    points.sort(key=_time_point_sort_key)
    return _limit_points(points, 288)


def _normalize_ancillary_dashboard(payload: dict[str, Any]) -> dict[str, Any]:
    raw_groups = payload.get("data", {})
    groups = {
        group_name: _ancillary_group_values(rows)
        for group_name, rows in (raw_groups.items() if isinstance(raw_groups, dict) else [])
    }

    products = [
        {
            "name": "Responsive Reserve",
            "capability_mw": _positive_sum(groups.get("responsiveReserveCapabilityGroup", {})),
            "awards_mw": _positive_sum(groups.get("responsiveReserveAwardsGroup", {})),
        },
        {
            "name": "ECRS",
            "capability_mw": _positive_sum(groups.get("ercotContingencyReserveCapabilityGroup", {})),
            "awards_mw": _positive_sum(groups.get("ercotContingencyReserveAwardsGroup", {})),
        },
        {
            "name": "Non-Spin",
            "capability_mw": _positive_sum(groups.get("nonSpinReserveCapabilityGroup", {})),
            "awards_mw": _positive_sum(groups.get("nonSpinReserveAwardsGroup", {})),
        },
        {
            "name": "Reg Up",
            "capability_mw": _to_float(groups.get("regulationCapacityGroup", {}).get("regUpCap")),
            "awards_mw": _to_float(groups.get("regulationAwardsGroup", {}).get("regUpAwd")),
        },
        {
            "name": "Reg Down",
            "capability_mw": _to_float(groups.get("regulationCapacityGroup", {}).get("regDownCap")),
            "awards_mw": _to_float(groups.get("regulationAwardsGroup", {}).get("regDownAwd")),
        },
    ]

    return {
        "last_updated": _ercot_dashboard_timestamp(payload.get("lastUpdated")),
        "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['ancillary']}",
        "interval": str(payload.get("interval") or ""),
        "products": [
            {key: round(value, 1) if isinstance(value, float) else value for key, value in product.items()}
            for product in products
        ],
        "system": {
            "prc_mw": round(_to_float(groups.get("ercotWidePhysicalResponsiveCapabilityGroup", {}).get("prc")), 1),
            "online_reserve_mw": round(
                _to_float(groups.get("realTimeOperatingReserveDemandCurveCapacityGroup", {}).get("rtReserveOnline")),
                1,
            ),
            "online_offline_reserve_mw": round(
                _to_float(groups.get("realTimeOperatingReserveDemandCurveCapacityGroup", {}).get("rtReserveOnOffline")),
                1,
            ),
        },
        "groups": groups,
    }


def _ancillary_group_values(rows: Any) -> dict[str, float]:
    values = {}
    if not isinstance(rows, list):
        return values
    for row in rows:
        if not isinstance(row, list | tuple) or len(row) < 2 or row[0] == "key":
            continue
        values[str(row[0])] = round(_to_float(row[1]), 1)
    return values


def _positive_sum(values: dict[str, float]) -> float:
    return round(sum(value for value in values.values() if value > 0), 1)


def _normalize_supply_demand_payload(payload: dict[str, Any]) -> dict[str, Any]:
    current_day = [
        point
        for row in _coerce_rows(payload.get("data", []))
        if (point := _supply_demand_current_row(row)) is not None
    ]
    current_day.sort(key=_supply_demand_sort_key)

    six_day = [
        point
        for row in _coerce_rows(payload.get("forecast", []))
        if (point := _supply_demand_forecast_row(row)) is not None
    ]
    six_day.sort(key=_supply_demand_sort_key)

    return {
        "timestamp": utc_now().isoformat(),
        "last_updated": _ercot_dashboard_timestamp(payload.get("lastUpdated")),
        "source_url": ERCOT_SUPPLY_DEMAND_URL,
        "current_day": current_day,
        "six_day": six_day,
        "latest": _latest_supply_demand_point(current_day),
        "summary": _supply_demand_summary(current_day),
        "status": _status("ERCOT Supply/Demand", "demo"),
    }


def _supply_demand_current_row(row: dict[str, Any]) -> dict[str, Any] | None:
    demand = _maybe_num(row, "demand", "forecastedDemand")
    capacity = _maybe_num(row, "capacity", "committedCapacity")
    if demand is None or capacity is None:
        return None

    available = _maybe_num(row, "available", "availableCapacity", "availCapGen")
    timestamp = _ercot_dashboard_timestamp(row.get("timestamp"))
    return {
        "timestamp": timestamp,
        "epoch": _maybe_int(row.get("epoch")),
        "demand_mw": round(demand, 1),
        "committed_capacity_mw": round(capacity, 1),
        "available_capacity_mw": _round_or_none(available),
        "is_forecast": _truthy(row.get("forecast")),
        "hour_ending": _maybe_int(row.get("hourEnding")),
        "interval": _maybe_int(row.get("interval")),
    }


def _supply_demand_forecast_row(row: dict[str, Any]) -> dict[str, Any] | None:
    demand = _maybe_num(row, "forecastedDemand", "demand")
    available = _maybe_num(row, "availCapGen", "available", "availableCapacity")
    if demand is None or available is None:
        return None

    return {
        "timestamp": _ercot_dashboard_timestamp(row.get("timestamp")),
        "epoch": _maybe_int(row.get("epoch")),
        "demand_mw": round(demand, 1),
        "available_capacity_mw": round(available, 1),
        "delivery_date": str(row.get("deliveryDate", "")),
        "hour_ending": _maybe_int(row.get("hourEnding")),
        "is_forecast": True,
    }


def _latest_supply_demand_point(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    actual = [point for point in points if not point.get("is_forecast")]
    source = actual or list(points)
    if not source:
        return {}
    return dict(source[-1])


def _supply_demand_summary(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not points:
        return {
            "actual_points": 0,
            "forecast_points": 0,
            "peak_demand_mw": 0,
            "minimum_margin_mw": 0,
            "minimum_margin_pct": 0,
        }

    peak = max(points, key=lambda point: float(point.get("demand_mw") or 0))
    margins = []
    for point in points:
        demand = float(point.get("demand_mw") or 0)
        capacity = float(point.get("available_capacity_mw") or point.get("committed_capacity_mw") or 0)
        if demand and capacity:
            margins.append((capacity - demand, ((capacity - demand) / demand) * 100))

    min_margin, min_margin_pct = min(margins, key=lambda margin: margin[0]) if margins else (0, 0)
    return {
        "actual_points": len([point for point in points if not point.get("is_forecast")]),
        "forecast_points": len([point for point in points if point.get("is_forecast")]),
        "peak_demand_mw": round(float(peak.get("demand_mw") or 0), 1),
        "peak_demand_timestamp": peak.get("timestamp", ""),
        "minimum_margin_mw": round(min_margin, 1),
        "minimum_margin_pct": round(min_margin_pct, 1),
    }


def _supply_demand_sort_key(point: dict[str, Any]) -> tuple[int, str]:
    epoch = point.get("epoch")
    return (int(epoch) if isinstance(epoch, int) else 0, str(point.get("timestamp", "")))


def _ercot_dashboard_timestamp(value: Any) -> str:
    if not value:
        return ""
    text = str(value).strip()
    for pattern in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(text, pattern).isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace(" ", "T")).isoformat()
    except ValueError:
        return text


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _maybe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any, default: float = 0) -> float:
    if value is None:
        return default
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _time_point_sort_key(point: dict[str, Any]) -> tuple[int, str]:
    epoch = point.get("epoch")
    return (int(epoch) if isinstance(epoch, int) else 0, str(point.get("timestamp", "")))


def _limit_points(points: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    if len(points) <= max_points:
        return points

    step = max(1, math.ceil(len(points) / max_points))
    limited = points[::step]
    if limited[-1] != points[-1]:
        limited.append(points[-1])
    return limited[-max_points:]


def _cached_ercot_snapshot(*, allow_expired: bool = False) -> dict[str, Any] | None:
    if not _ercot_snapshot_cache:
        return None
    if not allow_expired and _ercot_snapshot_expires_at and _ercot_snapshot_expires_at <= utc_now():
        return None
    return deepcopy(_ercot_snapshot_cache)


def _store_ercot_snapshot(snapshot: dict[str, Any]) -> None:
    cache_seconds = _env_int("ERCOT_CACHE_SECONDS", 60, minimum=10, maximum=300)
    globals()["_ercot_snapshot_cache"] = deepcopy(snapshot)
    globals()["_ercot_snapshot_expires_at"] = utc_now() + timedelta(seconds=cache_seconds)


def _cached_ercot_payload(
    cache_key: str,
    *,
    allow_expired: bool = False,
    max_age_seconds: int | None = None,
) -> dict[str, Any] | None:
    payload = _ercot_payload_cache.get(cache_key)
    if not payload:
        return None

    now = utc_now()
    expires_at = _ercot_payload_cache_expires_at.get(cache_key)
    if not allow_expired and expires_at and expires_at <= now:
        return None

    stored_at = _ercot_payload_cache_stored_at.get(cache_key)
    if max_age_seconds is not None and stored_at and stored_at + timedelta(seconds=max_age_seconds) <= now:
        return None

    return deepcopy(payload)


def _store_ercot_payload(cache_key: str, payload: dict[str, Any], *, ttl_seconds: int) -> None:
    now = utc_now()
    _ercot_payload_cache[cache_key] = deepcopy(payload)
    _ercot_payload_cache_stored_at[cache_key] = now
    _ercot_payload_cache_expires_at[cache_key] = now + timedelta(seconds=ttl_seconds)


def _ercot_payload_cache_key(
    name: str,
    params: dict[str, Any],
    *,
    include_time_window: bool = False,
) -> str:
    stable_params = {
        "size": params.get("size"),
        "settlementPoint": params.get("settlementPoint"),
        "deliveryDateFrom": params.get("deliveryDateFrom"),
        "deliveryDateTo": params.get("deliveryDateTo"),
    }
    if include_time_window:
        stable_params.update(
            {
                "SCEDTimestampFrom": params.get("SCEDTimestampFrom"),
                "SCEDTimestampTo": params.get("SCEDTimestampTo"),
                "intervalEndingFrom": params.get("intervalEndingFrom"),
                "intervalEndingTo": params.get("intervalEndingTo"),
            }
        )
    return f"{name}:{tuple(sorted((key, str(value)) for key, value in stable_params.items() if value is not None))}"


def _ercot_payload_cache_seconds(name: str) -> int:
    if _is_price_report(name):
        return _env_int("ERCOT_PRICE_CACHE_SECONDS", 180, minimum=30, maximum=1800)
    return _env_int("ERCOT_REPORT_CACHE_SECONDS", 60, minimum=10, maximum=900)


def _ercot_payload_stale_seconds(name: str) -> int:
    if _is_price_report(name):
        return _env_int("ERCOT_PRICE_STALE_SECONDS", 1800, minimum=60, maximum=7200)
    return _env_int("ERCOT_REPORT_STALE_SECONDS", 600, minimum=60, maximum=3600)


def _is_price_report(name: str) -> bool:
    return (
        name in {"price", "day_ahead_price", "hb-north-lmp", "hb-north-da-lmp"}
        or "lmp" in name
        or name.startswith("price")
    )


def _regional_estimates(load_mw: float, generation_mw: float) -> list[dict[str, Any]]:
    return _load_zone_metrics(load_mw, generation_mw, None)


def _load_zone_metrics(
    load_mw: float,
    generation_mw: float,
    price_proxy: float | None,
    *,
    load_zone_rows: dict[str, list[dict[str, Any]]] | None = None,
    generation_zone_rows: dict[str, list[dict[str, Any]]] | None = None,
    price_zone_rows: dict[str, list[dict[str, Any]]] | None = None,
    estimate_zone_prices: bool = False,
) -> list[dict[str, Any]]:
    weights = {"Houston": 0.28, "North": 0.34, "South": 0.2, "West": 0.18}
    raw_loads = {
        zone: _num((load_zone_rows or {}).get(zone, [{}])[0] if (load_zone_rows or {}).get(zone) else {}, "aggLoadSummary", "load", "demand")
        for zone in weights
    }
    raw_generation = {
        zone: _num(
            (generation_zone_rows or {}).get(zone, [{}])[0] if (generation_zone_rows or {}).get(zone) else {},
            "sumGenTelemMW",
            "sumBasePointNonIRR",
            "sumHASLNonIRR",
        )
        for zone in weights
    }
    zone_loads = _fill_zone_values(load_mw, raw_loads, weights)
    zone_generation = _fill_zone_values(generation_mw, raw_generation, weights)

    zones = []
    for index, name in enumerate(weights):
        point = REGION_POINTS[name]
        zone_load = zone_loads[name]
        zone_gen = zone_generation[name]
        zone_price = _zone_price(
            name,
            price_proxy,
            price_zone_rows or {},
            index=index,
            estimate_missing=estimate_zone_prices,
        )
        stress = min(100, max(5, (zone_load / max(zone_gen, 1)) * 78))
        zones.append(
            {
                "name": name,
                "settlement_point": LOAD_ZONE_SETTLEMENT_POINTS[name],
                "lat": point["lat"],
                "lon": point["lon"],
                "load_mw": round(zone_load, 1),
                "generation_mw": round(zone_gen, 1),
                "price_usd_mwh": round(zone_price, 2) if zone_price is not None else None,
                "stress": round(stress, 1),
            }
        )
    return zones


def _fill_zone_values(total: float, raw_values: dict[str, float], weights: dict[str, float]) -> dict[str, float]:
    usable = {zone: value for zone, value in raw_values.items() if value > 0}
    if len(usable) == len(weights):
        raw_total = sum(usable.values())
        scale = total / raw_total if total > 0 and raw_total > 0 else 1
        return {zone: value * scale for zone, value in usable.items()}

    if usable:
        missing = [zone for zone in weights if zone not in usable]
        remaining = max(total - sum(usable.values()), 0)
        missing_weight = sum(weights[zone] for zone in missing) or 1
        return {
            zone: usable.get(zone, remaining * (weights[zone] / missing_weight))
            for zone in weights
        }

    return {zone: total * weight for zone, weight in weights.items()}


def _zone_price(
    zone: str,
    system_price: float | None,
    price_zone_rows: dict[str, list[dict[str, Any]]],
    *,
    index: int,
    estimate_missing: bool = False,
) -> float | None:
    settlement_point = LOAD_ZONE_SETTLEMENT_POINTS[zone]
    price = _price_proxy(price_zone_rows.get(zone, []), settlement_point=settlement_point)
    if price is not None:
        return price
    if system_price is None or not estimate_missing:
        return None

    zone_spreads = {"Houston": 1.08, "North": 1.0, "South": 0.96, "West": 0.92}
    hour_signal = 1 + 0.035 * math.sin(index + utc_now().hour)
    return max(0, float(system_price) * zone_spreads[zone] * hour_signal)


def _ercot_report_trends(
    load_rows: Sequence[dict[str, Any]],
    generation_rows: Sequence[dict[str, Any]],
    wind_rows: Sequence[dict[str, Any]],
    solar_rows: Sequence[dict[str, Any]],
    price_rows: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    price_source_rows = _price_rows_for_settlement(price_rows, ERCOT_PRICE_SETTLEMENT_POINT)
    return {
        "load_mw": _row_series(load_rows, ("aggLoadSummary", "load", "demand"), ("SCEDTimestamp", "timestamp")),
        "generation_mw": _row_series(
            generation_rows,
            ("sumGenTelemMW", "sumBasePointNonIRR", "sumHASLNonIRR"),
            ("SCEDTimestamp", "timestamp"),
        ),
        "wind_mw": _row_series(
            wind_rows,
            ("genSystemWide", "systemWide", "actualSystemWide", "ACTUAL_SYSTEM_WIDE", "wind"),
            ("intervalEnding", "timestamp"),
        ),
        "solar_mw": _row_series(
            solar_rows,
            ("genSystemWide", "systemWide", "actualSystemWide", "ACTUAL_SYSTEM_WIDE", "solar"),
            ("intervalEnding", "timestamp"),
        ),
        "price_proxy": _row_series(price_source_rows, ERCOT_PRICE_VALUE_KEYS, ERCOT_PRICE_TIMESTAMP_KEYS, limit=96),
    }


def _market_price_series(
    rt_price_rows: Sequence[dict[str, Any]],
    day_ahead_price_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    settlement_point = ERCOT_PRICE_SETTLEMENT_POINT
    rt_rows = _price_rows_for_settlement(rt_price_rows, settlement_point)
    return {
        "settlement_point": settlement_point,
        "label": "North Hub",
        "rt_lmp": _row_series(
            rt_rows,
            ERCOT_PRICE_VALUE_KEYS,
            ERCOT_PRICE_TIMESTAMP_KEYS,
            limit=_env_int("ERCOT_RT_LMP_MAX_POINTS", 288, minimum=12, maximum=1000),
        ),
        "da_lmp": _day_ahead_price_series(day_ahead_price_rows, settlement_point),
    }


def _with_market_price_data(
    snapshot: dict[str, Any],
    rt_price_rows: Sequence[dict[str, Any]],
    day_ahead_price_rows: Sequence[dict[str, Any]],
    price_status: dict[str, str],
) -> dict[str, Any]:
    snapshot = deepcopy(snapshot)
    rt_rows = _price_rows_for_settlement(rt_price_rows, ERCOT_PRICE_SETTLEMENT_POINT)
    price_proxy = _price_proxy(list(rt_rows), settlement_point=ERCOT_PRICE_SETTLEMENT_POINT)
    price_series = _market_price_series(rt_rows, day_ahead_price_rows)

    snapshot["price_proxy"] = round(price_proxy, 2) if price_proxy is not None else None
    snapshot["price_settlement_point"] = ERCOT_PRICE_SETTLEMENT_POINT
    snapshot["price_label"] = ERCOT_PRICE_SETTLEMENT_POINT_LABEL
    snapshot["price_series"] = price_series
    snapshot["price_status"] = dict(price_status)

    trends = dict(snapshot.get("trends") or {})
    trends["price_proxy"] = _row_series(
        rt_rows,
        ERCOT_PRICE_VALUE_KEYS,
        ERCOT_PRICE_TIMESTAMP_KEYS,
        limit=96,
    )
    snapshot["trends"] = trends

    if price_proxy is None:
        for key in ("load_zones", "regions"):
            snapshot[key] = [_without_region_price(region) for region in snapshot.get(key, [])]

    return snapshot


def _without_region_price(region: dict[str, Any]) -> dict[str, Any]:
    updated = dict(region)
    updated["price_usd_mwh"] = None
    return updated


def _market_price_status(
    payloads: dict[str, dict[str, Any]],
    failures: dict[str, BaseException],
    rt_price_rows: Sequence[dict[str, Any]],
    day_ahead_price_rows: Sequence[dict[str, Any]],
) -> dict[str, str]:
    rt_payload = payloads.get("price") or {}
    cache_status = rt_payload.get("__local_cache_status")
    messages = []
    if isinstance(cache_status, dict) and cache_status.get("message"):
        messages.append(str(cache_status["message"]))
    if "day_ahead_price" in failures:
        messages.append(f"day_ahead_price: {_short_error(failures['day_ahead_price'])}")
    elif rt_price_rows and not day_ahead_price_rows:
        messages.append("day_ahead_price: no HB_NORTH rows returned")

    if rt_price_rows:
        if isinstance(cache_status, dict):
            state = str(cache_status.get("state") or "stale")
        else:
            state = "live"
        if state == "live" and messages:
            state = "partial"
        return _status("ERCOT RT/DA LMP", state, "; ".join(messages))

    if day_ahead_price_rows:
        if "price" in failures:
            messages.insert(0, f"price: {_short_error(failures['price'])}")
        else:
            messages.insert(0, f"price: no {ERCOT_PRICE_SETTLEMENT_POINT} RT LMP rows returned")
        return _status("ERCOT DA LMP", "partial", "; ".join(messages))

    if "price" in failures:
        return _status("ERCOT RT LMP", "unavailable", f"price: {_short_error(failures['price'])}")

    return _status("ERCOT RT LMP", "unavailable", f"No RT LMP rows returned for {ERCOT_PRICE_SETTLEMENT_POINT}.")


def _day_ahead_price_series(
    rows: Sequence[dict[str, Any]],
    settlement_point: str,
    *,
    limit: int = 48,
) -> list[dict[str, Any]]:
    price_rows = _price_rows_for_settlement(rows, settlement_point)
    series = []
    for row in price_rows[:limit]:
        value = _maybe_num(row, *ERCOT_DAY_AHEAD_PRICE_VALUE_KEYS)
        timestamp = _day_ahead_price_timestamp(row)
        if value is None or not timestamp:
            continue
        series.append({"timestamp": timestamp, "value": round(value, 2)})
    return sorted(series, key=lambda point: str(point["timestamp"]))


def _day_ahead_price_timestamp(row: dict[str, Any]) -> str:
    delivery_date = _raw_text(row, *ERCOT_DAY_AHEAD_PRICE_DATE_KEYS)
    hour_ending = _hour_ending(row)
    if not delivery_date or hour_ending is None:
        return _raw_text(row, "timestamp", "Timestamp")

    try:
        operating_day = date.fromisoformat(delivery_date[:10])
    except ValueError:
        return f"{delivery_date} HE {hour_ending}"

    timestamp = datetime.combine(operating_day, datetime.min.time()) + timedelta(hours=hour_ending - 1)
    return timestamp.isoformat()


def _hour_ending(row: dict[str, Any]) -> int | None:
    raw_hour = _raw_text(row, *ERCOT_DAY_AHEAD_PRICE_HOUR_KEYS)
    if not raw_hour:
        return None

    match = re.search(r"\d+", raw_hour)
    if not match:
        return None

    hour = int(match.group(0))
    return min(24, max(1, hour))


def _row_series(
    rows: Sequence[dict[str, Any]],
    value_keys: Sequence[str],
    timestamp_keys: Sequence[str],
    *,
    limit: int = 48,
) -> list[dict[str, Any]]:
    series = []
    for index, row in enumerate(rows[:limit]):
        value = _maybe_num(row, *value_keys)
        if value is None:
            continue
        series.append(
            {
                "timestamp": _raw_text(row, *timestamp_keys) or str(index),
                "value": round(value, 2),
            }
        )

    return sorted(series, key=lambda point: str(point["timestamp"]))


def _ercot_params(name: str) -> dict[str, Any]:
    params: dict[str, Any] = {"page": 1, "size": 20, "dir": "DESC"}
    start, end = _ercot_time_window(hours=12)
    if name in {"load", "generation"}:
        params["sort"] = "SCEDTimestamp"
    elif name in {"wind", "solar"}:
        params.update({"sort": "intervalEnding", "intervalEndingFrom": start, "intervalEndingTo": end})
    elif name == "price":
        params.update(
            {
                "size": _env_int("ERCOT_RT_LMP_POINTS", 36, minimum=12, maximum=96),
                "sort": "SCEDTimestamp",
                "SCEDTimestampFrom": start,
                "SCEDTimestampTo": end,
                "settlementPoint": ERCOT_PRICE_SETTLEMENT_POINT,
            }
        )
    elif name == "day_ahead_price":
        operating_day = _ercot_now().date().isoformat()
        params.update(
            {
                "size": 48,
                "sort": "hourEnding",
                "dir": "ASC",
                "deliveryDateFrom": operating_day,
                "deliveryDateTo": operating_day,
                "settlementPoint": ERCOT_PRICE_SETTLEMENT_POINT,
            }
        )
    return params


def _ercot_time_window(*, hours: int) -> tuple[str, str]:
    now = _ercot_now()
    start = now - timedelta(hours=hours)
    return _ercot_timestamp(start), _ercot_timestamp(now)


def _ercot_now() -> datetime:
    try:
        return datetime.now(ZoneInfo("America/Chicago")).replace(microsecond=0)
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().replace(microsecond=0)


def _ercot_timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def _price_proxy(rows: list[dict[str, Any]], *, settlement_point: str) -> float | None:
    row = _latest_price_row(_price_rows_for_settlement(rows, settlement_point))
    if not row:
        return None
    price = _maybe_num(row, *ERCOT_PRICE_VALUE_KEYS)
    return round(price, 2) if price is not None else None


def _price_rows_for_settlement(rows: Sequence[dict[str, Any]], settlement_point: str) -> list[dict[str, Any]]:
    normalized_settlement_point = _normalize_settlement_point(settlement_point)
    matching_rows = [
        row
        for row in rows
        if _normalize_settlement_point(_settlement_point(row)) == normalized_settlement_point
    ]
    if matching_rows:
        return matching_rows

    has_settlement_point_fields = any(_settlement_point(row) for row in rows)
    return [] if has_settlement_point_fields else list(rows)


def _latest_price_row(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    latest_row: dict[str, Any] = {}
    latest_timestamp: datetime | None = None

    for row in rows:
        if _maybe_num(row, *ERCOT_PRICE_VALUE_KEYS) is None:
            continue

        timestamp = _price_timestamp(row)
        if timestamp is None:
            if not latest_row and latest_timestamp is None:
                latest_row = row
            continue

        if latest_timestamp is None or timestamp > latest_timestamp:
            latest_timestamp = timestamp
            latest_row = row

    return latest_row


def _settlement_point(row: dict[str, Any]) -> str:
    return _raw_text(row, *ERCOT_PRICE_SETTLEMENT_POINT_KEYS)


def _normalize_settlement_point(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _price_timestamp(row: dict[str, Any]) -> datetime | None:
    return _parse_iso_datetime(_raw_text(row, *ERCOT_PRICE_TIMESTAMP_KEYS))


def _text(row: dict[str, Any], *keys: str) -> str:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None:
            return str(value).strip().upper()
    return ""


def _raw_text(row: dict[str, Any], *keys: str) -> str:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None:
            return str(value).strip()
    return ""


async def fetch_eia_snapshot(client: httpx.AsyncClient) -> dict[str, Any]:
    api_key = os.getenv("EIA_API_KEY")
    if not api_key:
        return empty_eia_snapshot("EIA_API_KEY is not set.", state="unavailable")

    params = {
        "api_key": api_key,
        "frequency": "hourly",
        "data[0]": "value",
        "facets[respondent][]": "ERCO",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "offset": 0,
        "length": 12,
    }

    try:
        payload = await _get_json(client, EIA_FUEL_MIX_URL, params=params)
    except Exception as exc:
        return empty_eia_snapshot(f"EIA fuel mix request failed: {exc}", state="unavailable")

    rows = payload.get("response", {}).get("data", [])
    latest_period = rows[0].get("period") if rows else ""
    latest_rows = [row for row in rows if row.get("period") == latest_period]
    total = sum(_num(row, "value") for row in latest_rows) or 1
    fuel_mix = {
        row.get("type-name", row.get("fueltype", "Other")): round((_num(row, "value") / total) * 100, 1)
        for row in latest_rows
    }

    if not fuel_mix:
        return empty_eia_snapshot("Live EIA response did not include fuel mix rows.", state="unavailable")

    return {
        "fuel_mix": fuel_mix,
        "latest_period": latest_period,
        "total_mwh": round(total, 1),
        "status": _status("EIA", "live"),
    }


async def fetch_eia_natural_gas(client: httpx.AsyncClient) -> dict[str, Any]:
    api_key = os.getenv("EIA_API_KEY")
    if not api_key:
        return empty_eia_natural_gas("EIA_API_KEY is not set.", state="unavailable")

    storage_params = _eia_gas_storage_params(api_key)
    balance_params = _eia_gas_balance_params(api_key)
    steo_params = _eia_gas_steo_params(api_key)

    try:
        storage_payload, balance_payload, steo_payload = await asyncio.gather(
            _get_json(client, EIA_GAS_STORAGE_URL, params=storage_params),
            _get_json(client, EIA_STEO_URL, params=balance_params),
            _get_json(client, EIA_STEO_URL, params=steo_params),
        )
    except Exception as exc:
        return empty_eia_natural_gas(f"EIA natural gas request failed: {exc}", state="unavailable")

    storage = _normalize_eia_gas_storage(storage_payload)
    balance = _normalize_eia_gas_balance(balance_payload)
    steo = _normalize_eia_steo_gas(steo_payload)
    if not storage["series"] or not balance["series"] or not steo["series"]:
        return empty_eia_natural_gas("Live EIA response did not include gas rows.", state="unavailable")

    return {
        "timestamp": utc_now().isoformat(),
        "storage": storage,
        "balance": balance,
        "steo": steo,
        "wells": empty_eia_natural_gas()["wells"],
        "status": _status("EIA Natural Gas", "live"),
    }


async def fetch_eia_natural_gas_feed(client: httpx.AsyncClient, feed_name: str) -> dict[str, Any]:
    normalized_name = _normalize_feed_name(feed_name)
    if normalized_name not in EIA_NATURAL_GAS_FEEDS:
        valid = ", ".join(EIA_NATURAL_GAS_FEEDS)
        raise ValueError(f"Unknown EIA natural gas feed '{feed_name}'. Valid feeds: {valid}.")

    config = EIA_NATURAL_GAS_FEEDS[normalized_name]
    title = str(config["title"])
    source_url = str(config["source_url"])
    api_key = os.getenv("EIA_API_KEY")
    if not api_key:
        data = empty_eia_natural_gas("EIA_API_KEY is not set.", state="unavailable")[normalized_name]
        return _feed_snapshot(
            f"eia-natural-gas-{normalized_name}",
            provider="EIA",
            title=title,
            source_url=source_url,
            status=_status("EIA Natural Gas", "unavailable", "EIA_API_KEY is not set."),
            data=data,
        )

    try:
        data = await _fetch_eia_natural_gas_feed_data(client, normalized_name, api_key)
    except Exception as exc:
        data = empty_eia_natural_gas(
            f"EIA natural gas feed '{normalized_name}' request failed: {exc}",
            state="unavailable",
        )[normalized_name]
        return _feed_snapshot(
            f"eia-natural-gas-{normalized_name}",
            provider="EIA",
            title=title,
            source_url=source_url,
            status=_status("EIA Natural Gas", "unavailable", f"{type(exc).__name__}: {exc}"),
            data=data,
        )

    if not data.get("series"):
        data = empty_eia_natural_gas(
            f"Live EIA response did not include rows for '{normalized_name}'.",
            state="unavailable",
        )[normalized_name]
        status = _status("EIA Natural Gas", "unavailable", f"Live EIA response did not include rows for '{normalized_name}'.")
    else:
        status = _status("EIA Natural Gas", "live")

    return _feed_snapshot(
        f"eia-natural-gas-{normalized_name}",
        provider="EIA",
        title=title,
        source_url=source_url,
        status=status,
        data=data,
    )


async def _fetch_eia_natural_gas_feed_data(
    client: httpx.AsyncClient,
    feed_name: str,
    api_key: str,
) -> dict[str, Any]:
    if feed_name == "storage":
        payload = await _get_json(client, EIA_GAS_STORAGE_URL, params=_eia_gas_storage_params(api_key))
        return _normalize_eia_gas_storage(payload)
    if feed_name == "balance":
        payload = await _get_json(client, EIA_STEO_URL, params=_eia_gas_balance_params(api_key))
        return _normalize_eia_gas_balance(payload)
    if feed_name == "steo":
        payload = await _get_json(client, EIA_STEO_URL, params=_eia_gas_steo_params(api_key))
        return _normalize_eia_steo_gas(payload)
    raise ValueError(f"Unknown EIA natural gas feed '{feed_name}'.")


def _eia_gas_storage_params(api_key: str) -> list[tuple[str, Any]]:
    storage_weeks = 104
    params: list[tuple[str, Any]] = [
        ("api_key", api_key),
        ("frequency", "weekly"),
        ("data[0]", "value"),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "desc"),
        ("offset", 0),
        ("length", storage_weeks * len(EIA_GAS_STORAGE_SERIES)),
    ]
    for series_id in EIA_GAS_STORAGE_SERIES.values():
        params.append(("facets[series][]", series_id))
    return params


def _eia_gas_balance_params(api_key: str) -> list[tuple[str, Any]]:
    balance_months = 48
    params: list[tuple[str, Any]] = [
        ("api_key", api_key),
        ("frequency", "monthly"),
        ("data[0]", "value"),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "desc"),
        ("offset", 0),
        ("length", balance_months * len(EIA_STEO_GAS_BALANCE_SERIES)),
    ]
    for series_id in EIA_STEO_GAS_BALANCE_SERIES.values():
        params.append(("facets[seriesId][]", series_id))
    return params


def _eia_gas_steo_params(api_key: str) -> list[tuple[str, Any]]:
    params: list[tuple[str, Any]] = [
        ("api_key", api_key),
        ("frequency", "monthly"),
        ("data[0]", "value"),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "desc"),
        ("offset", 0),
        ("length", 72),
    ]
    for series_id in EIA_STEO_SERIES.values():
        params.append(("facets[seriesId][]", series_id))
    return params


def _eia_gas_wells_params(api_key: str) -> list[tuple[str, Any]]:
    drilling_series_ids = [
        series_id
        for region in EIA_STEO_DRILLING_SERIES.values()
        for key, series_id in region.items()
        if key != "label"
    ]
    drilling_months = 36
    params: list[tuple[str, Any]] = [
        ("api_key", api_key),
        ("frequency", "monthly"),
        ("data[0]", "value"),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "desc"),
        ("offset", 0),
        ("length", drilling_months * len(drilling_series_ids)),
    ]
    for series_id in drilling_series_ids:
        params.append(("facets[seriesId][]", series_id))
    return params


def _normalize_eia_gas_storage(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("response", {}).get("data", [])
    storage_fields = {series_id: f"{name}_bcf" for name, series_id in EIA_GAS_STORAGE_SERIES.items()}
    by_period: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        period = str(row.get("period") or "")
        if not period:
            continue
        point = by_period.setdefault(period, {"period": period})
        field = storage_fields.get(str(row.get("series") or ""))
        if field:
            point[field] = round(_to_float(row.get("value")), 1)

    series = sorted(by_period.values(), key=lambda point: point["period"])
    latest = series[-1] if series else {}
    previous = series[-2] if len(series) > 1 else {}
    regions = [
        {"key": key, "field": f"{key}_bcf", "label": _title_from_key(key)}
        for key in EIA_GAS_STORAGE_SERIES
        if key != "lower_48"
    ]
    return {
        "source_url": EIA_GAS_STORAGE_URL,
        "series": series,
        "latest": latest,
        "regions": regions,
        "summary": {
            "lower_48_bcf": latest.get("lower_48_bcf", 0),
            "south_central_bcf": latest.get("south_central_bcf", 0),
            "lower_48_weekly_change_bcf": round(
                float(latest.get("lower_48_bcf") or 0) - float(previous.get("lower_48_bcf") or 0),
                1,
            )
            if previous
            else 0,
            "south_central_weekly_change_bcf": round(
                float(latest.get("south_central_bcf") or 0) - float(previous.get("south_central_bcf") or 0),
                1,
            )
            if previous
            else 0,
        },
    }


def _normalize_eia_gas_balance(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("response", {}).get("data", [])
    balance_fields = {series_id: field for field, series_id in EIA_STEO_GAS_BALANCE_SERIES.items()}
    by_period: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        period = str(row.get("period") or "")
        if not period:
            continue
        field = balance_fields.get(str(row.get("seriesId") or ""))
        if not field:
            continue
        point = by_period.setdefault(period, {"period": period})
        point[field] = round(_to_float(row.get("value")), 3)

    series = sorted(by_period.values(), key=lambda point: point["period"])
    for point in series:
        supply = float(point.get("supply_bcf_d") or 0)
        consumption = float(point.get("consumption_bcf_d") or 0)
        point["supply_consumption_gap_bcf_d"] = round(supply - consumption, 3)

    latest = _latest_period_with_value(series, "supply_bcf_d")
    previous = _previous_period_with_value(series, latest.get("period"), "working_inventory_bcf")
    return {
        "source_url": EIA_STEO_URL,
        "series": series,
        "latest": latest,
        "summary": {
            "latest_period": latest.get("period", ""),
            "supply_bcf_d": latest.get("supply_bcf_d", 0),
            "consumption_bcf_d": latest.get("consumption_bcf_d", 0),
            "working_inventory_bcf": latest.get("working_inventory_bcf", 0),
            "supply_consumption_gap_bcf_d": latest.get("supply_consumption_gap_bcf_d", 0),
            "inventory_monthly_change_bcf": round(
                float(latest.get("working_inventory_bcf") or 0) - float(previous.get("working_inventory_bcf") or 0),
                3,
            )
            if previous
            else 0,
            "note": "STEO monthly natural gas supply, consumption, and working inventory.",
        },
    }


def _normalize_eia_steo_gas(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("response", {}).get("data", [])
    by_period: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        period = str(row.get("period") or "")
        if not period:
            continue
        point = by_period.setdefault(period, {"period": period})
        series_id = row.get("seriesId")
        value = round(_to_float(row.get("value")), 3)
        if series_id == EIA_STEO_SERIES["henry_hub"]:
            point["henry_hub_usd_mmbtu"] = value
        elif series_id == EIA_STEO_SERIES["south_central_inventory"]:
            point["south_central_inventory_bcf"] = value

    series = sorted(by_period.values(), key=lambda point: point["period"])
    latest = _latest_period_with_value(series, "henry_hub_usd_mmbtu")
    return {
        "source_url": EIA_STEO_URL,
        "series": series,
        "latest": latest,
        "summary": {
            "latest_henry_hub_usd_mmbtu": latest.get("henry_hub_usd_mmbtu", 0),
            "latest_period": latest.get("period", ""),
        },
    }


def _normalize_eia_gas_wells(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("response", {}).get("data", [])
    fields = _eia_drilling_series_fields()
    by_region_period: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        period = str(row.get("period") or "")
        series_id = str(row.get("seriesId") or "")
        if not period or series_id not in fields:
            continue
        region_key, field = fields[series_id]
        region_config = EIA_STEO_DRILLING_SERIES[region_key]
        point = by_region_period.setdefault(
            (region_key, period),
            {"period": period, "region": region_config["label"], "region_key": region_key},
        )
        value = _to_float(row.get("value"))
        if field in {"active_rigs", "duc_wells", "new_wells_drilled", "new_wells_completed"}:
            point[field] = int(round(value))
        else:
            point[field] = round(value, 1)

    regions = sorted(
        by_region_period.values(),
        key=lambda point: (point["period"], _eia_drilling_region_order(str(point.get("region_key", "")))),
    )
    by_period: dict[str, dict[str, Any]] = {}
    for period in sorted({point["period"] for point in regions}):
        period_regions = [point for point in regions if point["period"] == period]
        active_rigs = sum(int(point.get("active_rigs") or 0) for point in period_regions)
        duc_wells = sum(int(point.get("duc_wells") or 0) for point in period_regions)
        drilled = sum(int(point.get("new_wells_drilled") or 0) for point in period_regions)
        completed = sum(int(point.get("new_wells_completed") or 0) for point in period_regions)
        gas_per_rig_values = [
            float(point.get("gas_per_rig_mmcf_d") or 0)
            for point in period_regions
            if _is_positive_number(point.get("gas_per_rig_mmcf_d"))
        ]
        by_period[period] = {
            "period": period,
            "active_rigs": active_rigs,
            "duc_wells": duc_wells,
            "new_wells_drilled": drilled,
            "new_wells_completed": completed,
            "duc_monthly_change": drilled - completed,
            "gas_per_rig_mmcf_d": round(sum(gas_per_rig_values) / len(gas_per_rig_values), 1) if gas_per_rig_values else 0,
        }

    series = sorted(by_period.values(), key=lambda point: point["period"])
    latest = _latest_period_with_value(series, "duc_wells")
    previous = _previous_period_with_value(series, latest.get("period"), "duc_wells")
    latest_period = str(latest.get("period") or "")
    latest_regions = [point for point in regions if point["period"] == latest_period]
    latest_regions = sorted(
        latest_regions,
        key=lambda point: _eia_drilling_region_order(str(point.get("region_key", ""))),
    )
    leading_region = max(latest_regions, key=lambda point: float(point.get("gas_per_rig_mmcf_d") or 0), default={})

    return {
        "source_url": EIA_STEO_URL,
        "source_page": EIA_DPR_PAGE_URL,
        "series": series,
        "regions": latest_regions,
        "latest": latest,
        "summary": {
            "latest_period": latest_period,
            "active_rigs": latest.get("active_rigs", 0),
            "duc_wells": latest.get("duc_wells", 0),
            "new_wells_drilled": latest.get("new_wells_drilled", 0),
            "new_wells_completed": latest.get("new_wells_completed", 0),
            "duc_monthly_change": latest.get("duc_monthly_change", 0),
            "duc_inventory_change": int(latest.get("duc_wells") or 0) - int(previous.get("duc_wells") or 0)
            if previous
            else 0,
            "gas_per_rig_mmcf_d": latest.get("gas_per_rig_mmcf_d", 0),
            "leading_gas_region": leading_region.get("region", ""),
            "leading_gas_per_rig_mmcf_d": leading_region.get("gas_per_rig_mmcf_d", 0),
            "note": "Live STEO drilling productivity metrics formerly published in the Drilling Productivity Report.",
        },
    }


def _eia_drilling_series_fields() -> dict[str, tuple[str, str]]:
    fields: dict[str, tuple[str, str]] = {}
    for region_key, region in EIA_STEO_DRILLING_SERIES.items():
        for field, series_id in region.items():
            if field != "label":
                fields[str(series_id)] = (region_key, field)
    return fields


def _eia_drilling_region_order(region_key: str) -> int:
    try:
        return list(EIA_STEO_DRILLING_SERIES).index(region_key)
    except ValueError:
        return len(EIA_STEO_DRILLING_SERIES)


def _is_positive_number(value: Any) -> bool:
    return _to_float(value) > 0


def _latest_period_with_value(series: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    for point in reversed(series):
        if key in point:
            return point
    return dict(series[-1]) if series else {}


def _previous_period_with_value(series: Sequence[dict[str, Any]], period: Any, key: str) -> dict[str, Any]:
    earlier = [point for point in series if point.get("period") != period]
    for point in reversed(earlier):
        if key in point:
            return point
    return {}


def _title_from_key(value: str) -> str:
    return value.replace("_", " ").title()


async def fetch_noaa_snapshot(client: httpx.AsyncClient) -> dict[str, Any]:
    return await fetch_noaa_airport_weather(client)


async def fetch_cpc_degree_day_forecast(
    client: httpx.AsyncClient,
    *,
    region: str = CPC_DEFAULT_REGION,
) -> dict[str, Any]:
    try:
        text = await _get_text(
            client,
            CPC_DEGREE_DAY_FORECAST_URL,
            headers={"User-Agent": _env_value("NWS_USER_AGENT", "NOAA_USER_AGENT") or DEFAULT_NWS_USER_AGENT},
        )
        snapshot = _parse_cpc_degree_day_forecast(text, region=region)
    except Exception as exc:
        return empty_cpc_degree_day_forecast(f"NOAA CPC degree-day request failed: {exc}", region=region, state="unavailable")

    if not snapshot["rows"]:
        return empty_cpc_degree_day_forecast(f"Region '{region}' was not found in CPC forecast text.", region=region, state="unavailable")

    snapshot["status"] = _status("NOAA CPC", "live")
    return snapshot


def _parse_cpc_degree_day_forecast(text: str, *, region: str = CPC_DEFAULT_REGION) -> dict[str, Any]:
    target = _normalize_region_name(region)
    issued_match = re.search(r"\b\d{3,4}\s+[AP]M\s+\w+\s+\w{3}\s+\d{1,2}\s+\w{3}\s+\d{4}\b", text)
    issued = issued_match.group(0) if issued_match else ""

    sections = _cpc_forecast_sections(text)
    target_section = next((section for section in sections if section["region"] == target), None)
    rows = _cpc_degree_day_rows(target_section["body"]) if target_section else []
    states = target_section["states"] if target_section else []

    return {
        "timestamp": utc_now().isoformat(),
        "issued": issued,
        "region": target,
        "states": states,
        "source_url": CPC_DEGREE_DAY_FORECAST_URL,
        "rows": rows,
        "regions": [{"region": section["region"], "states": section["states"]} for section in sections],
        "summary": _degree_day_summary(rows),
        "status": _status("NOAA CPC", "demo"),
    }


def _cpc_forecast_sections(text: str) -> list[dict[str, Any]]:
    normalized = " ".join(text.split())
    marker_matches = list(re.finditer(re.escape(CPC_HEADER_MARKER), normalized))
    sections = []
    for index, marker in enumerate(marker_matches):
        header = _cpc_section_header(normalized[: marker.start()])
        if not header:
            continue
        next_start = marker_matches[index + 1].start() if index + 1 < len(marker_matches) else len(normalized)
        sections.append(
            {
                "region": header["region"],
                "states": header["states"],
                "body": normalized[marker.end() : next_start],
            }
        )
    return sections


def _cpc_section_header(prefix: str) -> dict[str, Any] | None:
    parenthetical = re.search(r"\(([A-Z0-9 ]+)\)\s*$", prefix)
    if parenthetical:
        region = _cpc_trailing_region(prefix[: parenthetical.start()])
        if not region:
            return None
        return {"region": region, "states": _cpc_states(region, parenthetical.group(1))}

    region = _cpc_trailing_region(prefix)
    if not region:
        return None
    return {"region": region, "states": _cpc_states(region, "")}


def _cpc_trailing_region(value: str) -> str:
    match = re.search(r"(?:^|[0-9.])\s*([A-Z][A-Z ]+?)\s*$", value.strip())
    return _normalize_region_name(match.group(1)) if match else ""


def _cpc_states(region: str, raw_states: str) -> list[str]:
    states = [part for part in raw_states.split() if re.fullmatch(r"[A-Z]{2}", part)]
    if states:
        return states
    if region == "TEXAS":
        return ["TX"]
    return []


def _cpc_degree_day_rows(body: str) -> list[dict[str, Any]]:
    rows = []
    for match in CPC_ROW_PATTERN.finditer(body):
        year = int(match.group("year"))
        month = int(match.group("month"))
        rows.append(
            {
                "period": f"{year:04d}-{month:02d}",
                "year": year,
                "month": month,
                "heating_degree_days": {
                    "p90": float(match.group("hdd_p90")),
                    "mean": float(match.group("hdd_mean")),
                    "p10": float(match.group("hdd_p10")),
                    "normal": float(match.group("hdd_normal")),
                    "departure": float(match.group("hdd_departure")),
                },
                "cooling_degree_days": {
                    "p90": float(match.group("cdd_p90")),
                    "mean": float(match.group("cdd_mean")),
                    "p10": float(match.group("cdd_p10")),
                    "normal": float(match.group("cdd_normal")),
                    "departure": float(match.group("cdd_departure")),
                },
            }
        )
    return rows


def _normalize_region_name(value: str) -> str:
    return " ".join(str(value).upper().split())


def _degree_day_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"cooling_departure_total": 0, "heating_departure_total": 0, "peak_cooling_period": ""}
    peak_cooling = max(rows, key=lambda row: float(row["cooling_degree_days"]["mean"]))
    return {
        "cooling_departure_total": round(
            sum(float(row["cooling_degree_days"]["departure"]) for row in rows),
            1,
        ),
        "heating_departure_total": round(
            sum(float(row["heating_degree_days"]["departure"]) for row in rows),
            1,
        ),
        "peak_cooling_period": peak_cooling["period"],
        "peak_cooling_mean": round(float(peak_cooling["cooling_degree_days"]["mean"]), 1),
    }


async def fetch_noaa_airport_weather(
    client: httpx.AsyncClient,
    airport_codes: Sequence[str] | None = None,
) -> dict[str, Any]:
    stations = _selected_noaa_airports(airport_codes)

    results = await asyncio.gather(
        *[
            _fetch_nws_airport_observation(client, code, station)
            for code, station in stations.items()
        ],
        return_exceptions=True,
    )
    live_airports = [result for result in results if isinstance(result, dict)]
    failures = [
        f"{code}: {type(result).__name__}"
        for code, result in zip(stations, results)
        if isinstance(result, Exception)
    ]
    live_count = len(live_airports)
    if not live_count:
        detail = "; ".join(failures) if failures else "No station observations returned."
        return empty_noaa_snapshot(f"NWS station observations unavailable. {detail}", state="unavailable")

    airports = _merge_noaa_airport_rows(live_airports, stations)
    state = "live" if live_count == len(stations) else "partial"
    message = ""
    if state == "partial":
        detail = "; ".join(failures)
        message = f"{live_count}/{len(stations)} airport stations returned NWS observations."
        if detail:
            message = f"{message} {detail}"

    return _build_noaa_airports_snapshot(
        airports,
        station="NWS current airport observations",
        status=_status("NOAA", state, message),
    )


async def _fetch_nws_airport_observation(
    client: httpx.AsyncClient,
    code: str,
    station: dict[str, Any],
) -> dict[str, Any]:
    payload = await _get_json(
        client,
        _nws_observation_url(str(station["station_id"])),
        headers=_nws_headers(),
    )
    return _normalize_nws_airport_observation(payload, code, station)


def _nws_observation_url(station_id: str) -> str:
    return f"{NWS_API_BASE_URL}/stations/{station_id.strip().upper()}/observations/latest"


def _nws_headers() -> dict[str, str]:
    user_agent = _env_value("NWS_USER_AGENT", "NOAA_USER_AGENT") or DEFAULT_NWS_USER_AGENT
    return {"Accept": "application/geo+json", "User-Agent": user_agent}


def _selected_noaa_airports(airport_codes: Sequence[str] | None = None) -> dict[str, dict[str, Any]]:
    if not airport_codes:
        return dict(NOAA_AIRPORT_STATIONS)

    selected: dict[str, dict[str, Any]] = {}
    for code in airport_codes:
        normalized = str(code).strip().upper()
        if normalized in NOAA_AIRPORT_STATIONS:
            selected[normalized] = NOAA_AIRPORT_STATIONS[normalized]
    return selected or dict(NOAA_AIRPORT_STATIONS)


def _normalize_nws_airport_observation(
    payload: dict[str, Any],
    code: str,
    station: dict[str, Any],
) -> dict[str, Any]:
    properties = payload.get("properties")
    if not isinstance(properties, dict):
        raise ValueError(f"NWS observation for {code} did not include properties.")

    temperature = _nws_temperature_f(properties, "temperature")
    daily_high = _nws_temperature_f(properties, "maxTemperatureLast24Hours")
    daily_low = _nws_temperature_f(properties, "minTemperatureLast24Hours")
    wind = _nws_speed_mph(properties, "windSpeed")
    precipitation = _nws_precipitation_in(properties, "precipitationLastHour")
    observed_at = _nws_timestamp(properties.get("timestamp"))
    if not observed_at:
        raise ValueError(f"NWS observation for {code} did not include a timestamp.")

    missing = [
        label
        for label, value in (
            ("temperature", temperature),
            ("windSpeed", wind),
            ("precipitationLastHour", precipitation),
            ("maxTemperatureLast24Hours", daily_high),
            ("minTemperatureLast24Hours", daily_low),
        )
        if value is None
    ]

    return _airport_weather_row(
        code,
        station,
        observed_at=observed_at,
        temperature_f=temperature,
        daily_high_f=daily_high if daily_high is not None else temperature,
        daily_low_f=daily_low if daily_low is not None else temperature,
        wind_speed_mph=wind,
        precipitation_in=precipitation,
        source="live",
        missing_data_types=missing,
        description=str(properties.get("textDescription") or ""),
        raw_message=str(properties.get("rawMessage") or ""),
    )


def _nws_temperature_f(properties: dict[str, Any], key: str) -> float | None:
    value, unit = _nws_quantity(properties, key)
    if value is None:
        return None
    if "degF" in unit:
        return value
    return (value * 9 / 5) + 32


def _nws_speed_mph(properties: dict[str, Any], key: str) -> float | None:
    value, unit = _nws_quantity(properties, key)
    if value is None:
        return None
    if "mi_h-1" in unit or "mph" in unit:
        return value
    if "m_s-1" in unit:
        return value * 2.236936
    if "kt" in unit:
        return value * 1.150779
    return value * 0.621371


def _nws_precipitation_in(properties: dict[str, Any], key: str) -> float | None:
    value, unit = _nws_quantity(properties, key)
    if value is None:
        return None
    if unit.endswith(":in") or "inch" in unit:
        return value
    if unit.endswith(":mm"):
        return value / 25.4
    return value * 39.370079


def _nws_quantity(properties: dict[str, Any], key: str) -> tuple[float | None, str]:
    quantity = properties.get(key)
    if not isinstance(quantity, dict):
        return None, ""

    value = quantity.get("value")
    if value is None:
        return None, str(quantity.get("unitCode") or "")
    try:
        return float(value), str(quantity.get("unitCode") or "")
    except (TypeError, ValueError):
        return None, str(quantity.get("unitCode") or "")


def _nws_timestamp(value: Any) -> str:
    if not value:
        return ""
    text = str(value).strip()
    parsed = _parse_iso_datetime(text)
    return parsed.isoformat() if parsed else text


def _merge_noaa_airport_rows(
    live_airports: Sequence[dict[str, Any]],
    stations: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_code = {airport["airport"]: airport for airport in live_airports}
    return [by_code[code] for code in stations if code in by_code]


def _build_noaa_airports_snapshot(
    airports: Sequence[dict[str, Any]],
    *,
    station: str,
    status: dict[str, str],
) -> dict[str, Any]:
    high = _average(_airport_values(airports, "daily_high_f"), default=0)
    low = _average(_airport_values(airports, "daily_low_f"), default=0)
    temperatures = _airport_values(airports, "temperature_f")
    temperature = _average(temperatures, default=(high + low) / 2)
    wind = _average(_airport_values(airports, "wind_speed_mph"), default=0)
    precipitation = _average(_airport_values(airports, "precipitation_in"), default=0)
    observed_dates = [str(airport.get("observed_date", "")) for airport in airports if airport.get("observed_date")]
    observed_times = [str(airport.get("observed_at", "")) for airport in airports if airport.get("observed_at")]

    return {
        "timestamp": utc_now().isoformat(),
        "temperature_f": round(temperature, 1),
        "daily_high_f": round(high, 1),
        "daily_low_f": round(low, 1),
        "wind_speed_mph": round(wind, 1),
        "precipitation_in": round(precipitation, 2),
        "observed_date": max(observed_dates) if observed_dates else "",
        "observed_at": max(observed_times) if observed_times else "",
        "airport_count": len(airports),
        "airports": list(airports),
        "station": station,
        "stream_url": "/ws/weather",
        "status": status,
    }


def _airport_values(airports: Sequence[dict[str, Any]], key: str) -> list[float]:
    values = []
    for airport in airports:
        value = airport.get(key)
        if isinstance(value, int | float):
            values.append(float(value))
    return values


def _airport_weather_row(
    code: str,
    station: dict[str, Any],
    *,
    observed_at: str,
    temperature_f: float | None,
    daily_high_f: float | None,
    daily_low_f: float | None,
    wind_speed_mph: float | None,
    precipitation_in: float | None,
    source: str,
    missing_data_types: Sequence[str] = (),
    description: str = "",
    raw_message: str = "",
) -> dict[str, Any]:
    observed_date = _date_from_timestamp(observed_at)

    return {
        "airport": code,
        "name": station["name"],
        "station_id": station["station_id"],
        "lat": station["lat"],
        "lon": station["lon"],
        "observed_at": observed_at,
        "observed_date": observed_date,
        "age_days": _age_days(observed_date),
        "age_minutes": _age_minutes(observed_at),
        "temperature_f": _round_or_none(temperature_f),
        "daily_high_f": _round_or_none(daily_high_f),
        "daily_low_f": _round_or_none(daily_low_f),
        "wind_speed_mph": _round_or_none(wind_speed_mph),
        "precipitation_in": _round_or_none(precipitation_in, ndigits=2),
        "missing_data_types": list(missing_data_types) if source == "live" else [],
        "description": description,
        "raw_message": raw_message,
        "source": source,
    }


def _demo_noaa_airport(code: str, station: dict[str, Any], index: int) -> dict[str, Any]:
    offsets = {"DFW": 1.5, "IAH": 0.5, "AUS": 2.0, "LBB": -2.0, "SAT": 2.4, "ELP": 3.5}
    temp = _demo_wave(86 + offsets.get(code, 0), 8, 24, offset=-6 + index)
    wind = max(3, _demo_wave(10 + index * 0.35, 4, 18, offset=1 + index))
    precipitation = max(0, _demo_wave(0.03, 0.04, 12, offset=index))
    return _airport_weather_row(
        code,
        station,
        observed_at=utc_now().isoformat(),
        temperature_f=temp,
        daily_high_f=temp + 8,
        daily_low_f=temp - 10,
        wind_speed_mph=wind,
        precipitation_in=precipitation,
        source="demo",
        description="Demo observation",
    )


def _date_from_timestamp(value: str) -> str:
    parsed = _parse_iso_datetime(value)
    if parsed:
        return parsed.date().isoformat()
    return str(value)[:10] if value else ""


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(value: str) -> int | None:
    try:
        observed = date.fromisoformat(value)
    except ValueError:
        return None
    return max(0, (utc_now().date() - observed).days)


def _age_minutes(value: str) -> int | None:
    observed = _parse_iso_datetime(value)
    if not observed:
        return None
    age = utc_now() - observed
    return max(0, round(age.total_seconds() / 60))


def _round_or_none(value: float | None, *, ndigits: int = 1) -> float | None:
    if value is None:
        return None
    return round(value, ndigits)


def _maybe_num(row: dict[str, Any], *keys: str) -> float | None:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is None:
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            continue
    return None


def _average(values: Sequence[float | None], *, default: float) -> float:
    usable = [value for value in values if value is not None]
    return sum(usable) / len(usable) if usable else default


def demo_ercot_snapshot() -> dict[str, Any]:
    load = _demo_wave(58500, 7200, 24, offset=-7)
    wind = _demo_wave(11900, 2200, 18, offset=2)
    solar = max(0, _demo_wave(5100, 5200, 24, offset=-6))
    generation = load + 4300 + max(0, _demo_wave(800, 900, 12))
    price = 35 + max(0, (load - 61000) / 1300) * 8
    rt_price_series = _demo_recent_series(price, amplitude_pct=0.12, period_hours=10, offset=-1.0)
    da_price_series = _demo_day_ahead_price_series(price)

    load_zones = _load_zone_metrics(load, generation, price, estimate_zone_prices=True)

    return {
        "load_mw": round(load, 1),
        "generation_mw": round(generation, 1),
        "wind_mw": round(wind, 1),
        "solar_mw": round(solar, 1),
        "price_proxy": round(price, 2),
        "price_settlement_point": ERCOT_PRICE_SETTLEMENT_POINT,
        "price_label": ERCOT_PRICE_SETTLEMENT_POINT_LABEL,
        "price_series": {
            "settlement_point": ERCOT_PRICE_SETTLEMENT_POINT,
            "label": "North Hub",
            "rt_lmp": [dict(point) for point in rt_price_series],
            "da_lmp": da_price_series,
        },
        "price_status": _status("ERCOT RT/DA LMP", "demo"),
        "reserve_margin_pct": round(((generation - load) / load) * 100, 1),
        "load_zones": load_zones,
        "regions": [dict(zone) for zone in load_zones],
        "trends": {
            "load_mw": _demo_recent_series(load, amplitude_pct=0.055),
            "generation_mw": _demo_recent_series(generation, amplitude_pct=0.035, offset=1.4),
            "wind_mw": _demo_recent_series(wind, amplitude_pct=0.18, period_hours=18, offset=2.2),
            "solar_mw": _demo_recent_series(solar, amplitude_pct=0.45, period_hours=24, offset=-5.5, floor=0),
            "price_proxy": [dict(point) for point in rt_price_series],
        },
        "status": _status("ERCOT", "demo"),
    }


def demo_supply_demand_snapshot() -> dict[str, Any]:
    now = _ercot_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for minute in range(0, 24 * 60 + 5, 5):
        timestamp = start + timedelta(minutes=minute)
        hour = minute / 60
        demand = 56000 + 7400 * math.sin(((hour - 7) / 24) * math.tau) + 2200 * math.sin((hour / 12) * math.tau)
        demand = max(42000, demand)
        capacity = demand + 14500 + 2200 * math.sin(((hour + 3) / 24) * math.tau)
        available = capacity + 7800 + max(0, 2600 * math.sin(((hour - 10) / 24) * math.tau))
        is_forecast = timestamp > now
        rows.append(
            {
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S%z"),
                "epoch": int(timestamp.timestamp() * 1000),
                "demand": round(demand),
                "capacity": round(capacity),
                "available": round(available) if is_forecast else None,
                "forecast": int(is_forecast),
                "hourEnding": min(24, int(hour) + 1),
                "interval": minute % 60,
            }
        )

    forecast = []
    for hour_offset in range(1, 145):
        timestamp = start + timedelta(days=1, hours=hour_offset)
        hour = timestamp.hour
        daily = 58000 + 8200 * math.sin(((hour - 7) / 24) * math.tau)
        day_lift = (hour_offset // 24) * 420
        demand = daily + day_lift
        available = demand + 36000 + 4600 * math.sin(((hour + 2) / 24) * math.tau)
        forecast.append(
            {
                "deliveryDate": timestamp.date().isoformat(),
                "hourEnding": hour or 24,
                "forecastedDemand": round(demand),
                "availCapGen": round(available),
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S%z"),
                "epoch": int(timestamp.timestamp() * 1000),
            }
        )

    snapshot = _normalize_supply_demand_payload(
        {
            "lastUpdated": now.strftime("%Y-%m-%d %H:%M:%S%z"),
            "data": rows,
            "forecast": forecast,
        }
    )
    snapshot["status"] = _status("ERCOT Supply/Demand", "demo")
    return snapshot


def demo_ercot_public_dashboards() -> dict[str, Any]:
    now = _ercot_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    timestamps = [start + timedelta(minutes=5 * index) for index in range(0, 13 * 12)]

    prc_series = []
    storage_current = []
    outage_current = []
    fuel_series = []
    fuel_names = ["Natural Gas", "Wind", "Coal and Lignite", "Solar", "Nuclear", "Power Storage", "Other"]
    fuel_capacity = {
        "Natural Gas": 67500,
        "Wind": 43500,
        "Coal and Lignite": 13200,
        "Solar": 32300,
        "Nuclear": 5200,
        "Power Storage": 9800,
        "Other": 950,
    }
    for index, timestamp in enumerate(timestamps):
        hour = timestamp.hour + timestamp.minute / 60
        prc = 6500 + 1600 * math.sin(((hour + 2) / 24) * math.tau) - index * 7
        prc_series.append({"timestamp": timestamp.isoformat(), "epoch": int(timestamp.timestamp() * 1000), "prc_mw": round(max(2800, prc), 1)})

        charge = max(0, 820 * math.sin(((hour - 1) / 24) * math.tau))
        discharge = max(0, 1180 * math.sin(((hour - 15) / 24) * math.tau))
        storage_current.append(
            {
                "timestamp": timestamp.isoformat(),
                "charging_mw": round(charge, 1),
                "discharging_mw": round(discharge, 1),
                "net_mw": round(discharge - charge, 1),
            }
        )

        planned = 10400 + 420 * math.sin((hour / 24) * math.tau)
        unplanned = 18100 + 1250 * math.sin(((hour + 5) / 24) * math.tau)
        outage_current.append(
            {
                "timestamp": timestamp.isoformat(),
                "epoch": int(timestamp.timestamp() * 1000),
                "planned_mw": round(planned, 1),
                "unplanned_mw": round(unplanned, 1),
                "total_mw": round(planned + unplanned, 1),
                "dispatchable_mw": round((planned + unplanned) * 0.78, 1),
                "renewable_mw": round((planned + unplanned) * 0.22, 1),
            }
        )

        solar = max(0, 14500 * math.sin(((hour - 6.2) / 14) * math.pi))
        fuels = {
            "Natural Gas": round(24500 + 2600 * math.sin(((hour - 16) / 24) * math.tau), 1),
            "Wind": round(13400 + 2400 * math.sin(((hour + 2) / 18) * math.tau), 1),
            "Coal and Lignite": round(5750 + 420 * math.sin((hour / 24) * math.tau), 1),
            "Solar": round(solar, 1),
            "Nuclear": 3850,
            "Power Storage": round(discharge - charge, 1),
            "Other": 80,
        }
        fuel_details = {}
        for fuel, generation in fuels.items():
            capacity = fuel_capacity[fuel]
            if fuel == "Wind":
                hsl = max(generation * 1.18, 0.34 * capacity)
            elif fuel == "Solar":
                hsl = max(generation * 1.12, 0 if generation <= 0 else 0.52 * capacity)
            elif fuel == "Power Storage":
                hsl = max(abs(generation) * 1.3, 0.58 * capacity)
            else:
                outage_shape = 0.08 + 0.035 * math.sin(((hour + index / 4) / 24) * math.tau)
                fuel_bias = {
                    "Natural Gas": 0.18,
                    "Coal and Lignite": 0.11,
                    "Nuclear": 0.06,
                    "Other": 0.2,
                }.get(fuel, 0.08)
                hsl = max(generation, capacity * (1 - fuel_bias - outage_shape))
            fuel_details[fuel] = {
                "generation_mw": round(generation, 1),
                "hsl_mw": round(min(capacity, hsl), 1),
                "capacity_mw": round(capacity, 1),
            }

        fuel_series.append(
            {
                "timestamp": timestamp.isoformat(),
                "total_mw": round(sum(fuels.values()), 1),
                "fuels": fuels,
                "fuel_details": fuel_details,
            }
        )

    latest_fuel = fuel_series[-1]
    latest_total = float(latest_fuel["total_mw"] or 1)
    latest_mix = [
        {
            "fuel": fuel,
            "generation_mw": round(value, 1),
            "share_pct": round((value / latest_total) * 100, 1),
            "hsl_mw": latest_fuel["fuel_details"][fuel]["hsl_mw"],
            "capacity_mw": latest_fuel["fuel_details"][fuel]["capacity_mw"],
            "unavailable_mw": round(
                max(latest_fuel["fuel_details"][fuel]["capacity_mw"] - latest_fuel["fuel_details"][fuel]["hsl_mw"], 0),
                1,
            ),
            "headroom_mw": round(max(latest_fuel["fuel_details"][fuel]["hsl_mw"] - value, 0), 1),
            "availability_pct": round(
                (latest_fuel["fuel_details"][fuel]["hsl_mw"] / max(latest_fuel["fuel_details"][fuel]["capacity_mw"], 1)) * 100,
                1,
            ),
            "utilization_pct": round((value / max(latest_fuel["fuel_details"][fuel]["hsl_mw"], 1)) * 100, 1),
        }
        for fuel, value in sorted(latest_fuel["fuels"].items(), key=lambda item: item[1], reverse=True)
    ]

    combined_current = []
    for hour_ending in range(1, 25):
        timestamp = start + timedelta(hours=hour_ending)
        hour = timestamp.hour or 24
        wind_forecast = 18400 + 4100 * math.sin(((hour + 1) / 18) * math.tau)
        solar_forecast = max(0, 32200 * math.sin(((hour - 6.2) / 14) * math.pi))
        has_actual = timestamp <= now
        wind_actual = wind_forecast * (0.98 + 0.035 * math.sin(hour))
        solar_actual = solar_forecast * (0.97 + 0.045 * math.sin(hour / 2))
        combined_current.append(
            {
                "timestamp": timestamp.isoformat(),
                "epoch": int(timestamp.timestamp() * 1000),
                "hour_ending": hour_ending,
                "dst_flag": "N",
                "wind_actual_mw": round(max(0, wind_actual), 1) if has_actual else None,
                "solar_actual_mw": round(max(0, solar_actual), 1) if has_actual else None,
                "combined_actual_mw": round(max(0, wind_actual) + max(0, solar_actual), 1) if has_actual else None,
                "wind_forecast_mw": round(max(0, wind_forecast), 1),
                "solar_forecast_mw": round(max(0, solar_forecast), 1),
                "combined_forecast_mw": round(max(0, wind_forecast) + max(0, solar_forecast), 1),
            }
        )
    combined_actual = [point for point in combined_current if point["combined_actual_mw"] is not None]
    combined_forecast = [point for point in combined_current if point["combined_actual_mw"] is None]

    ancillary_products = [
        {"name": "Responsive Reserve", "capability_mw": 4020, "awards_mw": 2701},
        {"name": "ECRS", "capability_mw": 2108, "awards_mw": 2110},
        {"name": "Non-Spin", "capability_mw": 3650, "awards_mw": 4160},
        {"name": "Reg Up", "capability_mw": 510, "awards_mw": 505},
        {"name": "Reg Down", "capability_mw": 430, "awards_mw": 425},
    ]

    return {
        "timestamp": utc_now().isoformat(),
        "prc": {
            "last_updated": now.isoformat(),
            "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['prc']}",
            "condition": {
                "title": "Normal Conditions",
                "note": "Demo PRC signal.",
                "eea_level": 0,
                "state": "normal",
                "energy_level_value": 20,
            },
            "latest_prc_mw": prc_series[-1]["prc_mw"],
            "series": prc_series,
        },
        "fuel_mix": {
            "last_updated": now.isoformat(),
            "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['fuel_mix']}",
            "fuel_types": fuel_names,
            "series": fuel_series,
            "monthlyCapacity": fuel_capacity,
            "latest": {"timestamp": latest_fuel["timestamp"], "total_mw": latest_fuel["total_mw"], "mix": latest_mix},
        },
        "storage": {
            "last_updated": now.isoformat(),
            "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['storage']}",
            "current_day": storage_current,
            "previous_day": [],
            "latest": storage_current[-1],
            "summary": {
                "max_charging_mw": round(max(point["charging_mw"] for point in storage_current), 1),
                "max_discharging_mw": round(max(point["discharging_mw"] for point in storage_current), 1),
                "latest_net_mw": storage_current[-1]["net_mw"],
            },
        },
        "combined_renewables": {
            "last_updated": now.isoformat(),
            "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['combined_renewables']}",
            "current_day": combined_current,
            "latest_actual": combined_actual[-1] if combined_actual else {},
            "summary": {
                "actual_points": len(combined_actual),
                "forecast_points": len(combined_forecast),
                "peak_actual_mw": round(max((point["combined_actual_mw"] for point in combined_actual), default=0), 1),
                "peak_forecast_mw": round(max((point["combined_forecast_mw"] for point in combined_current), default=0), 1),
            },
            "forecast_fields": {"wind": "stwpf", "solar": "stppf"},
        },
        "outages": {
            "last_updated": now.isoformat(),
            "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['outages']}",
            "current_outages_mw": outage_current[-1]["total_mw"],
            "types": ["Dispatchable", "Renewable"],
            "current": outage_current,
            "previous": [],
            "latest": outage_current[-1],
        },
        "ancillary": {
            "last_updated": now.isoformat(),
            "source_url": f"{ERCOT_DASHBOARD_BASE_URL}/{ERCOT_PUBLIC_DASHBOARDS['ancillary']}",
            "interval": now.strftime("%H:%M:%S"),
            "products": ancillary_products,
            "system": {
                "prc_mw": prc_series[-1]["prc_mw"],
                "online_reserve_mw": 0,
                "online_offline_reserve_mw": 0,
            },
            "groups": {},
        },
        "status": _status("ERCOT Dashboards", "demo"),
    }


def _demo_recent_series(
    latest: float,
    *,
    amplitude_pct: float,
    period_hours: float = 24,
    offset: float = 0,
    floor: float | None = None,
    points: int = 36,
) -> list[dict[str, Any]]:
    now = _ercot_now()
    series = []
    for index in range(points):
        timestamp = now - timedelta(minutes=(points - index - 1) * 5)
        phase = ((index / 12) + offset) / period_hours
        value = latest * (1 + amplitude_pct * math.sin(phase * math.tau))
        if floor is not None:
            value = max(floor, value)
        series.append({"timestamp": timestamp.isoformat(), "value": round(value, 2)})
    return series


def _demo_day_ahead_price_series(latest: float, *, points: int = 24) -> list[dict[str, Any]]:
    now = _ercot_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    series = []
    for hour_ending in range(1, points + 1):
        timestamp = start + timedelta(hours=hour_ending)
        hour = hour_ending % 24
        value = latest * (1 + 0.09 * math.sin(((hour - 8) / 24) * math.tau))
        value += 2.4 * math.sin(((hour + 2) / 12) * math.tau)
        series.append({"timestamp": timestamp.isoformat(), "value": round(max(5, value), 2)})
    return series


def demo_eia_snapshot() -> dict[str, Any]:
    return {
        "fuel_mix": {
            "Natural gas": 46.5,
            "Wind": 24.0,
            "Coal": 12.4,
            "Solar": 9.6,
            "Nuclear": 7.1,
            "Other": 0.4,
        },
        "latest_period": utc_now().strftime("%Y-%m-%dT%H"),
        "total_mwh": 64150,
        "status": _status("EIA", "demo"),
    }


def demo_eia_natural_gas() -> dict[str, Any]:
    today = utc_now().date()
    storage_series = []
    for index in range(104):
        weeks_back = 103 - index
        period = today - timedelta(days=today.weekday() + 3 + weeks_back * 7)
        seasonal = math.sin(((index - 16) / 52) * math.tau)
        east = 720 + 185 * seasonal
        midwest = 835 + 220 * seasonal
        south_central = 940 + 250 * seasonal
        mountain = 205 + 48 * seasonal
        pacific = 265 + 64 * seasonal
        lower_48 = east + midwest + south_central + mountain + pacific
        storage_series.append(
            {
                "period": period.isoformat(),
                "lower_48_bcf": round(lower_48, 1),
                "east_bcf": round(east, 1),
                "midwest_bcf": round(midwest, 1),
                "south_central_bcf": round(south_central, 1),
                "mountain_bcf": round(mountain, 1),
                "pacific_bcf": round(pacific, 1),
            }
        )

    month_start = utc_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    balance_series = []
    for offset in range(-23, 25):
        period_date = _shift_month(month_start, offset)
        month = period_date.month
        seasonal = math.cos(((month - 1) / 12) * math.tau)
        production_trend = (offset + 23) * 0.08
        supply = 101.5 + production_trend + 2.5 * math.sin(offset / 8) + 9.8 * max(0, seasonal) - 4.8 * max(0, -seasonal)
        consumption = 92.0 + 19.5 * max(0, seasonal) + 8.6 * max(0, -seasonal) + 1.3 * math.sin(offset / 5)
        inventory = 3180 - 620 * seasonal + 65 * math.sin(offset / 4)
        balance_series.append(
            {
                "period": period_date.strftime("%Y-%m"),
                "supply_bcf_d": round(supply, 3),
                "consumption_bcf_d": round(consumption, 3),
                "working_inventory_bcf": round(inventory, 3),
                "supply_consumption_gap_bcf_d": round(supply - consumption, 3),
            }
        )

    steo_series = []
    for offset in range(-12, 24):
        period_date = _shift_month(month_start, offset)
        phase = ((offset + 3) / 12) * math.tau
        steo_series.append(
            {
                "period": period_date.strftime("%Y-%m"),
                "henry_hub_usd_mmbtu": round(3.45 + 0.42 * math.sin(phase), 3),
                "south_central_inventory_bcf": round(1040 + 190 * math.sin(phase - 1.1), 1),
            }
        )

    drilling_region_defs = [
        ("appalachia", "Appalachia", 43, 820, 92, 88, 28.6),
        ("haynesville", "Haynesville", 36, 790, 58, 55, 13.5),
        ("permian", "Permian", 315, 895, 440, 452, 2.6),
        ("eagle_ford", "Eagle Ford", 49, 345, 71, 76, 6.1),
        ("bakken", "Bakken", 34, 330, 62, 61, 2.7),
        ("rest_lower_48", "Rest of Lower 48", 54, 1330, 86, 80, 5.1),
    ]
    wells_series = []
    wells_regions = []
    for offset in range(-35, 1):
        period_date = _shift_month(month_start, offset)
        period = period_date.strftime("%Y-%m")
        region_rows = []
        for index, (key, label, rigs, ducs, drilled, completed, gas_per_rig) in enumerate(drilling_region_defs):
            wave = math.sin((offset + index * 2) / 5)
            trend = 1 + (offset + 35) * 0.002
            active_rigs = max(1, int(round(rigs * trend + wave * 4)))
            duc_wells = max(1, int(round(ducs - (offset + 35) * (2 + index * 0.25) + wave * 12)))
            new_wells_drilled = max(0, int(round(drilled * trend + wave * 5)))
            new_wells_completed = max(0, int(round(completed * trend - wave * 4)))
            productivity = round(gas_per_rig * (1 + (offset + 35) * 0.0015 + 0.018 * wave), 1)
            region_rows.append(
                {
                    "period": period,
                    "region": label,
                    "region_key": key,
                    "active_rigs": active_rigs,
                    "duc_wells": duc_wells,
                    "new_wells_drilled": new_wells_drilled,
                    "new_wells_completed": new_wells_completed,
                    "duc_monthly_change": new_wells_drilled - new_wells_completed,
                    "gas_per_rig_mmcf_d": productivity,
                }
            )

        if offset == 0:
            wells_regions = region_rows
        wells_series.append(
            {
                "period": period,
                "active_rigs": sum(row["active_rigs"] for row in region_rows),
                "duc_wells": sum(row["duc_wells"] for row in region_rows),
                "new_wells_drilled": sum(row["new_wells_drilled"] for row in region_rows),
                "new_wells_completed": sum(row["new_wells_completed"] for row in region_rows),
                "duc_monthly_change": sum(row["duc_monthly_change"] for row in region_rows),
                "gas_per_rig_mmcf_d": round(sum(row["gas_per_rig_mmcf_d"] for row in region_rows) / len(region_rows), 1),
            }
        )

    latest_storage = storage_series[-1]
    previous_storage = storage_series[-2]
    latest_balance = balance_series[-1]
    previous_balance = balance_series[-2]
    latest_steo = _latest_period_with_value(steo_series, "henry_hub_usd_mmbtu")
    latest_wells = wells_series[-1]
    previous_wells = wells_series[-2]
    leading_region = max(wells_regions, key=lambda row: row["gas_per_rig_mmcf_d"])
    return {
        "timestamp": utc_now().isoformat(),
        "storage": {
            "source_url": EIA_GAS_STORAGE_URL,
            "series": storage_series,
            "latest": latest_storage,
            "regions": [
                {"key": "east", "field": "east_bcf", "label": "East"},
                {"key": "midwest", "field": "midwest_bcf", "label": "Midwest"},
                {"key": "south_central", "field": "south_central_bcf", "label": "South Central"},
                {"key": "mountain", "field": "mountain_bcf", "label": "Mountain"},
                {"key": "pacific", "field": "pacific_bcf", "label": "Pacific"},
            ],
            "summary": {
                "lower_48_bcf": latest_storage["lower_48_bcf"],
                "south_central_bcf": latest_storage["south_central_bcf"],
                "lower_48_weekly_change_bcf": round(latest_storage["lower_48_bcf"] - previous_storage["lower_48_bcf"], 1),
                "south_central_weekly_change_bcf": round(
                    latest_storage["south_central_bcf"] - previous_storage["south_central_bcf"],
                    1,
                ),
            },
        },
        "balance": {
            "source_url": EIA_STEO_URL,
            "series": balance_series,
            "latest": latest_balance,
            "summary": {
                "latest_period": latest_balance["period"],
                "supply_bcf_d": latest_balance["supply_bcf_d"],
                "consumption_bcf_d": latest_balance["consumption_bcf_d"],
                "working_inventory_bcf": latest_balance["working_inventory_bcf"],
                "supply_consumption_gap_bcf_d": latest_balance["supply_consumption_gap_bcf_d"],
                "inventory_monthly_change_bcf": round(
                    latest_balance["working_inventory_bcf"] - previous_balance["working_inventory_bcf"],
                    3,
                ),
                "note": "STEO monthly natural gas supply, consumption, and working inventory.",
            },
        },
        "steo": {
            "source_url": EIA_STEO_URL,
            "series": steo_series,
            "latest": latest_steo,
            "summary": {
                "latest_henry_hub_usd_mmbtu": latest_steo["henry_hub_usd_mmbtu"],
                "latest_period": latest_steo["period"],
            },
        },
        "wells": {
            "source_url": EIA_STEO_URL,
            "source_page": EIA_DPR_PAGE_URL,
            "series": wells_series,
            "regions": wells_regions,
            "latest": latest_wells,
            "summary": {
                "latest_period": latest_wells["period"],
                "active_rigs": latest_wells["active_rigs"],
                "duc_wells": latest_wells["duc_wells"],
                "new_wells_drilled": latest_wells["new_wells_drilled"],
                "new_wells_completed": latest_wells["new_wells_completed"],
                "duc_monthly_change": latest_wells["duc_monthly_change"],
                "duc_inventory_change": latest_wells["duc_wells"] - previous_wells["duc_wells"],
                "gas_per_rig_mmcf_d": latest_wells["gas_per_rig_mmcf_d"],
                "leading_gas_region": leading_region["region"],
                "leading_gas_per_rig_mmcf_d": leading_region["gas_per_rig_mmcf_d"],
                "note": "Live STEO drilling productivity metrics formerly published in the Drilling Productivity Report.",
            },
        },
        "status": _status("EIA Natural Gas", "demo"),
    }


def _shift_month(value: datetime, offset: int) -> datetime:
    month_index = value.year * 12 + (value.month - 1) + offset
    year, month = divmod(month_index, 12)
    return value.replace(year=year, month=month + 1)


def demo_noaa_snapshot() -> dict[str, Any]:
    return demo_noaa_airports_snapshot()


def demo_noaa_airports_snapshot(airport_codes: Sequence[str] | None = None) -> dict[str, Any]:
    stations = _selected_noaa_airports(airport_codes)
    airports = [_demo_noaa_airport(code, station, index) for index, (code, station) in enumerate(stations.items())]
    return _build_noaa_airports_snapshot(
        airports,
        station="Demo Texas current station average",
        status=_status("NOAA", "demo"),
    )


def demo_cpc_degree_day_forecast(*, region: str = CPC_DEFAULT_REGION) -> dict[str, Any]:
    start = utc_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for offset in range(15):
        period_date = _shift_month(start, offset)
        month = period_date.month
        cooling_normal = max(0, 345 * math.sin(((month - 3) / 12) * math.pi))
        heating_normal = max(0, 360 * math.sin(((month + 3) / 12) * math.pi))
        cdd_departure = 8 + 10 * math.sin((offset / 15) * math.tau)
        hdd_departure = -6 - 5 * math.sin((offset / 15) * math.tau)
        rows.append(
            {
                "period": period_date.strftime("%Y-%m"),
                "year": period_date.year,
                "month": month,
                "heating_degree_days": {
                    "p90": round(max(0, heating_normal + hdd_departure - 35), 1),
                    "mean": round(max(0, heating_normal + hdd_departure), 1),
                    "p10": round(max(0, heating_normal + hdd_departure + 35), 1),
                    "normal": round(heating_normal, 1),
                    "departure": round(hdd_departure, 1),
                },
                "cooling_degree_days": {
                    "p90": round(max(0, cooling_normal + cdd_departure - 35), 1),
                    "mean": round(max(0, cooling_normal + cdd_departure), 1),
                    "p10": round(max(0, cooling_normal + cdd_departure + 35), 1),
                    "normal": round(cooling_normal, 1),
                    "departure": round(cdd_departure, 1),
                },
            }
        )

    normalized_region = _normalize_region_name(region)
    return {
        "timestamp": utc_now().isoformat(),
        "issued": utc_now().strftime("%I%M %p UTC %a %d %b %Y"),
        "region": normalized_region,
        "states": _cpc_states(normalized_region, ""),
        "source_url": CPC_DEGREE_DAY_FORECAST_URL,
        "rows": rows,
        "regions": [{"region": CPC_DEFAULT_REGION, "states": _cpc_states(CPC_DEFAULT_REGION, "")}],
        "summary": _degree_day_summary(rows),
        "status": _status("NOAA CPC", "demo"),
    }

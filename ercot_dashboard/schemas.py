from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class SourceStatus(ApiModel):
    source: str = Field(..., examples=["ERCOT"])
    state: str = Field(..., examples=["live"])
    message: str = Field(default="", examples=["Using normalized public API data."])


class HealthResponse(ApiModel):
    status: Literal["ok"] = Field(default="ok")
    backend: Literal["fastapi"] = Field(default="fastapi")


class TimeSeriesPoint(ApiModel):
    timestamp: str = Field(..., examples=["2026-05-13T15:00:00+00:00"])
    value: float = Field(..., examples=[64150.0])
    is_forecast: bool | None = Field(default=None)


class EventRecord(ApiModel):
    time: str = Field(..., examples=["15:04:21 UTC"])
    level: str = Field(..., examples=["info"])
    title: str = Field(..., examples=["Async data refresh"])
    message: str = Field(..., examples=["7 source calls completed through FastAPI fanout in 842 ms."])


EventLevel = Literal["info", "success", "warning", "danger"]


class OperatorEventCreate(ApiModel):
    level: EventLevel = Field(default="info", examples=["warning"])
    title: str = Field(..., min_length=1, max_length=120, examples=["Manual reserve watch"])
    message: str = Field(..., min_length=1, max_length=500, examples=["Operator marked North load-zone reserve as watchlisted."])
    source: str = Field(default="Operator", min_length=1, max_length=80, examples=["Control room"])
    acknowledged: bool = Field(default=False)


class OperatorEventUpdate(ApiModel):
    level: EventLevel | None = Field(default=None, examples=["success"])
    title: str | None = Field(default=None, min_length=1, max_length=120, examples=["Manual reserve watch acknowledged"])
    message: str | None = Field(default=None, min_length=1, max_length=500)
    source: str | None = Field(default=None, min_length=1, max_length=80)
    acknowledged: bool | None = Field(default=None, examples=[True])


class OperatorEvent(EventRecord):
    id: str = Field(..., examples=["evt-7a64be10ce"])
    timestamp: str = Field(..., examples=["2026-05-13T15:04:21+00:00"])
    updated_at: str = Field(..., examples=["2026-05-13T15:04:21+00:00"])
    source: str = Field(default="Operator", examples=["Control room"])
    acknowledged: bool = Field(default=False)
    acknowledged_at: str | None = Field(default=None)


class OperatorEventListResponse(ApiModel):
    count: int = Field(..., ge=0)
    events: list[OperatorEvent] = Field(default_factory=list)


class OperatorEventDeleteResponse(ApiModel):
    deleted: bool = Field(default=True)
    event: OperatorEvent


class FanoutMeta(ApiModel):
    strategy: str = Field(..., examples=["asyncio.gather"])
    duration_ms: float = Field(..., ge=0, examples=[842.4])
    source_latency_ms: dict[str, float] = Field(
        default_factory=dict,
        examples=[{"ercot": 580.2, "eia": 246.8, "noaa": 112.3}],
    )
    sources: int = Field(..., ge=0, examples=[7])
    live: bool = Field(..., examples=[True])


class DashboardMetrics(ApiModel):
    stress_index: float = Field(..., ge=0, le=100, examples=[41.7])
    balance_mw: float = Field(..., examples=[7800.4])
    renewable_share_pct: float = Field(..., ge=0, examples=[31.6])


class LoadZoneSnapshot(ApiModel):
    name: str = Field(..., examples=["North"])
    settlement_point: str | None = Field(default=None, examples=["LZ_NORTH"])
    load_mw: float = Field(..., ge=0, examples=[18520.4])
    generation_mw: float = Field(..., ge=0, examples=[21310.8])
    stress: float = Field(..., ge=0, le=100, examples=[54.2])
    price_usd_mwh: float | None = Field(default=None, examples=[28.42])


class ErcotSnapshot(ApiModel):
    load_mw: float = Field(..., ge=0, examples=[64150.0])
    generation_mw: float = Field(..., ge=0, examples=[71980.0])
    wind_mw: float = Field(..., ge=0, examples=[12840.0])
    solar_mw: float = Field(..., ge=0, examples=[7420.0])
    price_proxy: float | None = Field(default=None, examples=[34.18])
    price_settlement_point: str | None = Field(default=None, examples=["HB_NORTH"])
    price_label: str | None = Field(default=None, examples=["North Hub RT LMP"])
    reserve_margin_pct: float = Field(..., examples=[12.2])
    load_zones: list[LoadZoneSnapshot] = Field(default_factory=list)
    regions: list[LoadZoneSnapshot] = Field(default_factory=list)
    price_series: dict[str, Any] = Field(default_factory=dict)
    trends: dict[str, list[TimeSeriesPoint]] = Field(default_factory=dict)
    status: SourceStatus
    price_status: SourceStatus | None = None


class EiaSnapshot(ApiModel):
    fuel_mix: dict[str, float] = Field(
        default_factory=dict,
        examples=[{"Natural gas": 46.5, "Wind": 24.0, "Coal": 12.4}],
    )
    latest_period: str = Field(..., examples=["2026-05-13T15"])
    total_mwh: float = Field(..., ge=0, examples=[64150.0])
    status: SourceStatus


class AirportWeather(ApiModel):
    airport: str = Field(..., examples=["DFW"])
    station_id: str = Field(..., examples=["KDFW"])
    name: str = Field(..., examples=["Dallas/Fort Worth"])
    observed_at: str = Field(..., examples=["2026-05-13T15:51:00+00:00"])
    observed_date: str = Field(..., examples=["2026-05-13"])
    temperature_f: float | None = Field(default=None, examples=[86.0])
    daily_high_f: float | None = Field(default=None, examples=[95.0])
    daily_low_f: float | None = Field(default=None, examples=[68.0])
    wind_speed_mph: float | None = Field(default=None, examples=[10.0])
    precipitation_in: float | None = Field(default=None, examples=[0.1])
    source: str = Field(..., examples=["live"])


class NoaaSnapshot(ApiModel):
    timestamp: str = Field(..., examples=["2026-05-13T15:55:00+00:00"])
    temperature_f: float = Field(..., examples=[86.0])
    daily_high_f: float = Field(..., examples=[95.0])
    daily_low_f: float = Field(..., examples=[68.0])
    wind_speed_mph: float = Field(..., examples=[10.0])
    precipitation_in: float = Field(..., examples=[0.1])
    observed_date: str = Field(default="", examples=["2026-05-13"])
    observed_at: str = Field(default="", examples=["2026-05-13T15:51:00+00:00"])
    airport_count: int = Field(default=0, ge=0)
    airports: list[AirportWeather] = Field(default_factory=list)
    station: str = Field(..., examples=["Texas current station average"])
    stream_url: str = Field(default="/ws/weather")
    status: SourceStatus


class DashboardSnapshot(ApiModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {
                    "timestamp": "2026-05-13T15:55:00+00:00",
                    "system_status": "Normal",
                    "metrics": {
                        "stress_index": 41.7,
                        "balance_mw": 7800.4,
                        "renewable_share_pct": 31.6,
                    },
                    "fanout": {
                        "strategy": "asyncio.gather",
                        "duration_ms": 842.4,
                        "source_latency_ms": {"ercot": 580.2, "eia": 246.8, "noaa": 112.3},
                        "sources": 7,
                        "live": True,
                    },
                }
            ]
        },
    )

    timestamp: str
    system_status: str = Field(..., examples=["Normal"])
    ercot: ErcotSnapshot
    eia: EiaSnapshot
    noaa: NoaaSnapshot
    supply_demand: dict[str, Any] = Field(default_factory=dict)
    ercot_dashboards: dict[str, Any] = Field(default_factory=dict)
    eia_gas: dict[str, Any] = Field(default_factory=dict)
    climate: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    metrics: DashboardMetrics
    trends: dict[str, list[TimeSeriesPoint]] = Field(default_factory=dict)
    events: list[EventRecord] = Field(default_factory=list)
    fanout: FanoutMeta
    source_status: dict[str, SourceStatus] = Field(default_factory=dict)


class SourceBundle(ApiModel):
    name: str = Field(..., examples=["grid"])
    timestamp: str
    duration_ms: float = Field(..., ge=0)
    latency_ms: dict[str, float] = Field(default_factory=dict)
    source_count: int = Field(..., ge=0)
    status: SourceStatus
    refresh_policy: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class FeedEndpoint(ApiModel):
    name: str = Field(..., examples=["ercot-prc"])
    provider: str = Field(..., examples=["ERCOT"])
    title: str = Field(..., examples=["Physical Responsive Capability"])
    local_url: str = Field(..., examples=["/api/ercot/public-dashboards/prc"])
    upstream_url: str = Field(default="", examples=["https://www.ercot.com/api/1/services/read/dashboards/daily-prc.json"])
    description: str = Field(default="")


class FeedCatalogResponse(ApiModel):
    feeds: list[FeedEndpoint] = Field(default_factory=list)


class FeedSnapshotResponse(ApiModel):
    timestamp: str
    name: str = Field(..., examples=["ercot-prc"])
    provider: str = Field(..., examples=["ERCOT"])
    title: str = Field(..., examples=["Physical Responsive Capability"])
    source_url: str = Field(default="")
    status: SourceStatus
    data: dict[str, Any] = Field(default_factory=dict)


class ErcotReportSummary(ApiModel):
    name: str = Field(..., examples=["hb-north-lmp"])
    title: str = Field(..., examples=["North Hub RT LMP"])
    ercot_url: str
    local_url: str
    default_params: dict[str, Any] = Field(default_factory=dict)


class ErcotReportsResponse(ApiModel):
    reports: list[ErcotReportSummary] = Field(default_factory=list)


class ErcotDebugResponse(ApiModel):
    timestamp: str
    environment: dict[str, Any] = Field(default_factory=dict)
    auth: dict[str, Any] = Field(default_factory=dict)
    reports: list[dict[str, Any]] = Field(default_factory=list)
    documentation: dict[str, str] = Field(default_factory=dict)


class ErcotReportResponse(ApiModel):
    timestamp: str
    name: str
    title: str
    ercot_url: str
    params: dict[str, Any] = Field(default_factory=dict)
    row_count: int = Field(..., ge=0)
    sample_keys: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
    report: dict[str, Any] = Field(default_factory=dict)
    cache_status: dict[str, Any] | None = None


class LoadZoneLmp(ApiModel):
    name: str = Field(..., examples=["North"])
    settlement_point: str = Field(..., examples=["LZ_NORTH"])
    price_usd_mwh: float | None = Field(default=None, examples=[28.42])
    timestamp: str = Field(default="")
    status: str = Field(..., examples=["live"])
    diagnostic: dict[str, Any] = Field(default_factory=dict)


class LoadZoneLmpResponse(ApiModel):
    timestamp: str
    complete: bool
    status: SourceStatus
    zones: list[LoadZoneLmp] = Field(default_factory=list)


class SupplyDemandResponse(ApiModel):
    timestamp: str | None = None
    last_updated: str | None = None
    latest: dict[str, Any] = Field(default_factory=dict)
    current_day: list[dict[str, Any]] = Field(default_factory=list)
    six_day: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    status: SourceStatus


class ErcotPublicDashboardsResponse(ApiModel):
    timestamp: str
    prc: dict[str, Any] = Field(default_factory=dict)
    fuel_mix: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    combined_renewables: dict[str, Any] = Field(default_factory=dict)
    dc_ties: dict[str, Any] = Field(default_factory=dict)
    outages: dict[str, Any] = Field(default_factory=dict)
    ancillary: dict[str, Any] = Field(default_factory=dict)
    status: SourceStatus


class EiaNaturalGasResponse(ApiModel):
    timestamp: str
    storage: dict[str, Any] = Field(default_factory=dict)
    balance: dict[str, Any] = Field(default_factory=dict)
    steo: dict[str, Any] = Field(default_factory=dict)
    wells: dict[str, Any] = Field(default_factory=dict)
    status: SourceStatus


class DegreeDayForecastResponse(ApiModel):
    timestamp: str
    issued: str
    region: str = Field(..., examples=["TEXAS"])
    states: list[str] = Field(default_factory=list, examples=[["TX"]])
    source_url: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    regions: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    status: SourceStatus


class StreamChannel(ApiModel):
    name: str = Field(..., examples=["ercot"])
    url: str = Field(..., examples=["/ws/ercot?interval=30"])
    source: str = Field(..., examples=["ERCOT"])
    description: str
    query_parameters: dict[str, Any] = Field(default_factory=dict)


class StreamCatalogResponse(ApiModel):
    channels: list[StreamChannel] = Field(default_factory=list)

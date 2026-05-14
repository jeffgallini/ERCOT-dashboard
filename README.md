# ERCOT Grid Pulse

Demo dashboard for Dash 4.2 release-candidate FastAPI backend support.

The app uses Dash with `backend="fastapi"` so the dashboard and `/api/*`
endpoints run in one ASGI process. The service layer fans out to ERCOT, EIA,
and NOAA concurrently, normalizes the responses, and falls back to deterministic
demo data when credentials or public services are unavailable.

## Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m ercot_dashboard.app
```

Open:

- Dashboard: http://127.0.0.1:8050/dash/
- FastAPI API console: http://127.0.0.1:8050/docs
- Aggregated API: http://127.0.0.1:8050/api/dashboard
- ERCOT auth/debug API: http://127.0.0.1:8050/api/ercot/debug
- ERCOT configured reports: http://127.0.0.1:8050/api/ercot/reports
- ERCOT HB_NORTH LMP API: http://127.0.0.1:8050/api/ercot/hb-north-lmp
- ERCOT HB_NORTH DA LMP API: http://127.0.0.1:8050/api/ercot/hb-north-da-lmp
- ERCOT Supply/Demand API: http://127.0.0.1:8050/api/ercot/supply-demand
- ERCOT public dashboard replicas: http://127.0.0.1:8050/api/ercot/public-dashboards
- EIA natural gas storage/STEO: http://127.0.0.1:8050/api/eia/natural-gas
- Operator events API: http://127.0.0.1:8050/api/events
- ERCOT websocket: ws://127.0.0.1:8050/ws/ercot?interval=30
- Airport weather API: http://127.0.0.1:8050/api/weather/airports
- CPC degree-day forecast API: http://127.0.0.1:8050/api/weather/degree-days
- Airport weather websocket: ws://127.0.0.1:8050/ws/weather?interval=60

## API Console

The `/docs` route is a customized Swagger UI served by the same FastAPI app
that Dash mounts with `backend="fastapi"`. The OpenAPI schema uses Pydantic
models for the normalized dashboard state, source bundles, ERCOT report rows,
NOAA weather snapshots, EIA natural gas data, and scenario request bodies.

Swagger sections are grouped by demo source:

- `Operations`: health, aggregate dashboard state, and async source bundles
- `ERCOT`: grid reports, public dashboard replicas, and diagnostics
- `ERCOT Market`: real-time and day-ahead LMP endpoints
- `EIA`: natural gas storage and outlook data
- `Weather`: NOAA/NWS observations and CPC degree-day outlooks
- `Events`: in-memory manual operator events
- `Scenarios`: heatwave, wind ramp, and concurrent preview transforms
- `Streams`: WebSocket channel catalog for routes that OpenAPI cannot model directly

## Operator Event API

The demo includes a small in-memory event store so POST, PUT, and DELETE routes
have visible behavior without adding a database. Created events appear in
`/api/events` and are folded into the next `/api/dashboard` snapshot, so the Dash
event feed can display them after refresh.

```powershell
$event = Invoke-RestMethod -Method Post http://127.0.0.1:8050/api/events -ContentType "application/json" -Body '{"level":"warning","title":"Manual reserve watch","message":"North zone reserves under operator review.","source":"Control room"}'
Invoke-RestMethod http://127.0.0.1:8050/api/events
Invoke-RestMethod -Method Put "http://127.0.0.1:8050/api/events/$($event.id)" -ContentType "application/json" -Body '{"level":"success","title":"Reserve watch acknowledged","acknowledged":true}'
Invoke-RestMethod -Method Delete "http://127.0.0.1:8050/api/events/$($event.id)"
```

## Optional Live Data

Create a `.env` or set environment variables before starting the app:

```bash
set EIA_API_KEY=your-eia-key
set "NWS_USER_AGENT=ERCOT Grid Pulse Demo (local development)"
set NOAA_WEATHER_STREAM_INTERVAL_SECONDS=60
set ERCOT_API_SUBSCRIPTION_KEY=your-ercot-subscription-key
set ERCOT_API_SECONDARY_SUBSCRIPTION_KEY=your-price-only-ercot-subscription-key
set ERCOT_STREAM_INTERVAL_SECONDS=30
set ERCOT_PUBLIC_API_REQUESTS_PER_MINUTE=30
set ERCOT_PUBLIC_API_RATE_CUSHION_MS=150
set ERCOT_CACHE_SECONDS=60
set ERCOT_REPORT_CACHE_SECONDS=60
set ERCOT_PRICE_CACHE_SECONDS=180
set ERCOT_PRICE_STALE_SECONDS=1800
set ERCOT_GRID_SOURCE_CACHE_SECONDS=60
set ERCOT_MARKET_SOURCE_CACHE_SECONDS=60
set ERCOT_DASHBOARDS_SOURCE_CACHE_SECONDS=60
set ERCOT_RT_LMP_POINTS=36
set ERCOT_RT_LMP_REFRESH_SECONDS=300
set ERCOT_RT_LMP_INITIAL_POINTS=300
set ERCOT_RT_LMP_UPDATE_POINTS=12
set ERCOT_RT_LMP_MAX_POINTS=288
set ERCOT_API_USERNAME=your-ercot-login-email
set ERCOT_API_PASSWORD=your-ercot-password
```

ERCOT Public API requests require both `Ocp-Apim-Subscription-Key` and
`Authorization: Bearer <token>`. The app mints and caches the hourly token from
`ERCOT_API_USERNAME` and `ERCOT_API_PASSWORD` by POSTing to ERCOT B2C with query
parameters. ERCOT returns both `access_token` and `id_token`; the app uses
`access_token` for the bearer header. Price reports use
`ERCOT_API_SECONDARY_SUBSCRIPTION_KEY` when it is set, and fall back to
`ERCOT_API_SUBSCRIPTION_KEY` otherwise. You can also provide a current token
directly with `ERCOT_API_ID_TOKEN`. EIA requires an API key. NOAA/NWS current
observations do not require an API key, but NWS asks clients to send a
`User-Agent`; set `NWS_USER_AGENT` to identify your local app. The demo treats all
external APIs as unreliable by design and keeps the UI live with normalized
fallback data.

## ERCOT Debugging

The ERCOT Public API is REST over HTTPS. This app exposes local FastAPI endpoints
that call ERCOT and normalize the results:

```powershell
Invoke-RestMethod http://127.0.0.1:8050/api/ercot/debug
Invoke-RestMethod "http://127.0.0.1:8050/api/ercot/debug?check_reports=true"
Invoke-RestMethod http://127.0.0.1:8050/api/ercot/reports
Invoke-RestMethod "http://127.0.0.1:8050/api/ercot/report/system-load?size=3"
Invoke-RestMethod "http://127.0.0.1:8050/api/ercot/rt-lmp?start_time=2026-05-13T07:00:00&end_time=2026-05-13T08:00:00&settlement_point=HB_NORTH"
Invoke-RestMethod "http://127.0.0.1:8050/api/ercot/report/hb-north-lmp?start_time=2026-05-13T07:00:00&end_time=2026-05-13T08:00:00&settlement_point=HB_NORTH&size=12"
Invoke-RestMethod "http://127.0.0.1:8050/api/ercot/report/hb-north-da-lmp?size=24"
```

Configured ERCOT report names:

- `system-load`: `/np3-910-er/2d_agg_load_summary`
- `system-generation`: `/np3-910-er/2d_agg_gen_summary`
- `wind-5min`: `/np4-733-cd/wpp_actual_5min_avg_values`
- `solar-5min`: `/np4-738-cd/spp_actual_5min_avg_values`
- `hb-north-lmp`: `/np6-788-cd/lmp_node_zone_hub?settlementPoint=HB_NORTH`
- `hb-north-da-lmp`: `/np4-190-cd/dam_stlmnt_pnt_prices?settlementPoint=HB_NORTH`

ERCOT does not provide a native websocket for these Public Data API artifacts.
The local websocket polls the REST API and streams normalized JSON:

```text
ws://127.0.0.1:8050/ws/ercot?interval=30
ws://127.0.0.1:8050/ws/ercot?report=hb-north-lmp&interval=30&size=3
```

The dashboard keeps ERCOT traffic server-side. Dash callbacks call local
FastAPI routes through ASGI, and those routes serve in-memory source bundles to
all connected clients. The server caches the grid, market-price, and public
dashboard bundles for `ERCOT_GRID_SOURCE_CACHE_SECONDS`,
`ERCOT_MARKET_SOURCE_CACHE_SECONDS`, and
`ERCOT_DASHBOARDS_SOURCE_CACHE_SECONDS`, so multiple browser tabs do not create
multiple upstream ERCOT refreshes.

The ERCOT Public Data API is guarded by a process-wide request gate set by
`ERCOT_PUBLIC_API_REQUESTS_PER_MINUTE` and
`ERCOT_PUBLIC_API_RATE_CUSHION_MS`. The default spaces requests by a little more
than two seconds, matching ERCOT's 30-requests-per-minute limit. The dashboard
also caches the normalized ERCOT snapshot for `ERCOT_CACHE_SECONDS` and caches
individual ERCOT report payloads for `ERCOT_REPORT_CACHE_SECONDS`. Price reports
use the longer `ERCOT_PRICE_CACHE_SECONDS` and may reuse real cached price
payloads for up to `ERCOT_PRICE_STALE_SECONDS` after an upstream rate-limit
response. The RT LMP chart keeps its own current-day cache:
`ERCOT_RT_LMP_INITIAL_POINTS` seeds the current day, then the app waits
`ERCOT_RT_LMP_REFRESH_SECONDS` before querying only the latest
`ERCOT_RT_LMP_UPDATE_POINTS`. `ERCOT_RT_LMP_MAX_POINTS` caps the retained
5-minute points.

The current-day Supply and Demand panel uses ERCOT's public dashboard JSON at
`https://www.ercot.com/api/1/services/read/dashboards/supply-demand.json`.
That feed provides 5-minute current-day demand, committed capacity, forecast
flags, and available-capacity values, so it does not require the ERCOT Public
Data API credentials used by the report endpoints.

The ERCOT replica section also consumes public dashboard JSON feeds that do not
require ERCOT Public Data API credentials:

- `daily-prc.json`: physical responsive capability and grid condition state
- `fuel-mix.json`: five-minute generation mix by fuel type
- `energy-storage-resources.json`: battery charging and discharging
- `generation-outages.json`: planned and unplanned generation outages
- `ancillary-service-capacity-monitor.json`: ancillary service capability and awards

The natural gas panel uses EIA API v2 with `EIA_API_KEY`:

- Weekly storage: Lower 48 and South Central working gas in underground storage
- STEO monthly outlook: Henry Hub spot price and South Central working inventory

The climate panel parses NOAA CPC's monthly degree-day text forecast at
`https://www.cpc.ncep.noaa.gov/pacdir/DDdir/ddforecast.txt`. The default API
region is the Texas-only block, `TEXAS`. Use
`/api/weather/degree-days?region=TEXAS` to request it directly, or pass another
CPC region or state header from the text file. The dashboard plots monthly mean
HDD upward, monthly mean CDD downward, and a net climate position line calculated as
`HDD mean - CDD mean`.

NOAA/NWS station observations are current weather observations, not a native
sub-second push feed. The app streams a normalized airport weather snapshot over
WebSocket by polling `api.weather.gov` latest-observation endpoints for KDFW,
KIAH, KAUS, KLBB, KSAT, and KELP, then sending a fresh JSON payload on each
interval. NWS notes that observations can lag by about 20 minutes while upstream
MADIS data is quality-controlled.

## Architecture

- `ercot_dashboard.app`: Dash app factory and FastAPI app exposure.
- `ercot_dashboard.api`: `/api/dashboard`, `/api/events`, `/api/ercot/*`, `/api/eia/natural-gas`, `/api/weather/*`, `/ws/ercot`, `/ws/weather`, and scenario routes.
- `ercot_dashboard.services`: async external clients, normalization, and scenario transforms.
- `ercot_dashboard.layout`: dash-mantine-components layout.
- `ercot_dashboard.callbacks`: async Dash callbacks that call FastAPI endpoints through ASGI.

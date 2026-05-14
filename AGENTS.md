# AGENTS.md

## Project: ERCOT Grid Pulse (Demo System)

A lightweight, real-time energy intelligence dashboard built with:

- Dash 4.2 (React frontend framework)
- FastAPI (ASGI backend orchestration layer)
- dash-mantine-components (UI system)
- Public energy + weather data sources (ERCOT, EIA, NOAA)

The goal is to demonstrate modern reactive analytics architecture:
NOT production-grade energy modeling.

---

# 1. System Architecture

## High-Level Design

Frontend (Dash v4.2.0rc3)
- Reactive UI layer built with Plotly Dash
- Uses async-capable callbacks (Dash 3.1+ pattern)
- Supports dynamic layouts and partial updates
- Built with dash-mantine-components for UI primitives

Backend (FastAPI)
- ASGI-based async orchestration layer
- Handles all external API calls and scenario simulations
- Acts as a thin “data + computation API layer”
- No business logic in Dash callbacks

Data Sources (Public APIs)
- ERCOT grid and market data
- EIA energy data API v2.1
- NOAA weather data services

---

# 2. Dash 4.2 Behavior Guidelines

## Key Framework Capabilities (IMPORTANT)

This project assumes Dash v4.2.0rc3+ behavior:

### 1. Async/Await Native Callback Support
- Callbacks MAY be async functions
- Use `async def` when calling external APIs
- Use `asyncio.gather()` for parallel requests

Reference pattern:
- Fetch ERCOT + EIA + NOAA concurrently
- Avoid sequential blocking calls

---

### 2. FastAPI Backend Integration
Dash can run on top of FastAPI via ASGI server configuration.

- FastAPI is the primary backend
- Dash is mounted as the frontend app
- API endpoints coexist with Dash app routes

Pattern:
- `/api/*` → FastAPI endpoints
- `/dash/*` → Dash UI

---

### 3. Callback Execution Model (Dash 4.x)
- Callbacks execute on:
  - initial page load
  - user interactions
  - programmatic updates
- Multiple callbacks may execute concurrently depending on server setup
- Avoid relying on strict execution order

---

# 3. FastAPI Backend Guidelines

## Role Definition

FastAPI is responsible for:

- Aggregating external data sources
- Running scenario simulations
- Providing clean JSON APIs for Dash
- Handling async workloads

NOT responsible for:
- UI rendering
- stateful frontend logic
- persistent storage (optional for demo only)

---

## Required API Endpoints

### GET /api/dashboard
Aggregates all live data sources:

- ERCOT load / generation
- EIA fuel mix snapshot
- NOAA weather conditions

Must:
- use asyncio.gather()
- return normalized JSON object

---

### POST /api/scenario/heatwave
Simulates demand shock scenario:
- increases load
- adjusts stress index
- returns updated state

---

### POST /api/scenario/wind
Simulates renewable fluctuation:
- modifies wind generation
- updates system balance metrics

---

## FastAPI Implementation Rules

- MUST use ASGI async endpoints
- MUST avoid blocking I/O
- MUST isolate external API logic into service layer
- MUST treat all external APIs as unreliable

---

# 4. dash-mantine-components (DMC) UI System

## Role

dash-mantine-components is the primary UI framework:

- Provides layout primitives
- Provides KPI cards, grids, modals, buttons
- Ensures consistent “control room” aesthetic

---

## Design Principles

### Use Mantine for:
- layout (Grid, Stack, Flex)
- KPI cards
- buttons (scenario triggers)
- notifications (system alerts)
- modals (analysis views)

### Avoid:
- mixing multiple UI libraries
- raw HTML components unless necessary
- custom CSS-heavy components

---

## UI Style Guidelines

Theme:
- dark “operations center” aesthetic
- minimal but information-dense
- high contrast status indicators

Color semantics:
- Green → normal conditions
- Yellow → elevated stress
- Red → system stress / alerts

---

## Layout Structure

### 1. Header (Mantine AppShell Header)
- System status
- Last update timestamp
- FastAPI health indicator

---

### 2. KPI Row (Mantine Grid + Cards)
- ERCOT load
- Real-time price proxy
- wind generation
- solar generation
- computed stress index

---

### 3. Main Map Panel
- Plotly Mapbox visualization
- ERCOT regions
- weather overlay
- stress heatmap

---

### 4. Event Feed (Mantine ScrollArea)
- simulated + real updates
- timestamped system events
- streaming-style UI updates

---

### 5. Scenario Controls (Mantine Stack)
Buttons:
- Heatwave simulation
- Wind ramp simulation
- Full system refresh

---

# 5. Data Sources

## ERCOT (Primary Grid Data)
https://github.com/ercot/api-specs

Used for:
- load
- generation
- pricing proxies
- system status

---

## EIA API v2.1
https://www.eia.gov/opendata/documentation/APIv2.1.0.pdf

Used for:
- energy mix
- fuel breakdown
- historical trends

---

## NOAA Weather Data
https://www.ncdc.noaa.gov/cdo-web/webservices/v2

Used for:
- temperature
- wind speed
- weather-driven demand simulation

---

## Data Handling Rules

- Normalize all responses into simple dictionaries
- Never expose raw API payloads to frontend
- Apply lightweight transformations only
- Cache responses only within request scope (no persistence required)

---

# 6. Scenario Engine (Core Demo Feature)

Scenarios are lightweight transformations:

## Heatwave Scenario
- Increase demand based on temperature
- Raise system stress index
- Slight renewable efficiency reduction (optional)

---

## Wind Ramp Scenario
- Increase wind generation
- Reduce system stress
- Adjust price proxy downward

---

## System Refresh Scenario
- Parallel API refresh (ERCOT + EIA + NOAA)
- Async fanout required
- UI updates independently per component

---

# 7. Async Execution Rules

## REQUIRED PATTERN

Always prefer:

```python
await asyncio.gather(...)
```

for:
- ERCOT API calls
- EIA API calls
- NOAA API calls

## Forbidden Patterns
- sequential external API calls
- blocking sleep in callbacks
- mixing sync + async I/O in same path

# 8. UI Responsiveness Rules
- UI must never freeze during API calls
- partial updates are preferred over full refresh
- event feed should update independently of KPIs
- map updates should be decoupled from table updates

# 9. What This Project Is NOT

This is intentionally NOT:

a trading system
a forecasting engine
a nodal pricing model
a production monitoring system
a database-driven platform

It is a:

reactive analytics demonstration system

# 10. Primary Demo Objective

This project demonstrates:

- FastAPI
- async orchestration
- API-first architecture
- external data aggregation layer
- Dash 4.2
- async callbacks
- reactive UI updates
- dynamic layout behavior
- dash-mantine-components
- modern UI system
- structured dashboard layout
- fast component composition

# 11. Success Criteria

The demo is successful if:

multiple APIs load concurrently
UI updates feel live (not manually refreshed)
scenario buttons visibly change system state
map + KPIs + feed update independently
system feels like a real operational dashboard

# 12. Key Mental Model

FastAPI = brain (data + computation)
Dash = eyes (reactive UI)
Mantine = skeleton (UI structure)
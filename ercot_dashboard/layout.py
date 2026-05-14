from __future__ import annotations

from dash import dcc, html
from dash_iconify import DashIconify
import dash_mantine_components as dmc


THEME = {
    "fontFamily": "Inter, Segoe UI, sans-serif",
    "primaryColor": "cyan",
    "defaultRadius": "sm",
    "headings": {"fontFamily": "Inter, Segoe UI, sans-serif"},
    "colors": {
        "gridcyan": [
            "#e6fbff",
            "#c8f3fb",
            "#91e5f3",
            "#58d5eb",
            "#2cc9e4",
            "#16b7d1",
            "#0b91a8",
            "#096f82",
            "#085a69",
            "#063d49",
        ]
    },
}

PROCESS_HELP_TOPICS = [
    {
        "title": "API endpoints",
        "summary": "FastAPI routes normalize upstream ERCOT, EIA, NOAA, event, stream, and scenario work before Dash consumes it.",
        "icon": "tabler:api",
        "color": "cyan",
        "details": [
            "GET /api/dashboard returns the full dashboard snapshot.",
            "GET /api/source/* feeds the independent async stores.",
            "POST /api/scenario/* applies scenario transforms over the current state.",
        ],
        "code": ["api.py -> register_api_routes", "services/dashboard.py -> get_dashboard_snapshot"],
    },
    {
        "title": "Async callbacks",
        "summary": "Dash callbacks can be async def functions, so UI refreshes await FastAPI/httpx work without blocking the whole app.",
        "icon": "tabler:arrows-split",
        "color": "green",
        "details": [
            "Source callbacks await /api/source/* endpoints.",
            "Scenario preview posts to FastAPI from a websocket callback.",
            "Service fanout uses asyncio.gather for concurrent upstream calls.",
        ],
        "code": ["callbacks.py -> refresh_*_source", "services/dashboard.py -> _source_bundle"],
    },
    {
        "title": "WebSockets",
        "summary": "The demo shows both raw FastAPI websocket routes and Dash websocket callback transport for live side updates.",
        "icon": "tabler:plug-connected",
        "color": "violet",
        "details": [
            "Dash callbacks use websocket=True for telemetry and event feed updates.",
            "FastAPI exposes /ws/ercot and /ws/weather stream routes.",
            "GET /api/streams documents websocket channels because OpenAPI does not list them directly.",
        ],
        "code": ["callbacks.py -> update_transport_panel", "api.py -> @server.websocket"],
    },
    {
        "title": "FastAPI backend",
        "summary": "Dash 4.2 mounts on one ASGI FastAPI app so UI routes, JSON APIs, docs, and websocket routes share the same server.",
        "icon": "tabler:server-2",
        "color": "yellow",
        "details": [
            "dash.Dash(..., backend=\"fastapi\") creates the ASGI backend.",
            "register_api_routes(app.server) attaches JSON and websocket routes.",
            "configure_openapi_docs(app.server) replaces the default Swagger shell.",
        ],
        "code": ["app.py -> create_app", "docs.py -> configure_openapi_docs"],
    },
]

TIP_TOPICS = [
    {
        "title": "Add FastAPI as the backend",
        "icon": "tabler:layout-dashboard",
        "color": "cyan",
        "body": "Create Dash with the FastAPI backend, then register API routes on app.server before assigning layout and callbacks.",
        "code": [
            "app = dash.Dash(__name__, backend=\"fastapi\", requests_pathname_prefix=\"/dash/\")",
            "register_api_routes(app.server)",
        ],
    },
    {
        "title": "Theme Swagger UI in code",
        "icon": "tabler:palette",
        "color": "violet",
        "body": "Remove the default /docs route, return get_swagger_ui_html, and point swagger_css_url at a FastAPI-served CSS endpoint.",
        "code": [
            "_remove_route(server, \"/docs\")",
            "get_swagger_ui_html(swagger_css_url=\"/api/docs/swagger-theme.css\")",
        ],
    },
    {
        "title": "Set up websockets where they help",
        "icon": "tabler:wave-sine",
        "color": "green",
        "body": "Use FastAPI websocket routes for raw streams and Dash websocket callbacks for component updates that should avoid request polling.",
        "code": [
            "@server.websocket(\"/ws/ercot\")",
            "@app.callback(..., websocket=True)",
        ],
    },
]


def build_layout() -> dmc.MantineProvider:
    shell = dmc.AppShell(
        [
            dmc.AppShellHeader(_header(), className="app-header", withBorder=False),
            dmc.AppShellMain(
                [
                    dcc.Store(id="dashboard-store"),
                    dcc.Store(id="grid-store"),
                    dcc.Store(id="ercot-dashboards-store"),
                    dcc.Store(id="weather-store"),
                    dcc.Store(id="energy-store"),
                    dcc.Store(id="climate-store"),
                    dcc.Store(id="market-store"),
                    dcc.Store(id="scenario-control-store", data={}),
                    dcc.Store(id="scenario-preview-store"),
                    dcc.Store(id="map-price-store"),
                    dcc.Store(id="event-log-store", data=[]),
                    dcc.Interval(id="refresh-interval", interval=20_000, n_intervals=0),
                    dcc.Interval(id="grid-refresh-interval", interval=20_000, n_intervals=0),
                    dcc.Interval(id="ercot-dashboards-refresh-interval", interval=30_000, n_intervals=0),
                    dcc.Interval(id="weather-refresh-interval", interval=60_000, n_intervals=0),
                    dcc.Interval(id="energy-refresh-interval", interval=300_000, n_intervals=0),
                    dcc.Interval(id="climate-refresh-interval", interval=900_000, n_intervals=0),
                    dcc.Interval(id="map-price-retry-interval", interval=10_000, n_intervals=0),
                    dcc.Interval(id="telemetry-interval", interval=5_000, n_intervals=0),
                    dmc.Stack(
                        [
                            _command_strip(),
                            html.Div(id="kpi-row"),
                            _supply_demand_panel(),
                            _ercot_dashboard_gallery(),
                            _energy_climate_panel(),
                            dmc.Grid(
                                [
                                    dmc.GridCol(
                                        dmc.Stack([_map_panel(), _system_panel()], gap="md"),
                                        span={"base": 12, "xl": 8},
                                    ),
                                    dmc.GridCol(_side_panel(), span={"base": 12, "lg": 4}),
                                ],
                                gutter="md",
                            ),
                        ],
                        gap="md",
                        className="main-content",
                    ),
                ],
                className="main-shell",
            ),
        ],
        header={"height": 88},
        padding={"base": "sm", "md": "md"},
        className="app-shell",
        withBorder=False,
    )

    return dmc.MantineProvider(shell, forceColorScheme="dark", theme=THEME)


def _header() -> dmc.Group:
    return dmc.Group(
        [
            dmc.Group(
                [
                    dmc.ThemeIcon(
                        DashIconify(icon="tabler:activity-heartbeat", width=26),
                        size=46,
                        radius="sm",
                        color="cyan",
                        variant="light",
                        className="brand-mark",
                    ),
                    dmc.Stack(
                        [
                            dmc.Title("ERCOT Grid Pulse", order=2, className="app-title"),
                            dmc.Anchor("Built by Jeff Gallini", href= "https://www.linkedin.com/in/jeff-gallini/", size="xs", c="dimmed", visibleFrom="sm"),
                        ],
                        gap=0,
                    ),
                ],
                gap="sm",
                wrap="nowrap",
                className="brand-lockup",
            ),
            dmc.Group(
                [
                    dmc.Badge("FastAPI", id="api-health", color="gray", variant="light", size="lg", visibleFrom="md"),
                    dmc.Badge("Waiting for data", id="system-status", color="gray", variant="filled", size="lg"),
                    dmc.Text(id="last-update", size="sm", c="dimmed", visibleFrom="sm", className="last-update"),
                    dmc.Anchor(
                        dmc.Button(
                            "API Console",
                            leftSection=DashIconify(icon="tabler:code", width=17),
                            rightSection=DashIconify(icon="tabler:external-link", width=15),
                            size="sm",
                            color="cyan",
                            variant="filled",
                            className="api-nav-button",
                        ),
                        href="/docs",
                        target="_blank",
                        underline="never",
                    ),
                    dmc.Tooltip(
                        dmc.Anchor(
                            dmc.ActionIcon(
                                DashIconify(icon="tabler:braces", width=19),
                                color="gray",
                                variant="subtle",
                                size="lg",
                            ),
                            href="/api/dashboard",
                            target="_blank",
                            underline="never",
                        ),
                        label="Open raw dashboard JSON",
                        position="bottom",
                        withArrow=True,
                    ),
                ],
                gap="sm",
                wrap="nowrap",
                className="header-actions",
            ),
        ],
        justify="space-between",
        h="100%",
        px="lg",
        wrap="nowrap",
        className="header-inner",
    )


def _command_strip() -> dmc.Box:
    return dmc.Box(
        [
            dmc.Group(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="tabler:radar", width=20),
                            dmc.Text("Operations Fabric", fw=800, size="sm"),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        [
                            dmc.Badge("20s cadence", color="cyan", variant="light"),
                            dmc.Badge("ASGI", color="violet", variant="light"),
                            dmc.Badge("Scenario-ready", color="green", variant="light"),
                        ],
                        gap="xs",
                        visibleFrom="sm",
                    ),
                ],
                justify="space-between",
                mb="sm",
                className="strip-header",
            ),
            dmc.SimpleGrid(
                id="source-status-grid",
                cols={"base": 1, "sm": 3},
                spacing="sm",
                children=_source_status_placeholders(),
            ),
        ],
        className="command-strip",
    )


def _source_status_placeholders() -> list[dmc.Box]:
    return [
        dmc.Box(
            [
                dmc.Group(
                    [
                        dmc.Skeleton(h=28, w=28, radius="sm"),
                        dmc.Stack([dmc.Skeleton(h=10, w=82), dmc.Skeleton(h=8, w=132)], gap=6),
                    ],
                    gap="sm",
                    wrap="nowrap",
                )
            ],
            className="source-tile",
        )
        for _ in range(6)
    ]


def _map_panel() -> dmc.Card:
    return dmc.Card(
        [
            _section_header(
                icon="tabler:map-2",
                title="ERCOT Operations Map",
                right=dmc.Text(id="map-caption", size="sm", c="dimmed", className="panel-caption"),
            ),
            dmc.Box(
                [
                    dcc.Graph(id="grid-map", config={"displayModeBar": False}, className="map-graph"),
                    dmc.LoadingOverlay(
                        id="map-price-loader",
                        visible=True,
                        loaderProps={"type": "bars", "color": "cyan"},
                        overlayProps={"radius": "sm", "blur": 2},
                    ),
                ],
                style={"position": "relative"},
            ),
        ],
        withBorder=True,
        padding="md",
        className="panel-card",
    )


def _supply_demand_panel() -> dmc.Card:
    return dmc.Card(
        [
            _section_header(
                icon="tabler:chart-area-line",
                title="ERCOT Supply and Demand",
                right=dmc.Text(id="supply-demand-caption", size="sm", c="dimmed", className="panel-caption"),
            ),
            dcc.Graph(id="supply-demand-chart", config={"displayModeBar": False}, className="supply-demand-graph"),
        ],
        withBorder=True,
        padding="md",
        className="panel-card supply-demand-panel",
    )


def _ercot_dashboard_gallery() -> dmc.Card:
    return dmc.Card(
        [
            _section_header(
                icon="tabler:layout-dashboard",
                title="ERCOT Dashboard Replica",
                right=dmc.Badge("Public feeds", color="cyan", variant="light"),
            ),
            dmc.Grid(
                [
                    dmc.GridCol(_chart_tile("tabler:heartbeat", "Physical Responsive Capability", "prc-chart"), span={"base": 12, "lg": 4}),
                    dmc.GridCol(
                        _chart_tile("tabler:currency-dollar", "System Prices", "system-price-chart"),
                        span={"base": 12, "lg": 4},
                    ),
                    dmc.GridCol(_chart_tile("tabler:chart-area", "Generation Fuel Mix", "ercot-fuel-stack"), span={"base": 12, "lg": 8}),
                    dmc.GridCol(_chart_tile("tabler:battery-charging", "Energy Storage Resources", "storage-chart"), span={"base": 12, "md": 4}),
                    dmc.GridCol(_chart_tile("tabler:plug-connected-x", "Generation Outages", "outages-chart"), span={"base": 12, "md": 4}),
                    dmc.GridCol(_chart_tile("tabler:adjustments-bolt", "Ancillary Services", "ancillary-chart"), span={"base": 12, "md": 4}),
                ],
                gutter="md",
            ),
        ],
        withBorder=True,
        padding="md",
        className="panel-card dashboard-gallery-panel",
    )


def _energy_climate_panel() -> dmc.Card:
    return dmc.Card(
        [
            _section_header(
                icon="tabler:chart-infographic",
                title="Gas and Climate Outlook",
                right=dmc.Badge("EIA + CPC", color="green", variant="light"),
            ),
            dmc.Grid(
                [
                    dmc.GridCol(_chart_tile("tabler:database", "Natural Gas Storage", "eia-gas-storage-chart"), span={"base": 12, "lg": 4}),
                    dmc.GridCol(_chart_tile("tabler:chart-line", "STEO Henry Hub + Inventory", "steo-gas-chart"), span={"base": 12, "lg": 4}),
                    dmc.GridCol(_chart_tile("tabler:temperature", "Texas Climate Degree Days", "degree-day-chart"), span={"base": 12, "lg": 4}),
                ],
                gutter="md",
            ),
        ],
        withBorder=True,
        padding="md",
        className="panel-card dashboard-gallery-panel",
    )


def _chart_tile(icon: str, title: str, graph_id: str) -> dmc.Box:
    return dmc.Box(
        [
            dmc.Group(
                [
                    dmc.ThemeIcon(DashIconify(icon=icon, width=17), color="cyan", variant="light", radius="sm"),
                    dmc.Text(title, fw=800, size="sm", className="chart-tile-title"),
                ],
                gap="xs",
                wrap="nowrap",
                className="chart-tile-header",
            ),
            dcc.Graph(id=graph_id, config={"displayModeBar": False}, className="market-graph"),
        ],
        className="chart-tile",
    )


def _system_panel() -> dmc.Card:
    return dmc.Card(
        [
            _section_header(
                icon="tabler:gauge",
                title="System Intelligence",
                right=dmc.Badge("Computed", color="violet", variant="light"),
            ),
            dmc.Box(id="system-overview"),
        ],
        withBorder=True,
        padding="md",
        className="panel-card intelligence-panel",
    )


def _side_panel() -> dmc.Stack:
    return dmc.Stack(
        [
            _transport_panel(),
            _developer_guide_panel(),
            _scenario_controls(),
            dmc.Card(
                [
                    _section_header(
                        icon="tabler:chart-donut",
                        title="EIA Fuel Mix",
                        right=dmc.Text(id="fuel-period", size="xs", c="dimmed", className="panel-caption"),
                    ),
                    dcc.Graph(id="fuel-mix", config={"displayModeBar": False}, className="fuel-graph"),
                ],
                withBorder=True,
                padding="md",
                className="panel-card",
            ),
            dmc.Card(
                [
                    _section_header(
                        icon="tabler:terminal-2",
                        title="Event Feed",
                        right=dmc.Group(
                            [
                                dmc.Badge("0 events", id="event-feed-count", color="gray", variant="light"),
                                dmc.Badge("Deduped", color="green", variant="light"),
                            ],
                            gap=6,
                            wrap="nowrap",
                        ),
                    ),
                    dmc.ScrollArea(id="event-feed", h=285, scrollbars="y", offsetScrollbars=True),
                ],
                withBorder=True,
                padding="md",
                className="panel-card",
            ),
        ],
        gap="md",
    )


def _developer_guide_panel() -> dmc.Card:
    return dmc.Card(
        [
            _section_header(
                icon="tabler:help-hexagon",
                title="Dash 4.2 Field Guide",
                right=dmc.Badge("rc3 patterns", color="cyan", variant="light"),
            ),
            dmc.Tabs(
                [
                    dmc.TabsList(
                        [
                            dmc.TabsTab(
                                "Processes",
                                value="processes",
                                leftSection=DashIconify(icon="tabler:route", width=15),
                            ),
                            dmc.TabsTab(
                                "Tips",
                                value="tips",
                                leftSection=DashIconify(icon="tabler:sparkles", width=15),
                            ),
                        ],
                        grow=True,
                        className="guide-tabs-list",
                    ),
                    dmc.TabsPanel(
                        dmc.Stack(
                            [_process_help_tile(topic) for topic in PROCESS_HELP_TOPICS],
                            gap="xs",
                        ),
                        value="processes",
                        className="guide-tab-panel",
                    ),
                    dmc.TabsPanel(
                        dmc.Stack(
                            [
                                *[_tip_card(topic) for topic in TIP_TOPICS],
                                dmc.Box(id="async-benefit-card", className="async-benefit-card"),
                            ],
                            gap="xs",
                        ),
                        value="tips",
                        className="guide-tab-panel",
                    ),
                ],
                value="processes",
                variant="pills",
                className="guide-tabs",
            ),
        ],
        withBorder=True,
        padding="md",
        className="panel-card developer-guide-panel",
    )


def _process_help_tile(topic: dict[str, object]) -> dmc.Box:
    color = str(topic["color"])
    return dmc.Box(
        [
            dmc.Group(
                [
                    _process_hovercard(topic),
                    dmc.Stack(
                        [
                            dmc.Text(str(topic["title"]), fw=830, size="sm", lineClamp=1),
                            dmc.Text(str(topic["summary"]), size="xs", c="dimmed", lineClamp=2),
                        ],
                        gap=2,
                    ),
                ],
                gap="sm",
                wrap="nowrap",
                align="flex-start",
            ),
            dmc.Group(
                [_code_chip(str(item)) for item in topic["code"]],
                gap=6,
                mt=8,
                wrap="wrap",
            ),
        ],
        className=f"guide-topic guide-topic-{color}",
    )


def _process_hovercard(topic: dict[str, object]) -> dmc.HoverCard:
    color = str(topic["color"])
    return dmc.HoverCard(
        [
            dmc.HoverCardTarget(
                dmc.ActionIcon(
                    DashIconify(icon=str(topic["icon"]), width=19),
                    color=color,
                    variant="light",
                    size="lg",
                    radius="sm",
                    className="guide-action-icon",
                )
            ),
            dmc.HoverCardDropdown(
                dmc.Stack(
                    [
                        dmc.Group(
                            [
                                dmc.ThemeIcon(
                                    DashIconify(icon=str(topic["icon"]), width=18),
                                    color=color,
                                    variant="light",
                                    radius="sm",
                                ),
                                dmc.Text(str(topic["title"]), fw=850, size="sm"),
                            ],
                            gap="xs",
                            wrap="nowrap",
                        ),
                        dmc.Text(str(topic["summary"]), size="sm", c="dimmed"),
                        dmc.Stack(
                            [_guide_bullet(str(detail), color) for detail in topic["details"]],
                            gap=6,
                        ),
                        dmc.Group(
                            [_code_chip(str(item)) for item in topic["code"]],
                            gap=6,
                            wrap="wrap",
                        ),
                    ],
                    gap="xs",
                    className="guide-hover-content",
                ),
                className="guide-hover-dropdown",
            ),
        ],
        width=360,
        shadow="xl",
        withArrow=True,
        openDelay=140,
        closeDelay=80,
        position="bottom-start",
    )


def _tip_card(topic: dict[str, object]) -> dmc.Box:
    color = str(topic["color"])
    return dmc.Box(
        [
            dmc.Group(
                [
                    dmc.ThemeIcon(
                        DashIconify(icon=str(topic["icon"]), width=17),
                        color=color,
                        variant="light",
                        radius="sm",
                    ),
                    dmc.Text(str(topic["title"]), fw=830, size="sm"),
                ],
                gap="xs",
                wrap="nowrap",
            ),
            dmc.Text(str(topic["body"]), size="xs", c="dimmed", mt=5),
            _code_block([str(line) for line in topic["code"]]),
        ],
        className=f"guide-tip guide-tip-{color}",
    )


def _guide_bullet(text: str, color: str) -> dmc.Group:
    return dmc.Group(
        [
            dmc.ThemeIcon(
                DashIconify(icon="tabler:point-filled", width=12),
                color=color,
                variant="subtle",
                radius="xl",
                size=18,
            ),
            dmc.Text(text, size="xs", c="dimmed"),
        ],
        gap=6,
        wrap="nowrap",
        align="flex-start",
    )


def _code_chip(text: str) -> dmc.Box:
    return dmc.Box(dmc.Text(text, size="xs", className="guide-code-text"), className="guide-code-chip")


def _code_block(lines: list[str]) -> dmc.Box:
    return dmc.Box(
        [dmc.Text(line, size="xs", className="guide-code-line") for line in lines],
        className="guide-code-block",
    )


def _transport_panel() -> dmc.Card:
    return dmc.Card(
        [
            _section_header(
                icon="tabler:plug-connected",
                title="Dash 4.2 Transport",
                right=dmc.Group(
                    [
                        dmc.Badge("WS idle", id="ws-side-update-status", color="gray", variant="light"),
                        dmc.Badge("WebSocket", id="ws-transport-mode", color="cyan", variant="light"),
                    ],
                    gap=6,
                    wrap="nowrap",
                ),
            ),
            dmc.SimpleGrid(
                [
                    dmc.Box(
                        [
                            dmc.Text("ASGI fanout", size="xs", c="dimmed", tt="uppercase", fw=800),
                            dmc.Text(id="fanout-latency-total", className="transport-value"),
                        ],
                        className="transport-stat",
                    ),
                    dmc.Box(
                        [
                            dmc.Text("Callback path", size="xs", c="dimmed", tt="uppercase", fw=800),
                            dmc.Text(id="callback-transport-meta", className="transport-value"),
                        ],
                        className="transport-stat",
                    ),
                ],
                cols=2,
                spacing="sm",
            ),
            dmc.Stack(id="fanout-latency-grid", gap=7, mt="sm", children=_latency_placeholders()),
        ],
        withBorder=True,
        padding="md",
        className="panel-card transport-panel",
    )


def _latency_placeholders() -> list[dmc.Skeleton]:
    return [dmc.Skeleton(h=26, radius="sm") for _ in range(4)]


def _scenario_controls() -> dmc.Card:
    return dmc.Card(
        [
            _section_header(
                icon="tabler:adjustments-bolt",
                title="Scenario Controls",
                right=dmc.Badge("Scenario store", color="cyan", variant="light"),
            ),
            dmc.Stack(
                [
                    dmc.Box(id="scenario-preview-grid", className="scenario-preview-grid"),
                    dmc.Box(id="active-scenario-impact", className="active-scenario-impact"),
                    dmc.Button(
                        "Heatwave simulation",
                        id="heatwave-button",
                        color="red",
                        variant="light",
                        leftSection=DashIconify(icon="tabler:temperature-sun", width=18),
                        fullWidth=True,
                        className="scenario-button",
                    ),
                    dmc.Button(
                        "Wind ramp simulation",
                        id="wind-button",
                        color="green",
                        variant="light",
                        leftSection=DashIconify(icon="tabler:wind", width=18),
                        fullWidth=True,
                        className="scenario-button",
                    ),
                    dmc.Button(
                        "Full system refresh",
                        id="refresh-button",
                        color="cyan",
                        variant="filled",
                        leftSection=DashIconify(icon="tabler:refresh", width=18),
                        fullWidth=True,
                        className="scenario-button scenario-button-primary",
                    ),
                ],
                gap="xs",
            ),
        ],
        withBorder=True,
        padding="md",
        className="panel-card",
    )


def _section_header(*, icon: str, title: str, right) -> dmc.Group:
    return dmc.Group(
        [
            dmc.Group(
                [
                    dmc.ThemeIcon(DashIconify(icon=icon, width=18), color="cyan", variant="light", radius="sm"),
                    dmc.Title(title, order=4, className="panel-title"),
                ],
                gap="xs",
                wrap="nowrap",
            ),
            right,
        ],
        justify="space-between",
        align="center",
        mb="sm",
        wrap="nowrap",
        className="panel-header",
    )


def kpi_card(
    *,
    title: str,
    value: str,
    subtitle: str,
    color: str,
    icon: str,
    progress: float,
    signal: str,
    sparkline=None,
) -> dmc.Card:
    tone_class = {
        "cyan": "tone-cyan",
        "yellow": "tone-yellow",
        "green": "tone-green",
        "orange": "tone-orange",
        "red": "tone-red",
        "violet": "tone-violet",
    }.get(color, "tone-cyan")

    return dmc.Card(
        [
            dcc.Graph(
                figure=sparkline,
                config={"displayModeBar": False, "staticPlot": True},
                className="kpi-sparkline",
            )
            if sparkline is not None
            else None,
            dmc.Group(
                [
                    dmc.Stack(
                        [
                            dmc.Text(title, size="xs", c="dimmed", tt="uppercase", fw=800, className="kpi-label"),
                            dmc.Text(signal, size="xs", className="kpi-signal"),
                        ],
                        gap=1,
                    ),
                    dmc.ThemeIcon(
                        DashIconify(icon=icon, width=19),
                        color=color,
                        variant="light",
                        radius="sm",
                        className="kpi-icon",
                    ),
                ],
                justify="space-between",
                align="flex-start",
                mb=8,
                wrap="nowrap",
            ),
            dmc.Text(value, className="kpi-value"),
            dmc.Progress(value=progress, color=color, size=4, radius="xl", mt="xs", mb=6),
            dmc.Text(subtitle, size="xs", c="dimmed", className="kpi-subtitle"),
        ],
        withBorder=True,
        padding="md",
        className=f"kpi-card {tone_class}",
    )

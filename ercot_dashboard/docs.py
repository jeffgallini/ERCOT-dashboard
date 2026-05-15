from __future__ import annotations

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, Response


API_TITLE = "ERCOT Grid Pulse API"
API_SUMMARY = "FastAPI orchestration layer mounted inside the Dash 4.2 demo."
API_VERSION = "0.2.0"
API_DESCRIPTION = """
ERCOT Grid Pulse uses Dash with `backend="fastapi"` so the reactive dashboard,
source APIs, OpenAPI schema, and Swagger console share one ASGI
application.

The routes are intentionally grouped by source system:

- Operations: health, aggregate dashboard state, feed catalog, and source-specific refreshes
- ERCOT: grid, market, public dashboard, and diagnostic endpoints
- EIA: fuel mix plus natural gas storage, supply/consumption, and STEO outlook
- Weather: NOAA/NWS observations and CPC degree-day outlooks
- Events: manual operator events backed by an in-memory demo store
- Streams: WebSocket channel catalog for live UI transports
"""

OPENAPI_TAGS = [
    {
        "name": "Operations",
        "description": "Health checks, aggregate dashboard state, feed catalog, and async source bundle refreshes.",
    },
    {
        "name": "ERCOT",
        "description": "ERCOT grid snapshots, configured reports, and dashboard replica feeds.",
        "externalDocs": {
            "description": "ERCOT public API specifications",
            "url": "https://github.com/ercot/api-specs",
        },
    },
    {
        "name": "ERCOT Market",
        "description": "Real-time and day-ahead LMP endpoints normalized for demo analytics.",
    },
    {
        "name": "EIA",
        "description": "EIA API v2 electricity and natural gas data normalized for the dashboard.",
        "externalDocs": {
            "description": "EIA API v2 documentation",
            "url": "https://www.eia.gov/opendata/documentation.php",
        },
    },
    {
        "name": "Weather",
        "description": "NOAA/NWS airport observations and CPC degree-day outlooks.",
        "externalDocs": {
            "description": "NOAA Climate Data Online web services",
            "url": "https://www.ncdc.noaa.gov/cdo-web/webservices/v2",
        },
    },
    {
        "name": "Events",
        "description": "Manual operator events that appear in dashboard snapshots and the event feed.",
    },
    {
        "name": "Streams",
        "description": "WebSocket transport catalog. WebSocket routes are not represented directly in OpenAPI.",
    },
]

SWAGGER_UI_PARAMETERS = {
    "defaultModelsExpandDepth": 0,
    "defaultModelExpandDepth": 1,
    "displayRequestDuration": True,
    "docExpansion": "none",
    "filter": True,
    "operationsSorter": "alpha",
    "persistAuthorization": True,
    "showExtensions": True,
    "syntaxHighlight": {"theme": "obsidian"},
    "tagsSorter": "alpha",
    "tryItOutEnabled": True,
}

SWAGGER_THEME_CSS = """
@import url("https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css");

:root {
  color-scheme: dark;
  --console-bg: #080a0d;
  --console-surface: #10151b;
  --console-surface-raised: #151b22;
  --console-surface-soft: rgba(19, 25, 32, 0.78);
  --console-code: #090d12;
  --console-line: rgba(174, 188, 204, 0.18);
  --console-line-strong: rgba(174, 188, 204, 0.3);
  --console-teal: #2dd4bf;
  --console-blue: #60a5fa;
  --console-green: #40c878;
  --console-amber: #f4c542;
  --console-red: #fb7185;
  --console-text: #f4f7fb;
  --console-muted: #a9b5c3;
  --console-faint: #788697;
  --console-schema-heading: #e8eef8;
  --console-schema-property: #b9c8dc;
  --console-schema-control: #d7e8ff;
  --console-schema-type: #9fa8ff;
  --console-schema-value: #aebddb;
}

html,
body {
  min-height: 100%;
  background:
    linear-gradient(rgba(174, 188, 204, 0.026) 1px, transparent 1px),
    linear-gradient(90deg, rgba(174, 188, 204, 0.026) 1px, transparent 1px),
    linear-gradient(180deg, var(--console-bg) 0%, #0c1116 48%, #0b0d10 100%);
  background-size: 46px 46px, 46px 46px, auto;
}

body {
  margin: 0;
  color: var(--console-text);
  font-family: Inter, "Segoe UI", sans-serif;
}

body::before {
  position: fixed;
  z-index: 20;
  top: 0;
  right: 0;
  left: 0;
  display: block;
  padding: 17px 28px 4px;
  border-bottom: 1px solid var(--console-line);
  background: rgba(8, 10, 13, 0.94);
  color: var(--console-text);
  content: "ERCOT Grid Pulse API Console";
  font-size: 1.25rem;
  font-weight: 750;
  letter-spacing: 0;
  backdrop-filter: blur(18px);
}

body::after {
  position: fixed;
  z-index: 21;
  top: 48px;
  left: 28px;
  color: var(--console-muted);
  content: "Dash 4.2 FastAPI backend | tagged source APIs | Pydantic schemas";
  font-size: 0.8rem;
}

.swagger-ui {
  max-width: 1480px;
  margin: 0 auto;
  padding: 94px 20px 42px;
  color: var(--console-text);
  font-family: Inter, "Segoe UI", sans-serif;
}

.swagger-ui .topbar {
  display: none;
}

.swagger-ui .info {
  margin: 28px 0 24px;
  padding: 20px;
  border: 1px solid var(--console-line);
  border-left: 4px solid var(--console-teal);
  border-radius: 8px;
  background: rgba(16, 21, 27, 0.92);
}

.swagger-ui .info .title,
.swagger-ui .info h1,
.swagger-ui .info h2,
.swagger-ui .info h3,
.swagger-ui .info h4,
.swagger-ui .opblock-tag,
.swagger-ui .opblock .opblock-summary-operation-id,
.swagger-ui .opblock .opblock-summary-path,
.swagger-ui .opblock-description-wrapper p,
.swagger-ui .model-title,
.swagger-ui table thead tr td,
.swagger-ui table thead tr th {
  color: var(--console-text);
  font-family: Inter, "Segoe UI", sans-serif;
}

.swagger-ui .info p,
.swagger-ui .info li,
.swagger-ui .markdown p,
.swagger-ui .markdown li,
.swagger-ui .parameter__name,
.swagger-ui .parameter__type,
.swagger-ui .response-col_status,
.swagger-ui .response-col_description,
.swagger-ui .opblock-summary-description,
.swagger-ui .tab li,
.swagger-ui label {
  color: var(--console-muted);
}

.swagger-ui .scheme-container,
.swagger-ui .opblock-tag,
.swagger-ui section.models {
  border: 1px solid var(--console-line);
  border-radius: 8px;
  background: rgba(16, 21, 27, 0.92);
  box-shadow: none;
}

.swagger-ui .scheme-container {
  padding: 12px 16px;
}

.swagger-ui .opblock-tag {
  padding: 13px 16px;
  margin: 14px 0 10px;
  font-size: 1rem;
  letter-spacing: 0;
}

.swagger-ui .opblock-tag:hover {
  background: rgba(21, 27, 34, 0.96);
}

.swagger-ui .opblock-tag small {
  color: var(--console-faint);
}

.swagger-ui .opblock {
  overflow: hidden;
  border-radius: 8px;
  background: var(--console-surface-soft);
  box-shadow: none;
}

.swagger-ui .opblock .opblock-summary {
  min-height: 52px;
}

.swagger-ui .opblock.opblock-get {
  border-color: rgba(96, 165, 250, 0.3);
  background: rgba(34, 55, 78, 0.34);
}

.swagger-ui .opblock.opblock-post {
  border-color: rgba(64, 200, 120, 0.28);
  background: rgba(28, 65, 44, 0.32);
}

.swagger-ui .opblock.opblock-get .opblock-summary-method {
  background: #2563eb;
}

.swagger-ui .opblock.opblock-post .opblock-summary-method {
  background: #15803d;
}

.swagger-ui .opblock .opblock-summary-path,
.swagger-ui .opblock .opblock-summary-path__deprecated {
  color: var(--console-text);
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 0.92rem;
}

.swagger-ui .opblock .opblock-summary-operation-id {
  color: var(--console-faint);
}

.swagger-ui .btn,
.swagger-ui .btn.authorize,
.swagger-ui select,
.swagger-ui input[type="text"],
.swagger-ui textarea {
  border-color: rgba(148, 163, 184, 0.28);
  border-radius: 7px;
  background: rgba(9, 13, 18, 0.94);
  color: var(--console-text);
  box-shadow: none;
}

.swagger-ui input[type="text"]::placeholder,
.swagger-ui textarea::placeholder {
  color: var(--console-faint);
}

.swagger-ui .btn:hover,
.swagger-ui select:hover {
  border-color: var(--console-line-strong);
  background: var(--console-surface-raised);
}

.swagger-ui .btn.execute {
  border-color: rgba(45, 212, 191, 0.42);
  background: #0f766e;
}

.swagger-ui .highlight-code,
.swagger-ui .microlight,
.swagger-ui .responses-inner,
.swagger-ui .parameters-container,
.swagger-ui .opblock-section-header {
  background: rgba(9, 13, 18, 0.74) !important;
  color: var(--console-text);
}

.swagger-ui .opblock-body pre.microlight {
  background: #000000 !important;
}

.swagger-ui .opblock-section-header {
  border-color: var(--console-line);
  box-shadow: none;
}

.swagger-ui table tbody tr td,
.swagger-ui table tbody tr th {
  border-color: var(--console-line);
  color: var(--console-muted);
}

.swagger-ui .renderedMarkdown code,
.swagger-ui code,
.swagger-ui pre,
.swagger-ui .microlight {
  font-family: "Cascadia Code", Consolas, monospace;
}

.swagger-ui section.models {
  margin: 30px 0 0;
  padding: 0;
  overflow: hidden;
}

.swagger-ui section.models h4 {
  margin: 0;
  padding: 16px 18px;
  border-bottom: 1px solid var(--console-line);
  background: rgba(21, 27, 34, 0.68);
  color: var(--console-text);
  font-size: 1rem;
  letter-spacing: 0;
}

.swagger-ui section.models h4 span {
  color: var(--console-muted);
}

.swagger-ui section.models .model-container {
  margin: 10px 12px;
  border: 1px solid var(--console-line);
  border-radius: 7px;
  background: rgba(11, 15, 20, 0.72);
  box-shadow: none;
}

.swagger-ui section.models .model-box,
.swagger-ui .model-box {
  background: transparent !important;
}

.swagger-ui section.models .model-box {
  padding: 12px 14px;
}

.swagger-ui section.models button,
.swagger-ui section.models .model span,
.swagger-ui section.models .model-title,
.swagger-ui section.models .model-title__text,
.swagger-ui section.models .model-hint,
.swagger-ui section.models .property,
.swagger-ui section.models .property.primitive,
.swagger-ui section.models .prop-type,
.swagger-ui section.models .prop-format,
.swagger-ui section.models .model-toggle {
  background-color: transparent !important;
  box-shadow: none !important;
  text-shadow: none;
}

.swagger-ui section.models button {
  border: 0;
  color: var(--console-schema-control) !important;
}

.swagger-ui section.models .model-hint {
  color: var(--console-schema-control) !important;
  font-family: Inter, "Segoe UI", sans-serif;
  font-size: 0.78rem;
  font-weight: 500;
}

.swagger-ui .model {
  color: var(--console-schema-property) !important;
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 0.86rem;
}

.swagger-ui section.models .model span {
  color: var(--console-schema-property) !important;
}

.swagger-ui .model-title,
.swagger-ui .model-title__text {
  color: var(--console-schema-heading) !important;
  font-family: Inter, "Segoe UI", sans-serif;
  font-weight: 700;
}

.swagger-ui .model .property {
  color: var(--console-schema-property) !important;
  font-weight: 650;
}

.swagger-ui .model .property.primitive {
  color: var(--console-schema-property) !important;
}

.swagger-ui .model .required,
.swagger-ui .parameter__name.required,
.swagger-ui .parameter__name.required::after {
  color: var(--console-red);
}

.swagger-ui .model .prop-type {
  color: var(--console-schema-type) !important;
  font-weight: 700;
}

.swagger-ui .model .prop-format {
  color: var(--console-schema-type) !important;
}

.swagger-ui .model .prop-enum,
.swagger-ui .model .prop-default {
  color: var(--console-amber) !important;
}

.swagger-ui section.models .model .primitive,
.swagger-ui section.models .model .inner-object,
.swagger-ui section.models .model .model-example,
.swagger-ui section.models .model .example,
.swagger-ui section.models .model .brace-open,
.swagger-ui section.models .model .brace-close {
  color: var(--console-schema-value) !important;
}

.swagger-ui .model .property-row {
  border-top: 1px solid rgba(174, 188, 204, 0.1);
}

.swagger-ui .model-toggle::after {
  opacity: 0.9;
  filter: invert(92%) sepia(18%) saturate(652%) hue-rotate(176deg);
}

.swagger-ui section.models svg {
  color: var(--console-schema-control) !important;
  fill: var(--console-schema-control) !important;
  stroke: var(--console-schema-control) !important;
}

.swagger-ui .model-example,
.swagger-ui .body-param__example,
.swagger-ui .example,
.swagger-ui .responses-wrapper {
  color: var(--console-muted);
}

.swagger-ui a,
.swagger-ui .info a {
  color: var(--console-teal);
}

.swagger-ui .errors-wrapper {
  border-color: rgba(251, 113, 133, 0.34);
  background: rgba(127, 29, 29, 0.25);
}
"""


def configure_openapi_docs(server: FastAPI) -> None:
    server.title = API_TITLE
    server.summary = API_SUMMARY
    server.description = API_DESCRIPTION
    server.version = API_VERSION
    server.openapi_tags = OPENAPI_TAGS
    server.swagger_ui_parameters = SWAGGER_UI_PARAMETERS
    server.contact = {"name": "ERCOT Grid Pulse Demo"}
    server.license_info = {"name": "Demo use only"}
    server.servers = [{"url": "/", "description": "Dash-mounted FastAPI backend"}]
    server.openapi_schema = None

    _remove_route(server, "/docs")

    @server.get("/docs", include_in_schema=False)
    async def custom_swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=server.openapi_url,
            title=f"{API_TITLE} - Swagger",
            oauth2_redirect_url=server.swagger_ui_oauth2_redirect_url,
            swagger_css_url="/api/docs/swagger-theme.css",
            swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
        )

    @server.get("/api/docs/swagger-theme.css", include_in_schema=False)
    async def swagger_theme() -> Response:
        return Response(SWAGGER_THEME_CSS, media_type="text/css")


def _remove_route(server: FastAPI, path: str) -> None:
    server.router.routes[:] = [route for route in server.router.routes if getattr(route, "path", "") != path]

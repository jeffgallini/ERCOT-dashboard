from __future__ import annotations

import time

import dash
import dash_mantine_components as dmc
from dash.backends._fastapi import DashMiddleware

from ercot_dashboard.api import register_api_routes
from ercot_dashboard.callbacks import register_callbacks
from ercot_dashboard.docs import configure_openapi_docs
from ercot_dashboard.layout import build_layout


def _patch_dash_api_body_passthrough() -> None:
    if getattr(DashMiddleware, "_ercot_api_body_passthrough", False):
        return

    original_setup_timing = DashMiddleware._setup_timing

    async def setup_timing_without_api_body_read(self: DashMiddleware, request) -> None:
        path = str(request.scope.get("path") or "")
        dash_prefix = str(self.dash_app.config.requests_pathname_prefix or "/dash/")
        if not path.startswith(dash_prefix):
            request.state.json_body = None
            if self.enable_timing:
                request.state.timing_information = {"__dash_server": {"dur": time.time(), "desc": None}}
            return

        await original_setup_timing(self, request)

    DashMiddleware._setup_timing = setup_timing_without_api_body_read
    DashMiddleware._ercot_api_body_passthrough = True


def create_app() -> dash.Dash:
    _patch_dash_api_body_passthrough()

    app = dash.Dash(
        __name__,
        backend="fastapi",
        external_stylesheets=dmc.styles.ALL,
        requests_pathname_prefix="/dash/",
        routes_pathname_prefix="/dash/",
        suppress_callback_exceptions=True,
        title="ERCOT Grid Pulse",
        update_title=None,
    )

    configure_openapi_docs(app.server)
    register_api_routes(app.server)
    app.layout = build_layout()
    register_callbacks(app)

    return app


dash_app = create_app()
server = dash_app.server


if __name__ == "__main__":
    # Dash's FastAPI backend delegates to uvicorn; disabling reload avoids
    # Windows named-pipe failures from the reload worker while keeping dev tools.
    dash_app.run(debug=True, host="127.0.0.1", port=8050, reload=False)

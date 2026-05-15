from __future__ import annotations

import dash_leaflet as dl
from fastapi.testclient import TestClient

from ercot_dashboard.app import create_app
from ercot_dashboard.layout import PROCESS_HELP_TOPICS, TIP_TOPICS, build_layout
from ercot_dashboard.services.events import clear_operator_events


def test_event_feed_uses_dash_websocket_transport() -> None:
    app = create_app()

    websocket_callbacks = [
        callback_id
        for callback_id, callback in app.callback_map.items()
        if callback.get("websocket")
    ]

    assert "event-log-store.data" in websocket_callbacks
    assert any(
        callback_id.startswith("..prc-chart.figure...system-price-chart.figure...system-demand-chart.figure")
        for callback_id in app.callback_map
    )


def test_leaflet_map_is_fixed_viewport() -> None:
    layout = build_layout()
    grid_map = _find_component(layout, "grid-map")

    assert isinstance(grid_map, dl.Map)
    assert grid_map.zoomControl is False
    assert grid_map.dragging is False
    assert grid_map.scrollWheelZoom is False
    assert grid_map.doubleClickZoom is False
    assert grid_map.boxZoom is False
    assert grid_map.touchZoom is False
    assert grid_map.keyboard is False


def test_dash42_field_guide_covers_requested_topics() -> None:
    process_titles = {topic["title"] for topic in PROCESS_HELP_TOPICS}
    tip_titles = {topic["title"] for topic in TIP_TOPICS}

    assert process_titles == {"API endpoints", "Async callbacks", "WebSockets", "FastAPI backend"}
    assert "Add FastAPI as the backend" in tip_titles
    assert "Theme Swagger UI in code" in tip_titles
    assert "Set up websockets where they help" in tip_titles


def test_fastapi_openapi_docs_are_curated_for_demo_sources() -> None:
    app = create_app()
    schema = app.server.openapi()

    assert app.server.title == "ERCOT Grid Pulse API"
    assert [tag["name"] for tag in schema["tags"]] == [
        "Operations",
        "ERCOT",
        "ERCOT Market",
        "EIA",
        "Weather",
        "Events",
        "Streams",
    ]
    assert schema["paths"]["/api/dashboard"]["get"]["tags"] == ["Operations"]
    assert schema["paths"]["/api/feeds"]["get"]["tags"] == ["Operations"]
    assert schema["paths"]["/api/ercot/grid"]["get"]["tags"] == ["ERCOT"]
    assert schema["paths"]["/api/ercot/system-load"]["get"]["tags"] == ["ERCOT"]
    assert schema["paths"]["/api/ercot/load-zones/{zone_name}/load"]["get"]["tags"] == ["ERCOT"]
    assert schema["paths"]["/api/ercot/load-zones/{zone_name}/generation"]["get"]["tags"] == ["ERCOT"]
    assert schema["paths"]["/api/ercot/public-dashboards/{feed_name}"]["get"]["tags"] == ["ERCOT"]
    assert schema["paths"]["/api/eia/fuel-mix"]["get"]["tags"] == ["EIA"]
    assert schema["paths"]["/api/eia/natural-gas/{feed_name}"]["get"]["tags"] == ["EIA"]
    assert schema["paths"]["/api/eia/natural-gas"]["get"]["tags"] == ["EIA"]
    assert schema["paths"]["/api/weather/airports"]["get"]["tags"] == ["Weather"]
    assert schema["paths"]["/api/weather/airports/{airport_code}"]["get"]["tags"] == ["Weather"]
    assert schema["paths"]["/api/ercot/load-zone-lmps"]["get"]["tags"] == ["ERCOT Market"]
    assert schema["paths"]["/api/events"]["post"]["tags"] == ["Events"]
    assert schema["paths"]["/api/events/{event_id}"]["put"]["tags"] == ["Events"]
    assert schema["paths"]["/api/events/{event_id}"]["delete"]["tags"] == ["Events"]
    assert "/api/scenario/preview" not in schema["paths"]
    assert "/api/streams" in schema["paths"]
    assert "/api/docs/swagger-theme.css" not in schema["paths"]
    assert "DashboardSnapshot" in schema["components"]["schemas"]
    assert "FeedCatalogResponse" in schema["components"]["schemas"]
    assert "FeedSnapshotResponse" in schema["components"]["schemas"]
    assert "ScenarioInput" not in schema["components"]["schemas"]
    assert "OperatorEventCreate" in schema["components"]["schemas"]


def test_feed_catalog_lists_individual_source_routes() -> None:
    app = create_app()
    client = TestClient(app.server)

    response = client.get("/api/feeds")

    assert response.status_code == 200
    feeds = {feed["local_url"]: feed for feed in response.json()["feeds"]}
    assert "/api/ercot/system-load" in feeds
    assert "/api/ercot/load-zones/houston/load" in feeds
    assert "/api/ercot/load-zones/houston/generation" in feeds
    assert "/api/ercot/public-dashboards/prc" in feeds
    assert "/api/eia/fuel-mix" in feeds
    assert "/api/eia/natural-gas/storage" in feeds
    assert "/api/weather/airports/DFW" in feeds


def test_custom_swagger_theme_is_served_from_fastapi() -> None:
    app = create_app()
    client = TestClient(app.server)

    docs_response = client.get("/docs")
    theme_response = client.get("/api/docs/swagger-theme.css")

    assert docs_response.status_code == 200
    assert "/api/docs/swagger-theme.css" in docs_response.text
    assert theme_response.status_code == 200
    assert "ERCOT Grid Pulse API Console" in theme_response.text


def test_operator_event_crud_endpoints_change_event_store() -> None:
    clear_operator_events()
    app = create_app()
    client = TestClient(app.server)

    try:
        created = client.post(
            "/api/events",
            json={
                "level": "warning",
                "title": "Manual reserve watch",
                "message": "North load-zone reserve margin is under manual observation.",
                "source": "Control room",
            },
        )
        assert created.status_code == 201
        event = created.json()
        event_id = event["id"]
        assert event["acknowledged"] is False

        listed = client.get("/api/events").json()
        assert listed["count"] == 1
        assert listed["events"][0]["id"] == event_id

        updated = client.put(
            f"/api/events/{event_id}",
            json={"level": "success", "title": "Reserve watch acknowledged", "acknowledged": True},
        )
        assert updated.status_code == 200
        assert updated.json()["level"] == "success"
        assert updated.json()["acknowledged"] is True

        active = client.get("/api/events?include_acknowledged=false").json()
        assert active["count"] == 0

        deleted = client.delete(f"/api/events/{event_id}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True

        missing = client.delete(f"/api/events/{event_id}")
        assert missing.status_code == 404
    finally:
        clear_operator_events()


def _find_component(component: object, component_id: str) -> object:
    if getattr(component, "id", None) == component_id:
        return component

    children = getattr(component, "children", None)
    if isinstance(children, list | tuple):
        for child in children:
            match = _find_component(child, component_id)
            if match is not None:
                return match
    elif children is not None:
        return _find_component(children, component_id)

    return None

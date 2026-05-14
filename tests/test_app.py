from __future__ import annotations

from fastapi.testclient import TestClient

from ercot_dashboard.app import create_app
from ercot_dashboard.layout import PROCESS_HELP_TOPICS, TIP_TOPICS
from ercot_dashboard.services.events import clear_operator_events


def test_transport_panel_callback_uses_dash_websocket_transport() -> None:
    app = create_app()

    websocket_callbacks = [
        callback_id
        for callback_id, callback in app.callback_map.items()
        if callback.get("websocket")
    ]

    assert (
        "..ws-transport-mode.children...ws-transport-mode.color..."
        "fanout-latency-total.children...callback-transport-meta.children..."
        "fanout-latency-grid.children.."
    ) in websocket_callbacks
    assert "event-log-store.data" in websocket_callbacks
    assert "active-scenario-impact.children" in app.callback_map
    assert "async-benefit-card.children" in app.callback_map


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
        "Scenarios",
        "Streams",
    ]
    assert schema["paths"]["/api/dashboard"]["get"]["tags"] == ["Operations"]
    assert schema["paths"]["/api/eia/natural-gas"]["get"]["tags"] == ["EIA"]
    assert schema["paths"]["/api/weather/airports"]["get"]["tags"] == ["Weather"]
    assert schema["paths"]["/api/ercot/load-zone-lmps"]["get"]["tags"] == ["ERCOT Market"]
    assert schema["paths"]["/api/events"]["post"]["tags"] == ["Events"]
    assert schema["paths"]["/api/events/{event_id}"]["put"]["tags"] == ["Events"]
    assert schema["paths"]["/api/events/{event_id}"]["delete"]["tags"] == ["Events"]
    assert schema["paths"]["/api/scenario/preview"]["post"]["tags"] == ["Scenarios"]
    assert "/api/streams" in schema["paths"]
    assert "/api/docs/swagger-theme.css" not in schema["paths"]
    assert "DashboardSnapshot" in schema["components"]["schemas"]
    assert "ScenarioInput" in schema["components"]["schemas"]
    assert "OperatorEventCreate" in schema["components"]["schemas"]


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

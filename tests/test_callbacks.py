from __future__ import annotations

import asyncio

from ercot_dashboard.callbacks import _apply_scenario_command, _map_price_event_records, _merge_event_log
from ercot_dashboard.services.dashboard import get_dashboard_snapshot


def test_map_price_events_capture_missing_south_lmp_and_dedupe() -> None:
    map_prices = {
        "timestamp": "2026-05-13T19:30:00+00:00",
        "status": {"state": "partial", "message": "Missing load zone LMP rows: South"},
        "zones": [
            {
                "name": "South",
                "settlement_point": "LZ_SOUTH",
                "status": "unavailable",
                "diagnostic": {"message": "No rows returned for LZ_SOUTH."},
            }
        ],
    }

    records = _map_price_event_records(map_prices)
    first_log = _merge_event_log([], records)
    second_log = _merge_event_log(first_log, records)

    assert records[0]["title"] == "LZ_SOUTH RT LMP Unavailable"
    assert records[0]["level"] == "danger"
    assert len(second_log) == 1
    assert second_log[0]["count"] == 2


def test_scenario_command_reapplies_transform_to_composed_snapshot() -> None:
    snapshot = asyncio.run(get_dashboard_snapshot(use_live=False))

    heatwave = _apply_scenario_command(snapshot, {"kind": "heatwave"})
    wind = _apply_scenario_command(snapshot, {"kind": "wind"})

    assert heatwave["active_scenario"]["label"] == "Heatwave Simulation"
    assert heatwave["ercot"]["load_mw"] > snapshot["ercot"]["load_mw"]
    assert wind["active_scenario"]["label"] == "Wind Ramp Simulation"
    assert wind["ercot"]["wind_mw"] > snapshot["ercot"]["wind_mw"]

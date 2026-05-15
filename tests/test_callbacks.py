from __future__ import annotations

from ercot_dashboard.callbacks import _map_price_event_records, _merge_event_log


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

from __future__ import annotations

from tests.system.observability.prometheus.common import service_info_by_service


def test_service_info_by_service_indexes_rows_by_service_label() -> None:
    payload = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {"metric": {"service": "finder", "job": "finder"}, "value": [0, "1"]},
                {"metric": {"service": "monitor", "job": "monitor"}, "value": [0, "1"]},
            ],
        },
    }

    rows = service_info_by_service(payload)

    assert set(rows) == {"finder", "monitor"}
    assert rows["finder"]["metric"]["job"] == "finder"
    assert rows["monitor"]["metric"]["job"] == "monitor"


def test_service_info_by_service_ignores_rows_without_service_label() -> None:
    payload = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {"metric": {"job": "finder"}, "value": [0, "1"]},
                {"metric": {"service": "monitor", "job": "monitor"}, "value": [0, "1"]},
            ],
        },
    }

    rows = service_info_by_service(payload)

    assert set(rows) == {"monitor"}
    assert rows["monitor"]["metric"]["job"] == "monitor"

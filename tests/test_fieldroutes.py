import json
from datetime import date

import pytest

from jarvis.connectors.base import EntityUnsupported
from jarvis.connectors.fieldroutes import FieldRoutesClient, ReadOnlyViolation


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


class FakeHTTP:
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def post(self, url, data, timeout):
        self.calls.append((url, data))
        return self.handler(url, data)


def make(handler):
    http = FakeHTTP(handler)
    return FieldRoutesClient("thedefenders", "KEY", "TOKEN", office_ids=["1"], session=http), http


def test_write_endpoints_are_refused():
    client, http = make(lambda u, d: FakeResp(200, {"success": True}))
    for path in ("customer/update", "appointment/create", "payment/charge", "customer/delete"):
        with pytest.raises(ReadOnlyViolation):
            client._call(path, {})
    assert http.calls == []


def test_search_then_get_and_mapping():
    def handler(url, data):
        if url.endswith("appointment/search"):
            assert json.loads(data["date"])["operator"] == "BETWEEN"
            assert data["authenticationKey"] == "KEY"
            return FakeResp(200, {"success": True, "appointmentIDs": [1, 2], "count": 2})
        assert url.endswith("appointment/get")
        assert json.loads(data["appointmentIDs"]) == ["1", "2"]
        return FakeResp(200, {"success": True, "appointments": [
            {"appointmentID": 1, "officeID": 1, "customerID": 9, "date": "2026-10-09", "dateCompleted": "2026-10-09 14:02:00",
             "status": "1", "servicedBy": 77},
            {"appointmentID": 2, "officeID": 1, "customerID": 8, "date": "2026-10-09", "dateCompleted": "0000-00-00 00:00:00",
             "status": "0", "employeeID": 78}]})

    client, _ = make(handler)
    rows = client.fetch("appointments", date(2026, 10, 9), date(2026, 10, 9))
    assert [r["status"] for r in rows] == ["completed", "pending"]
    assert rows[0]["technician_source_id"] == "77" and rows[1]["technician_source_id"] == "78"
    assert rows[1]["completed_date"] is None


def test_credentials_never_in_url():
    client, http = make(lambda u, d: FakeResp(200, {"success": True, "employeeIDs": [], "count": 0}))
    client.fetch("employees", date(2026, 10, 9), date(2026, 10, 9))
    assert all("KEY" not in url and "TOKEN" not in url for url, _ in http.calls)


def test_permission_error_means_unsupported():
    client, _ = make(lambda u, d: FakeResp(403, {"success": False}))
    with pytest.raises(EntityUnsupported):
        client.fetch("payments", date(2026, 10, 9), date(2026, 10, 9))


def test_truncated_search_fails_loudly():
    client, _ = make(lambda u, d: FakeResp(200, {"success": True, "ticketIDs": [1], "count": 50001}))
    with pytest.raises(Exception, match="narrow the window"):
        client.fetch("invoices", date(2026, 10, 1), date(2026, 10, 9))

import datetime
import json
import re
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import driver  # noqa: E402
from autoquery import queries  # noqa: E402

TRIPINFO = Path(__file__).resolve().parents[2] / "ts-common/src/main/java/edu/fudan/common/entity/TripInfo.java"

TRIPS_URL = "http://ts-ui-dashboard:8080/api/v1/travelservice/trips/left"
RESERVED = {"status", "msg", "message", "level", "severity"}


def response(url, status_code=200, body=b"", method="GET", ms=120):
    r = requests.Response()
    r.url = url
    r.status_code = status_code
    r._content = body if isinstance(body, bytes) else json.dumps(body).encode()
    r.elapsed = datetime.timedelta(milliseconds=ms)
    r.request = requests.Request(method, url).prepare()
    return r


def trip(economy, comfort):
    return {"tripId": {"type": "G", "number": "1234"}, "priceForEconomyClass": economy, "priceForConfortClass": comfort}


def test_normalize_path_replaces_ids_and_numbers():
    url = "http://x/api/v1/cancelservice/cancel/5ad7750b-a68b-49c0-a8c0-32776b067703/4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f"
    assert driver.normalize_path(url) == "/api/v1/cancelservice/cancel/{id}/{id}"
    assert driver.normalize_path("http://x/drawback/4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f/50.0") == "/drawback/{id}/{n}"


def test_outcome_reports_business_rejection_behind_http_200():
    body = {"status": 0, "msg": "Order cancel rejected: station locked", "data": None}
    out = driver.outcome(response("http://x/api/v1/cancelservice/cancel/a/b", body=body))
    assert (out["http_status"], out["tt_status"], out["tt_msg"]) == (200, 0, "Order cancel rejected: station locked")
    assert out["evt"] == "outcome" and out["method"] == "GET" and out["duration_ms"] == 120


def test_outcome_survives_non_json_and_list_bodies():
    html = driver.outcome(response("http://x/api/v1/preserveservice/preserve", 413, b"<html>413</html>", "POST"))
    assert (html["http_status"], html["tt_status"], html["tt_msg"]) == (413, None, "")
    listed = driver.outcome(response("http://x/api/v1/foo", body=[1, 2]))
    assert listed["tt_status"] is None


def test_outcome_avoids_datadog_reserved_attributes():
    assert not RESERVED & driver.outcome(response("http://x/y", body={"status": 1})).keys()


def test_fare_anomaly_when_economy_is_not_below_comfort():
    body = {"status": 1, "data": [trip("50.0", "50.0"), trip("19.0", "50.0")]}
    anomalies = driver.price_anomalies(response(TRIPS_URL, body=body, method="POST"))
    assert anomalies == [{"evt": "fare_anomaly", "trip": {"type": "G", "number": "1234"}, "economy": 50.0, "comfort": 50.0}]


def test_fare_check_ignores_blank_prices_other_paths_and_empty_data():
    assert driver.price_anomalies(response(TRIPS_URL, body={"status": 1, "data": [trip("", "50.0"), trip(None, None)]})) == []
    assert driver.price_anomalies(response("http://x/api/v1/orderservice/order/refresh", body={"data": [trip("50.0", "50.0")]})) == []
    assert driver.price_anomalies(response(TRIPS_URL, body={"status": 0, "data": None})) == []
    assert driver.price_anomalies(response(TRIPS_URL, 500, b"oops")) == []


def test_log_response_writes_json_lines(monkeypatch):
    lines = []
    monkeypatch.setattr(driver.outcome_log, "info", lines.append)
    monkeypatch.setattr(driver.outcome_log, "warning", lines.append)
    driver.log_response(response(TRIPS_URL, body={"status": 1, "data": [trip("50.0", "50.0")]}, method="POST"))
    assert [json.loads(line)["evt"] for line in lines] == ["outcome", "fare_anomaly"]


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return response(url, body={"status": 1}, method="POST")


class FakeQuery:
    uid = "user-1"

    def __init__(self, pairs=None):
        self.pairs = pairs
        self.session = FakeSession()

    def query_orders(self, types=(0, 1), query_other=False):
        return self.pairs


def test_voucher_scenario_asks_for_a_paid_high_speed_order():
    q = FakeQuery(pairs=[("o1", "G1234")])
    driver.query_and_get_voucher(q)
    method, url, kwargs = q.session.calls[0]
    assert (method, url) == ("POST", driver.VOUCHER_URL)
    assert kwargs["json"] == {"orderId": "o1", "type": 1}
    assert kwargs["timeout"] == driver.VOUCHER_TIMEOUT_SECONDS


def test_voucher_scenario_skips_when_there_are_no_orders():
    q = FakeQuery(pairs=None)
    driver.query_and_get_voucher(q)
    assert q.session.calls == []


def test_trip_date_follows_the_services_shanghai_day():
    # Live run: autoquery fixes its date at import, and the travel service (Asia/Shanghai) refuses trips dated before
    # its today. From 16:00 UTC, Shanghai's midnight, every preserve failed with "Cannot choose from an empty sequence".
    utc = datetime.timezone.utc
    assert driver.service_date(datetime.datetime(2026, 9, 27, 15, 59, tzinfo=utc)) == "2026-09-27"
    assert driver.service_date(datetime.datetime(2026, 9, 27, 16, 0, tzinfo=utc)) == "2026-09-28"


def test_each_scenario_runs_with_the_services_current_date(monkeypatch):
    seen = []
    dates = iter(["2026-09-27", "2026-09-28"])
    monkeypatch.setattr(queries, "datestr", queries.datestr)
    monkeypatch.setattr(driver, "login", FakeQuery)
    monkeypatch.setattr(driver, "service_date", lambda now: next(dates))
    monkeypatch.setattr(driver, "WEIGHTS", {lambda q: seen.append(queries.datestr): 1})

    def stop_after_two(seconds):
        if len(seen) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(driver.time, "sleep", stop_after_two)
    with pytest.raises(KeyboardInterrupt):
        driver.main()
    assert seen == ["2026-09-27", "2026-09-28"]


def test_weights_include_the_lab_scenarios():
    assert driver.WEIGHTS[driver.query_and_get_voucher] > 0
    assert all(w > 0 for w in driver.WEIGHTS.values())


def test_trip_queries_send_the_fields_tripinfo_binds():
    # Live run: auto-query sends startingPlace, but this version's TripInfo binds startPlace. The controller then
    # sees no start place and answers a bare [], so the driver never books an order and never asks for a voucher.
    fields = set(re.findall(r"private \w+ (\w+);", TRIPINFO.read_text()))
    sent = []
    q = queries.Query("http://ts-ui-dashboard:8080")
    q.session.post = lambda url, **kw: sent.append(kw["json"]) or response(url, body={"data": []}, method="POST")
    q.query_high_speed_ticket(("Shang Hai", "Su Zhou"))
    q.query_normal_ticket(("Shang Hai", "Nan Jing"))
    q.query_high_speed_ticket_parallel(("Shang Hai", "Su Zhou"))
    q.query_advanced_ticket(("Shang Hai", "Su Zhou"))
    assert len(sent) == 4
    for payload in sent:
        assert {"startPlace", "endPlace", "departureTime"} <= set(payload) and set(payload) <= fields, payload

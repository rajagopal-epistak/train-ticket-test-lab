import json
import logging
import os
import random
import re
import time
from urllib.parse import urlsplit

from autoquery import scenarios
from autoquery.queries import Query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("tt-traffic-driver")

# One JSON line per HTTP call so Datadog parses the fields without a pipeline.
# Field names avoid Datadog's reserved attributes (status, msg, message, level).
outcome_log = logging.getLogger("tt-outcome")
outcome_log.propagate = False
_outcome_handler = logging.StreamHandler()
_outcome_handler.setFormatter(logging.Formatter("%(message)s"))
outcome_log.addHandler(_outcome_handler)
outcome_log.setLevel(logging.INFO)

URL = os.environ.get("TT_URL", "http://ts-ui-dashboard:8080")
# The dashboard's nginx only proxies /api/v1/ and the deployed gateway has no /getVoucher route.
VOUCHER_URL = os.environ.get("VOUCHER_URL", "http://ts-voucher-service:16101/getVoucher")
INTERVAL = float(os.environ.get("INTERVAL_SECONDS", "1"))
VOUCHER_TIMEOUT_SECONDS = 15  # a slow voucher lookup must be measured, not abandoned
RELOGIN_SECONDS = 1800  # auth tokens expire after 1 h
HEARTBEAT_EVERY = 50

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
NUMBER_SEGMENT_RE = re.compile(r"/\d+(\.\d+)?(?=/|$)")


def normalize_path(url):
    path = UUID_RE.sub("{id}", urlsplit(url).path)
    return NUMBER_SEGMENT_RE.sub("/{n}", path)


def _json_body(response):
    try:
        return response.json()
    except ValueError:
        return None


def outcome(response):
    body = _json_body(response)
    is_dict = isinstance(body, dict)
    return {
        "evt": "outcome",
        "method": response.request.method,
        "path": normalize_path(response.url),
        "http_status": response.status_code,
        "tt_status": body.get("status") if is_dict else None,
        "tt_msg": str(body.get("msg") or "")[:200] if is_dict else "",
        "duration_ms": int(response.elapsed.total_seconds() * 1000),
    }


def _price(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Fare invariant: an economy seat must cost less than a comfort seat on the same trip.
def price_anomalies(response):
    if not urlsplit(response.url).path.endswith("/trips/left"):
        return []
    body = _json_body(response)
    trips = body.get("data") if isinstance(body, dict) else None
    anomalies = []
    for trip in trips if isinstance(trips, list) else []:
        if not isinstance(trip, dict):
            continue
        economy = _price(trip.get("priceForEconomyClass"))
        comfort = _price(trip.get("priceForConfortClass"))
        if economy is not None and comfort is not None and 0 < comfort <= economy:
            anomalies.append({"evt": "fare_anomaly", "trip": trip.get("tripId"), "economy": economy, "comfort": comfort})
    return anomalies


def log_response(response, *args, **kwargs):
    outcome_log.info(json.dumps(outcome(response), separators=(",", ":")))
    for anomaly in price_anomalies(response):
        outcome_log.warning(json.dumps(anomaly, separators=(",", ":")))


# Voucher lookups for paid high-speed orders.
def query_and_get_voucher(q):
    pairs = q.query_orders(types=tuple([1]))
    if not pairs:
        return
    order_id, trip_id = random.choice(pairs)
    q.session.post(VOUCHER_URL, json={"orderId": order_id, "type": 1 if trip_id[:1] in ("G", "D") else 0},
                   timeout=VOUCHER_TIMEOUT_SECONDS)


WEIGHTS = {
    scenarios.query_and_preserve: 4,  # creates the orders the other scenarios act on
    scenarios.query_and_pay: 2,
    scenarios.query_and_collect: 1,
    scenarios.query_and_execute: 1,
    scenarios.query_and_cancel: 1,
    scenarios.query_and_rebook: 1,
    scenarios.query_and_consign: 1,
    query_and_get_voucher: 1,
}


def login():
    while True:
        q = Query(URL)
        q.session.hooks["response"].append(log_response)
        try:
            if q.login():
                return q
        except Exception:
            log.exception("login raised")
        time.sleep(10)


def main():
    q, logged_in_at = login(), time.monotonic()
    runs = errors = 0
    while True:
        scenario = random.choices(list(WEIGHTS), weights=list(WEIGHTS.values()))[0]
        try:
            scenario(q)
        except Exception:
            errors += 1
            log.exception("%s raised", scenario.__name__)
        runs += 1
        if runs % HEARTBEAT_EVERY == 0:
            log.info("heartbeat runs=%d errors=%d", runs, errors)
        if time.monotonic() - logged_in_at > RELOGIN_SECONDS:
            q, logged_in_at = login(), time.monotonic()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()

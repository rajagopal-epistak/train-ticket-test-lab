import json
import re
import sys
import types
from pathlib import Path

VOUCHER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VOUCHER))


class StubFlags:
    enabled = frozenset()

    def is_enabled(self, name):
        return name in self.enabled


# server.py builds its flagd client at import; stub it so the test needs no flagd.
sys.modules["feature_flag_service"] = types.SimpleNamespace(FeatureFlagService=StubFlags)
import server  # noqa: E402

SCHEMA = re.findall(r"^\s+(\w+) (?:INT|VARCHAR|FLOAT)", (VOUCHER / "server.py").read_text(), re.M)
ROW = (7, "o1", "2026-09-26", "09:00", "Contact", "G1234", 2, "5", "Shang Hai", "Su Zhou", 100.0)


class FakeCursor:
    def __init__(self):
        self.sql = None
        self.rowcount = 0

    def execute(self, sql, args):
        self.sql = sql
        self.rowcount = 1

    def fetchone(self):
        return ROW


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def close(self):
        pass


def lookup(monkeypatch, flags):
    cursor = FakeCursor()
    monkeypatch.setattr(server.pymysql, "connect", lambda **kwargs: FakeConnection(cursor))
    monkeypatch.setattr(server.feature_flag_service, "enabled", frozenset(flags))
    result = server.GetVoucherHandler.fetchVoucherByOrderId(None, "o1")
    column = re.search(r"where (\w+) = %s", cursor.sql).group(1)
    return column, result


def test_schema_is_read_from_the_create_table_statement():
    assert "order_id" in SCHEMA and "voucher_id" in SCHEMA


def test_flag_off_looks_up_by_a_real_column_and_returns_the_voucher(monkeypatch):
    column, result = lookup(monkeypatch, [])
    assert column in SCHEMA
    assert json.loads(result)["order_id"] == "o1"


def test_f22_looks_up_by_a_column_the_table_lacks(monkeypatch):
    column, _ = lookup(monkeypatch, ["tt-feat-22"])
    assert column not in SCHEMA


def test_other_flags_leave_the_lookup_alone(monkeypatch):
    column, _ = lookup(monkeypatch, ["tt-feat-17"])
    assert column == "order_id"

"""The discount rules, tested as pure logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import discounts as d

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def rule(**kw):
    base = {
        "code": "SAVE10",
        "kind": "percent",
        "value": 10,
        "active": True,
        "perCustomerOnce": True,
    }
    return base | kw


def test_percent_and_fixed():
    assert d.amount_off(rule(), 5000) == 500
    assert d.amount_off(rule(kind="fixed", value=700), 5000) == 700


def test_percent_rounds_down_never_up():
    assert (
        d.amount_off(rule(value=15), 999) == 149
    )  # 149.85 -> 149, the customer is never over-credited


def test_never_more_than_the_items_cost():
    assert d.amount_off(rule(kind="fixed", value=5000), 1200) == 1200
    assert d.amount_off(rule(value=90), 100) == 90


def test_max_discount_cap():
    assert d.amount_off(rule(value=50, maxDiscount=1000), 10000) == 1000


def test_zero_subtotal_is_zero():
    assert d.amount_off(rule(), 0) == 0


@pytest.mark.parametrize("sub", [1, 7, 99, 1234, 99999])
def test_never_negative_and_never_above_subtotal(sub):
    for r in (rule(), rule(kind="fixed", value=500), rule(value=90, maxDiscount=3)):
        assert 0 <= d.amount_off(r, sub) <= sub


def test_valid_code_applies():
    assert d.check(rule(), 5000, 0, False, NOW) == (500, None)


@pytest.mark.parametrize(
    ("r", "why"),
    [
        (None, "not valid"),
        (rule(active=False), "not valid"),
        (rule(startsAt=(NOW + timedelta(days=1)).isoformat()), "not active yet"),
        (rule(endsAt=(NOW - timedelta(seconds=1)).isoformat()), "expired"),
        (rule(endsAt=NOW.isoformat()), "expired"),
        (rule(maxUses=5), "fully used"),
        (rule(minOrder=9000), "at least ₦9,000"),
    ],
)
def test_codes_that_do_not_apply_say_why(r, why):
    off, msg = d.check(r, 5000, 5, False, NOW)
    assert off == 0 and why in msg


def test_one_use_per_customer():
    assert d.check(rule(), 5000, 1, True, NOW)[0] == 0
    assert d.check(rule(perCustomerOnce=False), 5000, 1, True, NOW)[0] == 500


def test_use_limit_boundary():
    r = rule(maxUses=3)
    assert d.check(r, 5000, 2, False, NOW)[0] == 500
    assert d.check(r, 5000, 3, False, NOW)[0] == 0


def test_dates_with_z_suffix_and_naive_are_understood():
    assert d.check(rule(endsAt="2026-11-22T00:00:00Z"), 5000, 0, False, NOW)[0] == 500
    assert d.check(rule(endsAt="2026-11-22T00:00:00"), 5000, 0, False, NOW)[0] == 500
    assert d.check(rule(endsAt="2026-11-20T00:00:00Z"), 5000, 0, False, NOW)[0] == 0


@pytest.mark.parametrize("raw", ["save10", " Save 10 ", "SAVE10", "save\t10"])
def test_codes_are_case_and_space_insensitive(raw):
    assert d.normalise(raw) == "SAVE10"


GOOD = {"code": "welcome10", "kind": "percent", "value": 10}


def test_definition_cleans_and_defaults():
    r, p = d.validate_definition(GOOD)
    assert (
        p is None
        and r["code"] == "WELCOME10"
        and r["perCustomerOnce"] is True
        and r["active"] is True
    )
    assert r["minOrder"] is None and r["maxUses"] is None


@pytest.mark.parametrize(
    "patch",
    [
        {"code": ""},
        {"code": "ab"},
        {"code": "x" * 25},
        {"code": "bad code!"},
        {"code": "<script>"},
        {"kind": "bogus"},
        {"kind": None},
        {"value": 0},
        {"value": -5},
        {"value": 1.5},
        {"value": "10"},
        {"value": True},
        {"value": 91},
        {"minOrder": -1},
        {"minOrder": "abc"},
        {"maxUses": 0.5},
        {"maxDiscount": -3},
        {"startsAt": "not a date"},
        {"endsAt": "2020-01-01", "startsAt": "2021-01-01"},
    ],
)
def test_bad_definitions_are_refused(patch):
    r, p = d.validate_definition(GOOD | patch)
    assert r is None and p


def test_fixed_amount_may_exceed_ninety():
    assert d.validate_definition({"code": "FLAT500", "kind": "fixed", "value": 500})[1] is None

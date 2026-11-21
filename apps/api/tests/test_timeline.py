"""The tracking timeline must reflect the order's real state and never invent progress or times."""

from __future__ import annotations

import pytest

from app import order_status as S


def steps(**order):
    return S.timeline({"date": "2026-11-21T00:00:00Z", "paymentDetail": {}, **order})


def labels(t):
    return [x["label"] for x in t]


def states(t):
    return {x["label"]: x["state"] for x in t}


def test_a_pay_on_delivery_order_has_no_payment_step():
    t = steps(status=S.AWAITING, payMethod="delivery")
    assert "Payment confirmed" not in labels(t) and "Waiting for your payment" not in labels(t)
    assert labels(t) == [
        "Order received",
        "Order processing",
        "Ready for dispatch",
        "Out for delivery",
        "Delivered",
    ]


def test_an_unpaid_pay_ahead_order_says_it_is_waiting_for_payment():
    t = steps(status=S.AWAITING_PAYMENT, payMethod="before")
    assert states(t)["Waiting for your payment"] == "current"
    assert states(t)["Order received"] == "done"
    assert states(t)["Payment confirmed"] == "upcoming"
    assert all(
        x["state"] == "upcoming" for x in t if x["label"] in ("Order processing", "Delivered")
    )


@pytest.mark.parametrize(
    ("status", "current"),
    [
        (S.PAID, "Payment confirmed"),
        (S.PREPARING, "Order processing"),
        (S.READY, "Ready for dispatch"),
        (S.OUT, "Out for delivery"),
    ],
)
def test_exactly_one_step_is_current_and_everything_before_it_is_done(status, current):
    t = steps(status=status, payMethod="before", paymentDetail={"paidAt": "2026-11-21T01:00:00Z"})
    cur = [x for x in t if x["state"] == "current"]
    assert [x["label"] for x in cur] == [current]
    idx = labels(t).index(current)
    assert all(x["state"] == "done" for x in t[:idx])
    assert all(x["state"] == "upcoming" for x in t[idx + 1 :])


def test_delivered_means_every_step_is_done_and_none_is_pending():
    t = steps(status=S.DELIVERED, payMethod="before", paymentDetail={"paidAt": "x"})
    assert {x["state"] for x in t} == {"done"}


def test_a_cancelled_order_shows_only_that_it_was_cancelled():
    t = steps(status=S.CANCELLED, payMethod="before")
    assert t == [{"label": "Order cancelled", "state": "cancelled", "when": None}]


def test_times_are_only_shown_when_really_recorded():
    t = steps(
        status=S.PREPARING, payMethod="before", paymentDetail={"paidAt": "2026-11-21T01:00:00Z"}
    )
    when = {x["label"]: x["when"] for x in t}
    assert when["Order received"] == "2026-11-21T00:00:00Z"
    assert when["Payment confirmed"] == "2026-11-21T01:00:00Z"
    assert when["Order processing"] is None and when["Delivered"] is None, "no invented times"


def test_an_unknown_status_does_not_crash_or_claim_progress():
    t = steps(status="Something odd", payMethod="delivery")
    assert t[0]["state"] == "current" and all(x["state"] == "upcoming" for x in t[1:])


def test_old_orders_without_a_pay_method_still_render():
    assert steps(status=S.AWAITING) and steps(status=S.PAID)


def test_ready_for_dispatch_sits_between_processing_and_out_for_delivery():
    assert S.STAFF_NEXT[S.PREPARING] == [S.READY, S.CANCELLED]
    assert S.STAFF_NEXT[S.READY] == [S.OUT, S.CANCELLED]
    assert (
        S.PROGRESS[S.PREPARING] < S.PROGRESS[S.READY] < S.PROGRESS[S.OUT] < S.PROGRESS[S.DELIVERED]
    )
    assert not S.staff_may_move(S.PREPARING, S.OUT), "cannot skip packing"


def test_the_tracking_page_renders_the_timeline_from_the_database(client):
    signup = {
        "name": "Ada",
        "phone": "08011111111",
        "email": "ada@example.com",
        "password": "secret123",
        "passwordConfirm": "secret123",
    }
    client.post("/api/auth/signup", json=signup)
    o = client.post(
        "/api/orders",
        json={
            "items": [{"productId": "p1", "optionIndex": 0, "qty": 1}],
            "address": "12 Market Rd",
            "phone": "08022222222",
            "city": "Otukpo",
            "payMethod": "before",
        },
    ).json()["order"]
    html = client.post("/ui/track", data={"order_id": o["id"], "phone": "08022222222"}).text
    assert 'class="timeline"' in html and "Waiting for your payment" in html
    assert 'aria-current="step"' in html
    wrong = client.post("/ui/track", data={"order_id": o["id"], "phone": "08099999999"}).text
    assert 'class="timeline"' not in wrong, "a wrong phone number must not reveal the order"

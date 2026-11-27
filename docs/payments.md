# Payments (Monnify bank transfer)

Pay-before-delivery orders can be paid by a one-time bank transfer account from Monnify. Pay on
Delivery and the store's own static bank details are unchanged and still work when Monnify is not
configured.

## The flow

1. The order is created first, with its stock reserved.
2. `POST /api/payments/{order_id}/new-account` (or checkout) mints a payment reference, then asks
   Monnify for a one-time account. Only one attempt runs at a time per order.
3. The customer transfers into that account. The account expires after the duration Monnify gives
   us (40 minutes in practice).
4. Settlement happens only from a verified server-side source: a signed webhook whose payment is
   re-queried from Monnify, or the customer's poll, which queries Monnify too. Nothing the browser
   says can mark an order paid.

## Money accounting

`paymentDetail.monnify.history[]` keeps every attempt (reference, transaction reference, expected
amount, account, expiry, status). Settlement adds up every verified receipt across the current and
historical attempts, each attempt counted once:

- `paidAmount` is the cumulative amount received.
- `overpaidBy` is the excess over the order total.
- An overpaid order carries an open reconciliation issue and **cannot move to a fulfilment status**
  (`Preparing your order`, `Ready for dispatch`, `Out for delivery`, `Delivered`) until a staff
  member resolves it with `POST /api/store/admin/orders/{order_id}/resolve-payment` and a note.
  The rule is enforced in the API, not in the admin page.

Discrepancies (currency, method, contract, order metadata, transaction reference, overpayment,
unmatched money) are stored in `paymentDetail.reconciliationIssues[]`, each with a stable id and
its own resolution record. A new discrepancy never replaces an unresolved earlier one, and
resolving one issue never closes another.

## Polling and manual checks

The customer page polls `GET /api/payments/{order_id}` at most every 5 seconds, which queries the
current attempt. Every 60 seconds, and whenever the customer presses **Check payment**
(`?check=1`), one older unpaid attempt is queried as well, so money sent to a replaced account is
found without waiting for its webhook.

Manual checks have their own budget: 5 per order per 60 seconds. Beyond that the API answers 429
with a `retryAfter` value and makes no Monnify call. Normal polling is unaffected.

## Reservation sweeper

When a temporary Monnify outage stops an account being created, the order is kept with its stock
reserved for 15 minutes (`paymentDetail.reservationExpiresAtEpoch`). Expiry is claimed atomically
(one status transition, one stock release), so it can never release stock twice.

How it is actually run:

- An **in-process task** started in the application lifespan (`reservation_sweeper`) sweeps every
  60 seconds **while the Render instance is running**. It sweeps once immediately at startup.
- Checkout also performs a bounded sweep (10 orders) before reserving stock, so a stale
  reservation left behind by a restart or a quiet period is cleaned up on the next order.
- This is **not** an external cron and not an always-on scheduler. A Render free instance sleeps
  after inactivity: while it is asleep the task does not run and no sweep happens. On wake the
  app starts, the lifespan task runs, and it sweeps immediately. Nothing is lost, but a
  reservation can outlive its 15 minutes until the service next runs.

# Orders, tracking and cancellation

## Lifecycle

An order starts as **Payment confirmed** (paid ahead) or **Awaiting delivery — pay on arrival**, then moves forward one step at a time.

| From | Staff can move it to |
| --- | --- |
| Payment confirmed / Awaiting delivery | Preparing your order, Cancelled |
| Preparing your order | Out for delivery, Cancelled |
| Out for delivery | Delivered |
| Delivered, Cancelled | nothing (final) |

Staff cannot skip a step, for example from Preparing straight to Delivered. The rules live in one file, `apps/api/app/order_status.py`, and the staff screen, customer screen and API all read from it.

Statuses are plain text in the existing `orders.status` column, so no database migration is needed. Orders placed before this feature keep working.

## Staff

Open **Store SMS inbox** in the footer and enter the staff key. Each order shows buttons for the moves that are allowed. A move only applies if the order is still in the status staff were looking at, so two staff clicking at once cannot push an order into a wrong state.

Cancelling a prepaid order shows a reminder to arrange a refund. Payments are simulated in this project, so nothing is refunded automatically.

## Customers

- **Cancel:** a signed-in customer can cancel their own order while it is Payment confirmed, Awaiting delivery or Preparing. After it leaves the store, the button is gone and the server refuses the request. Asking to cancel another customer's order gives the same "not found" answer as an order that does not exist.
- **Progress bar:** the order list shows a progress bar that follows the status. Cancelled orders show no bar.

## Track without signing in

**Track order** in the header asks for the order reference and the phone number used on the order. Both must match (the last 9 digits are compared, so `0803...` and `+234803...` both work). A wrong guess shows a generic message, the page never shows the address or phone, and the endpoint allows 10 attempts per minute per client.

## Not included

Stock levels are not tracked. Adding them needs a new column or table, which is a database change on a live Postgres, so it was left out on purpose.

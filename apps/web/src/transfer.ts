import { errorMessage } from "./api";
import { $, clear, h, money } from "./dom";
import type { MonnifyPayment } from "./types";

/** The one-time Monnify transfer account for a pay-before-delivery order.
 *
 * The server owns the truth: this panel shows what it returned, counts the account down
 * locally so the customer is never surprised by an expiry, and asks the server for the
 * payment status on a slow poll. Nothing here can mark an order paid. */

const POLL_MS = 10_000;

let current: MonnifyPayment | null = null;
let orderId = "";
let countdown: number | undefined;
let poller: number | undefined;

function panel(): HTMLElement {
  return $("payPanel");
}

export function stopPaymentPanel(): void {
  if (countdown !== undefined) window.clearInterval(countdown);
  if (poller !== undefined) window.clearInterval(poller);
  countdown = undefined;
  poller = undefined;
  current = null;
  const box = document.getElementById("payPanel");
  if (box) {
    clear(box);
    box.hidden = true;
  }
}

function isOpenStatus(status: string): boolean {
  return status === "PENDING" || status === "CREATING";
}

function row(label: string, value: string, extra?: HTMLElement): HTMLElement {
  return h(
    "div",
    { class: "pay-row" },
    h("span", { class: "muted", text: label }),
    extra ?? h("strong", { text: value }),
  );
}

async function copy(text: string, button: HTMLButtonElement): Promise<void> {
  const label = button.textContent;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied ✓";
  } catch {
    button.textContent = "Press and hold to copy";
  }
  window.setTimeout(() => {
    button.textContent = label;
  }, 2000);
}

function render(payment: MonnifyPayment): void {
  current = payment;
  const box = panel();
  clear(box);
  box.hidden = false;

  const status = String(payment.status || "PENDING").toUpperCase();
  box.append(
    h("div", { class: `pay-status ${status.toLowerCase()}`, text: statusLabel(status) }),
  );
  box.append(h("p", { class: "small-note", text: payment.message || "" }));

  if (payment.accountNumber) {
    box.append(row("Bank", payment.bank || "—"));
    box.append(row("Account name", payment.accountName || "—"));
    const numberEl = h("strong", { class: "pay-account", text: payment.accountNumber });
    box.append(row("Account number", payment.accountNumber, numberEl));
    box.append(row("Send exactly", money(payment.amount)));
    box.append(row("Order reference", payment.paymentReference || orderId));

    const copyBtn = h("button", {
      class: "btn-ghost",
      type: "button",
      text: "Copy account number",
    }) as HTMLButtonElement;
    copyBtn.onclick = () => void copy(payment.accountNumber, copyBtn);
    box.append(copyBtn);

    const expiry = h("div", { class: "pay-expiry" });
    box.append(expiry);
    renderExpiry(expiry, payment);
  }

  if (status === "EXPIRED" || status === "FAILED" || status === "REVERSED") {
    const again = h("button", {
      class: "btn-primary",
      type: "button",
      text: "Get a new account",
    }) as HTMLButtonElement;
    again.onclick = () => void requestNewAccount(again);
    box.append(again);
  }

  if (isOpenStatus(status) && payment.accountNumber) {
    const sent = h("button", {
      class: "btn-ghost",
      type: "button",
      text: "I have sent it — check now",
    }) as HTMLButtonElement;
    sent.onclick = () => void checkNow(sent);
    box.append(sent);
  }
}

function statusLabel(status: string): string {
  if (status === "PAID" || status === "OVERPAID") return "Payment confirmed";
  if (status === "PARTIALLY_PAID") return "Part payment received";
  if (status === "EXPIRED") return "Account expired";
  if (status === "FAILED") return "Payment failed";
  if (status === "REVERSED") return "Payment reversed";
  if (status === "CREATING") return "Setting up your account";
  return "Awaiting your transfer";
}

function renderExpiry(el: HTMLElement, payment: MonnifyPayment): void {
  clear(el);
  const status = String(payment.status || "").toUpperCase();
  if (!isOpenStatus(status)) return;
  const left = Math.max(0, Math.floor(payment.secondsLeft));
  if (left <= 0) {
    el.textContent = "This account has expired. Request a new one.";
    return;
  }
  const mins = Math.floor(left / 60);
  const secs = left % 60;
  el.textContent = `This account is valid for ${mins}:${String(secs).padStart(2, "0")} more.`;
}

function tick(): void {
  if (!current) return;
  current = { ...current, secondsLeft: Math.max(0, current.secondsLeft - 1) };
  const el = panel().querySelector<HTMLElement>(".pay-expiry");
  if (el) renderExpiry(el, current);
}

async function fetchStatus(): Promise<MonnifyPayment | null> {
  if (!orderId) return null;
  try {
    const res = await fetch(`/api/payments/${encodeURIComponent(orderId)}`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { payment?: MonnifyPayment | null };
    return data.payment ?? null;
  } catch {
    return null;
  }
}

function apply(payment: MonnifyPayment): void {
  render(payment);
  if (!isOpenStatus(String(payment.status).toUpperCase())) {
    if (poller !== undefined) window.clearInterval(poller);
    poller = undefined;
  }
  if (String(payment.status).toUpperCase() === "EXPIRED" && countdown !== undefined) {
    window.clearInterval(countdown);
    countdown = undefined;
  }
}

async function checkNow(button: HTMLButtonElement): Promise<void> {
  button.disabled = true;
  button.textContent = "Checking…";
  const fresh = await fetchStatus();
  if (fresh) apply(fresh);
  button.disabled = false;
  button.textContent = "I have sent it — check now";
}

async function requestNewAccount(button: HTMLButtonElement): Promise<void> {
  button.disabled = true;
  button.textContent = "Creating a new account…";
  try {
    const res = await fetch(`/api/payments/${encodeURIComponent(orderId)}/new-account`, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const data = (await res.json()) as { payment?: MonnifyPayment | null; error?: string };
    if (!res.ok || !data.payment) {
      button.disabled = false;
      button.textContent = "Get a new account";
      const box = panel();
      box.append(
        h("p", {
          class: "msg error",
          text: errorMessage({ message: data.error ?? "" }, "Could not create a new account."),
        }),
      );
      return;
    }
    apply(data.payment);
    startTimers();
  } catch {
    button.disabled = false;
    button.textContent = "Get a new account";
  }
}

function startTimers(): void {
  if (countdown !== undefined) window.clearInterval(countdown);
  if (poller !== undefined) window.clearInterval(poller);
  countdown = window.setInterval(tick, 1000);
  poller = window.setInterval(() => {
    void fetchStatus().then((fresh) => {
      if (fresh) apply(fresh);
    });
  }, POLL_MS);
}

/** Show the account for a freshly placed order and keep it up to date. */
export function showPaymentPanel(payment: MonnifyPayment): void {
  orderId = payment.orderId;
  render(payment);
  startTimers();
}

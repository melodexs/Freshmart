import { initCart, rehydrateGrid, setCheckoutHandler, setDeliveryFee } from "./cart";
import { configureCheckout, initCheckout, openCheckout } from "./checkout";
import { $, $maybe, clear, h, hide, money, show } from "./dom";
import type { PlacedOrder } from "./types";

/** Entry point. The server renders the pages (Jinja + HTMX); this file only
 * handles what needs the browser: the cart, checkout, modals and toasts. */

const LAST_EMAIL_KEY = "fm_last_email";
let signedIn = false;

// ---------- remembering the last email for quick sign-in ----------

function getLastEmail(): string {
  try {
    return localStorage.getItem(LAST_EMAIL_KEY) ?? "";
  } catch {
    return "";
  }
}
function setLastEmail(email: string): void {
  try {
    localStorage.setItem(LAST_EMAIL_KEY, email);
  } catch {
    /* private mode: quick sign-in just won't be remembered */
  }
}

// ---------- modals ----------

function openModal(id: string): void {
  show($(id));
}
function closeModal(el: HTMLElement): void {
  hide(el);
}

function initModals(): void {
  // Any button with data-open-modal opens that overlay (HTMX loads its content).
  document.addEventListener("click", (e) => {
    const target = e.target as HTMLElement | null;
    const opener = target?.closest<HTMLElement>("[data-open-modal]");
    if (opener?.dataset.openModal) openModal(opener.dataset.openModal);
    const closer = target?.closest<HTMLElement>("[data-close-modal]");
    if (closer) closeModal(closer.closest<HTMLElement>(".modal-overlay") ?? closer);
    // Click on the dim backdrop closes the modal.
    if (target?.classList.contains("modal-overlay")) closeModal(target);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      document.querySelectorAll<HTMLElement>(".modal-overlay.show").forEach(closeModal);
    }
  });
}

// ---------- toasts ----------

let successTimer: number | undefined;
function showSuccessToast(text: string): void {
  const t = $("successToast");
  t.textContent = "✅ " + text;
  t.style.display = "block";
  window.clearTimeout(successTimer);
  successTimer = window.setTimeout(() => (t.style.display = "none"), 2600);
}

let smsTimer: number | undefined;
function showSmsToast(text: string): void {
  const t = $("smsToast");
  clear(t);
  t.append("📩 ", h("strong", { text: "SMS sent to store" }), h("br"), text);
  t.style.display = "block";
  window.clearTimeout(smsTimer);
  smsTimer = window.setTimeout(() => (t.style.display = "none"), 6000);
}

// ---------- sign in / out state, driven by HX-Trigger events from the server ----------

function syncSignedIn(): void {
  signedIn = $maybe("logoutBtn") !== null;
}

function promptSignIn(message: string): void {
  openModal("authOverlay");
  const email = getLastEmail();
  // Ask the server for the sign-in form; it shows "Welcome back" when it knows the email.
  const url = email ? `/ui/signin?last=${encodeURIComponent(email)}` : "/ui/signin";
  const notice = $("authNotice");
  clear(notice);
  notice.append(h("div", { class: "msg ok", text: message }));
  window.htmx.ajax("GET", url, { target: "#authBody", swap: "innerHTML" });
}

function initAuthEvents(): void {
  // Opening "Sign in" from the header: include the remembered email.
  document.body.addEventListener("htmx:configRequest", (e) => {
    const detail = (e as CustomEvent).detail as { path: string; elt: HTMLElement; parameters: Record<string, string> };
    if (detail.elt.hasAttribute("data-last-email")) {
      const email = getLastEmail();
      if (email) detail.parameters["last"] = email;
      clear($("authNotice"));
    }
  });

  document.body.addEventListener("signed-in", (e) => {
    // The server puts the details in the HX-Trigger header (the swapped HTML isn't in the page yet).
    const detail = ((e as CustomEvent).detail ?? {}) as { email?: string; firstName?: string };
    const email = detail.email ?? "";
    const first = detail.firstName ?? "";
    if (email) setLastEmail(email);
    hide($("authOverlay"));
    hide($("signupOverlay"));
    clear($("authNotice"));
    // Refresh the header so it shows the signed-in buttons.
    window.htmx.ajax("GET", "/ui/header", { target: "#account-area", swap: "innerHTML" });
    showSuccessToast(`Login successful. Welcome, ${first}!`);
  });

  document.body.addEventListener("signed-out", () => {
    for (const id of ["ordersOverlay", "confirmOverlay", "checkoutOverlay"]) hide($(id));
    hide($("cartOverlay"));
    hide($("cartDrawer"));
  });

  // Keep `signedIn` accurate whenever the header is swapped.
  document.body.addEventListener("htmx:afterSwap", (e) => {
    const target = (e as CustomEvent).detail?.target as HTMLElement | undefined;
    if (target?.id === "account-area") syncSignedIn();
    if (target?.id === "catalog") rehydrateGrid();
  });
}

// ---------- order confirmation ----------

function showOrderPlaced(order: PlacedOrder): void {
  const items = order.items.map((i) => `${i.qty}x ${i.name}`).join(", ");
  const payLine = order.payMethod === "before" ? "PAID (before delivery)" : "Pay on delivery";
  showSmsToast(
    `New order ${order.id} — ${money(order.total)}. ${items}. Deliver to: ${order.address}, ${order.city}. Customer: ${order.phone}. ${payLine}.`,
  );

  const d = order.paymentDetail as Record<string, string | undefined>;
  let how = "You'll pay the rider on delivery.";
  if (order.payMethod === "before") {
    if (d.type === "card") how = `Paid ahead via card ending ${d.last4 ?? ""} (simulated).`;
    else if (d.type === "transfer") how = `Paid ahead via transfer from ${d.bank ?? ""} (simulated).`;
    else how = `Paid ahead via USSD via ${d.bank ?? ""} (simulated).`;
  }
  const text = $("confirmText");
  clear(text);
  text.append("Order ", h("strong", { text: order.id }), ` for ${money(order.total)} was placed.`, h("br"), how);
  show($("confirmOverlay"));
}

function init(): void {
  const cfg = $maybe("app-config")?.textContent;
  if (cfg) {
    const parsed = JSON.parse(cfg) as { deliveryFee?: number };
    if (typeof parsed.deliveryFee === "number") setDeliveryFee(parsed.deliveryFee);
  }
  syncSignedIn();
  initModals();
  initCart();
  initCheckout();
  initAuthEvents();
  setCheckoutHandler(openCheckout);
  configureCheckout({
    isSignedIn: () => signedIn,
    promptSignIn,
    onOrderPlaced: showOrderPlaced,
  });
  $("confirmClose").onclick = () => hide($("confirmOverlay"));
  rehydrateGrid();
}

document.addEventListener("DOMContentLoaded", init);

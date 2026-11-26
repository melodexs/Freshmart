import {
  addFromOrder,
  initCart,
  openCart,
  type ReorderLine,
  rehydrateGrid,
  setCheckoutHandler,
  setDeliveryFee,
} from "./cart";
import {
  configureCheckout,
  getBank,
  initCheckout,
  openCheckout,
  setAreas,
  setBankDetails,
  setMonnifyReady,
} from "./checkout";
import { showPaymentPanel, stopPaymentPanel } from "./transfer";
import { $, $maybe, clear, h, hide, money, show } from "./dom";
import type { MonnifyPayment, PlacedOrder } from "./types";

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

/** Who had focus before a dialog opened, so closing it can hand focus back. */
let lastOpener: HTMLElement | null = null;

const FOCUSABLE = "input, select, textarea, button:not([data-close-modal]), a[href]";

function openModal(id: string): void {
  lastOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const overlay = $(id);
  show(overlay);
  // Content may still be loading (HTMX), so focus the dialog itself first, then the first field.
  const dialog = overlay.querySelector<HTMLElement>(".modal");
  if (dialog) {
    dialog.tabIndex = -1;
    dialog.focus({ preventScroll: true });
    window.setTimeout(() => {
      const first = dialog.querySelector<HTMLElement>(FOCUSABLE);
      if (first && overlay.classList.contains("show")) first.focus({ preventScroll: true });
    }, 250);
  }
}
function closeModal(el: HTMLElement): void {
  hide(el);
  if (lastOpener && document.querySelectorAll(".modal-overlay.show").length === 0) {
    lastOpener.focus({ preventScroll: true });
    lastOpener = null;
  }
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

// ---------- reorder ----------

/** Read a JSON array from a data attribute. Bad or missing data gives an empty list. */
function readList(el: HTMLElement, name: string): unknown[] {
  try {
    const v: unknown = JSON.parse(el.dataset[name] ?? "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function initReorder(): void {
  document.addEventListener("click", async (e) => {
    const btn = (e.target as HTMLElement | null)?.closest<HTMLElement>(".reorder-btn");
    if (!btn) return;
    const ids = readList(btn, "reorder");
    const options = readList(btn, "reorderOptions");
    const qtys = readList(btn, "reorderQty");
    const wanted: ReorderLine[] = ids.map((id, i) => ({
      productId: String(id),
      optionIndex: Number(options[i]),
      qty: Number(qtys[i]),
    }));
    const { added, skipped } = await addFromOrder(wanted);
    const overlay = btn.closest<HTMLElement>(".modal-overlay");
    if (overlay) closeModal(overlay);
    if (added > 0) openCart();
    showSuccessToast(
      added === 0
        ? "Sorry, none of those items are available any more."
        : skipped > 0
          ? `${added} item${added === 1 ? "" : "s"} added. ${skipped} no longer sold.`
          : `${added} item${added === 1 ? "" : "s"} added to your cart.`,
      added > 0 && skipped === 0,
    );
  });
}

// ---------- toasts ----------

let successTimer: number | undefined;
function showSuccessToast(text: string, ok = true): void {
  const t = $("successToast");
  t.textContent = (ok ? "✅ " : "⚠️ ") + text;
  t.style.display = "block";
  window.clearTimeout(successTimer);
  successTimer = window.setTimeout(() => (t.style.display = "none"), 2600);
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
    // Every product-list request carries the chosen sort, whichever control triggered it.
    if (detail.path.startsWith("/ui/products")) {
      const sort = document.getElementById("sortSelect") as HTMLSelectElement | null;
      if (sort && !("sort" in detail.parameters)) detail.parameters["sort"] = sort.value;
    }
    if (detail.elt.hasAttribute("data-last-email")) {
      const email = getLastEmail();
      if (email) detail.parameters["last"] = email;
      clear($("authNotice"));
    }
  });

  document.body.addEventListener("need-signin", (e) => {
    const detail = ((e as CustomEvent).detail ?? {}) as { message?: string };
    promptSignIn(detail.message ?? "Please sign in to continue.");
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

function showOrderPlaced(order: PlacedOrder, payment: MonnifyPayment | null = null): void {
  const text = $("confirmText");
  clear(text);
  text.append("Order ", h("strong", { text: order.id }), ` for ${money(order.total)} was placed.`, h("br"));
  stopPaymentPanel();
  if (order.payMethod === "before" && payment) {
    text.append(
      "It is waiting for your payment. Transfer ",
      h("strong", { text: money(order.total) }),
      " to the one-time account below, using ",
      h("strong", { text: order.id }),
      " as the reference. We confirm it automatically.",
    );
  } else if (order.payMethod === "before") {
    const b = getBank();
    const accounts = b.accounts.length ? b.accounts : [b];
    text.append(
      "It is waiting for your payment. Transfer ",
      h("strong", { text: money(order.total) }),
      accounts.length > 1 ? " to any one of these accounts:" : " to ",
    );
    if (accounts.length > 1) {
      text.append(h("br"));
      accounts.forEach((a) => {
        text.append(h("strong", { text: `${a.accountNumber}, ${a.bank} (${a.accountName})` }), h("br"));
      });
    } else {
      text.append(h("strong", { text: `${b.accountNumber}, ${b.bank} (${b.accountName})` }));
    }
    text.append(
      " Use ",
      h("strong", { text: order.id }),
      " as the narration. We start packing as soon as we confirm the money.",
    );
  } else {
    text.append("You will pay the rider when your order arrives.");
  }
  const copy = $("copyRef");
  copy.textContent = "Copy order reference";
  copy.onclick = () => {
    void copyText(order.id).then((ok) => {
      copy.textContent = ok ? "Copied ✓" : `Reference: ${order.id}`;
    });
  };
  if (payment) showPaymentPanel(payment);
  show($("confirmOverlay"));
}

/** Copy text to the clipboard. Returns false if the browser refuses (e.g. no permission). */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function initBackToTop(): void {
  const btn = $("backToTop");
  const SHOW_AFTER_PX = 600;
  window.addEventListener(
    "scroll",
    () => {
      btn.hidden = window.scrollY < SHOW_AFTER_PX;
    },
    { passive: true },
  );
  btn.onclick = () => window.scrollTo({ top: 0, behavior: "smooth" });
}

function init(): void {
  const cfg = $maybe("app-config")?.textContent;
  if (cfg) {
    const parsed = JSON.parse(cfg) as {
      deliveryFee?: number;
      areas?: { name: string; fee: number; eta?: string }[];
      bank?: { bank: string; accountName: string; accountNumber: string; accounts: { bank: string; accountName: string; accountNumber: string }[]; ready: boolean };
      monnifyReady?: boolean;
    };
    if (typeof parsed.deliveryFee === "number") setDeliveryFee(parsed.deliveryFee);
    if (parsed.areas?.length) setAreas(parsed.areas);
    setBankDetails(parsed.bank);
    setMonnifyReady(Boolean(parsed.monnifyReady));
  }
  syncSignedIn();
  initModals();
  initReorder();
  initBackToTop();
  const cartReady = initCart();
  initCheckout();
  initAuthEvents();
  setCheckoutHandler(openCheckout);
  configureCheckout({
    isSignedIn: () => signedIn,
    promptSignIn,
    onOrderPlaced: showOrderPlaced,
  });
  $("confirmClose").onclick = () => {
    stopPaymentPanel();
    hide($("confirmOverlay"));
  };
  rehydrateGrid();
  handleEntryLinks(cartReady);
}

/** Links from the account page: ?cart=1 opens the cart (after it has been restored), ?signin=1 asks to sign in. */
function handleEntryLinks(cartReady: Promise<unknown>): void {
  const params = new URLSearchParams(location.search);
  const wantsCart = params.get("cart") === "1";
  const wantsSignIn = params.get("signin") === "1";
  if (!wantsCart && !wantsSignIn) return;
  history.replaceState(null, "", location.pathname);
  if (wantsCart) void cartReady.then(() => openCart());
  if (wantsSignIn && !signedIn) promptSignIn("Please sign in to see your account.");
}

document.addEventListener("DOMContentLoaded", init);

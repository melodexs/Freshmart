import { postJson, errorMessage } from "./api";
import { $, clear, h, hide, money, show } from "./dom";
import { fetchCatalog, loadCart, saveCart } from "./persist";
import type { CartEntry, CartLine, Product } from "./types";

/** In-memory cart. Prices shown here are for display only: the server recomputes
 * every total from its own catalog when the order is placed. */
const cart = new Map<string, CartEntry>();
let deliveryFee = 800;
const listeners: Array<() => void> = [];

export function setDeliveryFee(fee: number): void {
  deliveryFee = fee;
}
export function getDeliveryFee(): number {
  return deliveryFee;
}
/** A discount the server has previewed for the current basket. Only a preview: the server prices the real order. */
let applied: { code: string; amount: number } | null = null;
export function appliedDiscount(): { code: string; amount: number } | null {
  return applied;
}
export function setAppliedDiscount(d: { code: string; amount: number } | null): void {
  applied = d;
}
export function onCartChange(fn: () => void): void {
  listeners.push(fn);
}
function notify(): void {
  applied = null; // the basket changed, so any previewed saving may no longer be right
  saveCart(cart);
  const clearBtn = document.getElementById("clearCartBtn");
  if (clearBtn) clearBtn.hidden = cart.size === 0;
  renderCount();
  renderDrawer();
  for (const fn of listeners) fn();
}

export function isEmpty(): boolean {
  return cart.size === 0;
}
export function clearCart(): void {
  cart.clear();
  notify();
  rehydrateGrid();
}

export function lines(): CartLine[] {
  return Array.from(cart.entries()).map(([key, e]) => {
    const option = e.product.options[e.optionIndex];
    if (!option) throw new Error(`Bad option for ${key}`);
    return {
      key,
      product: e.product,
      option,
      qty: e.qty,
      note: e.note,
      unitPrice: option.price,
      subtotal: option.price * e.qty,
    };
  });
}
export function subtotal(): number {
  return lines().reduce((a, l) => a + l.subtotal, 0);
}
export function total(): number {
  return subtotal() - (applied?.amount ?? 0) + deliveryFee;
}

export function changeQty(key: string, delta: number): void {
  const entry = cart.get(key);
  if (!entry) return;
  const next = entry.qty + delta;
  if (next <= 0) cart.delete(key);
  else entry.qty = next;
  notify();
  rehydrateGrid();
}

/** One line of a past order, as stored by the server. */
export interface ReorderLine {
  productId: string;
  optionIndex: number;
  qty: number;
}

/** Put the lines of an earlier order back in the cart at today's prices.
 * Anything no longer sold (or whose size no longer exists) is skipped, and counted. */
export async function addFromOrder(wanted: ReorderLine[]): Promise<{ added: number; skipped: number }> {
  const catalog = await fetchCatalog();
  let added = 0;
  let skipped = 0;
  for (const w of wanted) {
    const product = catalog.find((p) => p.id === w.productId);
    const okIndex = Number.isInteger(w.optionIndex) && w.optionIndex >= 0;
    const okQty = Number.isInteger(w.qty) && w.qty > 0 && w.qty <= 1000;
    if (!product || !okIndex || !product.options[w.optionIndex] || !okQty) {
      skipped += 1;
      continue;
    }
    const key = `${product.id}|${w.optionIndex}`;
    const existing = cart.get(key);
    if (existing) existing.qty += w.qty;
    else cart.set(key, { qty: w.qty, note: "", product, optionIndex: w.optionIndex });
    added += 1;
  }
  notify();
  rehydrateGrid();
  return { added, skipped };
}

function addToCart(product: Product, optionIndex: number): void {
  const key = `${product.id}|${optionIndex}`;
  const existing = cart.get(key);
  if (existing) existing.qty += 1;
  else cart.set(key, { qty: 1, note: "", product, optionIndex });
  notify();
  rehydrateGrid();
}

// ---------- product grid (server-rendered, controls attached here) ----------

function readProduct(card: HTMLElement): Product | null {
  const script = card.querySelector<HTMLScriptElement>("script.product-data");
  if (!script?.textContent) return null;
  try {
    return JSON.parse(script.textContent) as Product;
  } catch {
    return null;
  }
}

/** Remember which size each product card has selected, across grid re-renders. */
const chosenOption = new Map<string, number>();

function hydrateCard(card: HTMLElement): void {
  const product = readProduct(card);
  if (!product) return;
  const select = card.querySelector<HTMLSelectElement>(".opt-select");
  const priceEl = card.querySelector<HTMLElement>(".price");
  const area = card.querySelector<HTMLElement>(".qtyArea");
  if (!area) return;

  let idx = chosenOption.get(product.id) ?? 0;
  if (select) {
    select.value = String(idx);
    select.onchange = () => {
      idx = Number(select.value);
      chosenOption.set(product.id, idx);
      paint();
    };
  }

  function paint(): void {
    const option = product?.options[idx];
    if (!product || !option || !area) return;
    if (priceEl) priceEl.textContent = money(option.price);
    const key = `${product.id}|${idx}`;
    const entry = cart.get(key);
    clear(area);
    if (entry) {
      const dec = h("button", { type: "button", text: "−", "aria-label": "Decrease" });
      const inc = h("button", { type: "button", text: "+", "aria-label": "Increase" });
      dec.onclick = () => changeQty(key, -1);
      inc.onclick = () => changeQty(key, 1);
      const note = h("input", {
        class: "note-input",
        placeholder: "Any specifics? e.g. scent, brand, ripeness",
      }) as HTMLInputElement;
      note.value = entry.note;
      note.oninput = () => {
        entry.note = note.value;
      };
      area.append(h("div", { class: "stepper" }, dec, h("span", { text: String(entry.qty) }), inc), note);
    } else {
      const add = h("button", { class: "add-btn", type: "button", text: "Add to cart" });
      add.onclick = () => addToCart(product, idx);
      area.append(add);
    }
  }
  paint();
}

/** Attach cart controls to every product card currently in the page. */
export function rehydrateGrid(): void {
  document.querySelectorAll<HTMLElement>("#productGrid .card").forEach(hydrateCard);
}

// ---------- cart count + drawer ----------

function renderCount(): void {
  const n = String(cart.size);
  $("cartCount").textContent = n;
  $("fabCartCount").textContent = n;
}

let onCheckout: () => void = () => undefined;
export function setCheckoutHandler(fn: () => void): void {
  onCheckout = fn;
}

function renderDrawer(): void {
  const body = $("cartBody");
  const foot = $("cartFoot");
  clear(body);
  clear(foot);
  const ls = lines();
  if (ls.length === 0) {
    body.append(
      h("div", { class: "empty-note" }, "Your cart is empty.", h("br"), "Browse products and add a few things."),
    );
    return;
  }
  for (const l of ls) {
    const remove = h("button", { class: "remove", type: "button", text: "Remove" });
    remove.onclick = () => changeQty(l.key, -l.qty);
    body.append(
      h(
        "div",
        { class: "line-item" },
        h(
          "div",
          { class: "line-thumb" },
          l.product.photo
            ? h("img", { src: l.product.photo, alt: "", width: "56", height: "56", loading: "lazy", decoding: "async" })
            : h("span", { text: l.product.emoji }),
        ),
        h(
          "div",
          { class: "grow" },
          h("div", { class: "name", text: l.product.name }),
          h("div", { class: "sub", text: `${l.option.label} · ${l.qty} × ${money(l.unitPrice)}` }),
          l.note && h("div", { class: "sub", style: "font-style:italic;", text: `"${l.note}"` }),
        ),
        h(
          "div",
          { style: "text-align:right;" },
          h("div", { style: "font-weight:600;font-size:.85rem;", text: money(l.subtotal) }),
          remove,
        ),
      ),
    );
  }
  const row = (label: string, value: string, cls = "totals-row") =>
    h("div", { class: cls }, h("span", { text: label }), h("span", { text: value }));
  const go = h("button", { class: "btn-primary", id: "goCheckout", type: "button", text: "Checkout" });
  go.onclick = () => onCheckout();
  const codeNote = h("div", { class: "code-note", role: "status" });
  const codeInput = h("input", {
    id: "discountInput",
    class: "code-input",
    type: "text",
    placeholder: "Discount code",
    autocomplete: "off",
    maxlength: "24",
    "aria-label": "Discount code",
  }) as HTMLInputElement;
  const applyBtn = h("button", { class: "btn-ghost code-apply", id: "discountApply", type: "button", text: "Apply" });
  applyBtn.onclick = async () => {
    const code = codeInput.value.trim();
    if (!code) return;
    applyBtn.setAttribute("disabled", "");
    codeNote.className = "code-note";
    codeNote.textContent = "Checking…";
    try {
      const items = lines().map((l) => {
        const [productId, optionIndex] = l.key.split("|");
        return { productId, optionIndex: Number(optionIndex), qty: l.qty };
      });
      const r = await postJson<{ code: string; discount: number }>("/api/orders/discount-check", { items, code });
      applied = { code: r.code, amount: r.discount };
      renderDrawer();
    } catch (err) {
      const e = err as { error?: string; detail?: string };
      const needsSignIn = !e.error && typeof e.detail === "string";
      codeNote.className = "code-note bad";
      codeNote.textContent = needsSignIn ? "Please sign in to use a discount code." : errorMessage(err, "That code could not be checked.");
    } finally {
      applyBtn.removeAttribute("disabled");
    }
  };
  const removeCode = h("button", { class: "linkish", type: "button", text: "Remove" });
  removeCode.onclick = () => {
    applied = null;
    renderDrawer();
  };
  const codeRow = applied
    ? h("div", { class: "code-row on" }, h("span", { text: `Code ${applied.code} applied` }), removeCode)
    : h("div", { class: "code-row" }, codeInput, applyBtn);
  foot.append(
    codeRow,
    codeNote,
    row("Subtotal", money(subtotal())),
    ...(applied ? [row(`Discount (${applied.code})`, `−${money(applied.amount)}`, "totals-row saving")] : []),
    row("Delivery fee", money(deliveryFee)),
    row("Total", money(total()), "totals-row grand"),
    go,
  );
}

export function openCart(): void {
  show($("cartOverlay"));
  show($("cartDrawer"));
}
export function closeCart(): void {
  hide($("cartOverlay"));
  hide($("cartDrawer"));
}

export async function initCart(): Promise<void> {
  $("cartBtn").onclick = openCart;
  $("cartFab").onclick = openCart;
  $("closeCart").onclick = closeCart;
  $("clearCartBtn").onclick = () => {
    if (window.confirm("Remove everything from your cart?")) clearCart();
  };
  $("cartOverlay").onclick = closeCart;

  // Fade the floating cart near the top, where the header cart is easy to reach.
  const fab = $("cartFab");
  const NEAR_TOP_PX = 160;
  const update = (): void => {
    fab.classList.toggle("faded", window.scrollY < NEAR_TOP_PX);
  };
  window.addEventListener("scroll", update, { passive: true });
  update();

  // Bring back a cart saved before a refresh, priced from the live catalog.
  // This must happen BEFORE the first notify(), which saves (and would erase) the stored cart.
  const restored = loadCart(await fetchCatalog());
  for (const [k, v] of restored) cart.set(k, v);
  notify();
  rehydrateGrid();
}

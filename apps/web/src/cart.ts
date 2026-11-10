import { $, clear, h, hide, money, show } from "./dom";
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
export function onCartChange(fn: () => void): void {
  listeners.push(fn);
}
function notify(): void {
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
  return subtotal() + deliveryFee;
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
        h("div", { style: "font-size:1.4rem;", text: l.product.emoji }),
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
  foot.append(
    row("Subtotal", money(subtotal())),
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

export function initCart(): void {
  $("cartBtn").onclick = openCart;
  $("cartFab").onclick = openCart;
  $("closeCart").onclick = closeCart;
  $("cartOverlay").onclick = closeCart;

  // Fade the floating cart near the top, where the header cart is easy to reach.
  const fab = $("cartFab");
  const NEAR_TOP_PX = 160;
  const update = (): void => {
    fab.classList.toggle("faded", window.scrollY < NEAR_TOP_PX);
  };
  window.addEventListener("scroll", update, { passive: true });
  update();

  notify();
}

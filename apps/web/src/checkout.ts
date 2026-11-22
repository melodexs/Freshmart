import { errorMessage, postJson } from "./api";
import { $, clear, h, hide, money, show } from "./dom";
import {
  changeQty,
  clearCart,
  closeCart,
  getDeliveryFee,
  setDeliveryFee,
  isEmpty,
  lines,
  onCartChange,
  subtotal,
  appliedDiscount,
  total,
} from "./cart";
import type { PayMethod, PlacedOrder } from "./types";

/** Three steps: 1 your details, 2 delivery, 3 payment. Prices and the delivery fee are
 * always recalculated by the server; what is shown here is only a preview. */

type Step = 1 | 2 | 3;

let step: Step = 1;
let selectedPay: PayMethod | null = null;
let isSignedIn: () => boolean = () => false;
let promptSignIn: (message: string) => void = () => undefined;
let onOrderPlaced: (order: PlacedOrder) => void = () => undefined;
let placing = false;

export function configureCheckout(opts: {
  isSignedIn: () => boolean;
  promptSignIn: (message: string) => void;
  onOrderPlaced: (order: PlacedOrder) => void;
}): void {
  isSignedIn = opts.isSignedIn;
  promptSignIn = opts.promptSignIn;
  onOrderPlaced = opts.onOrderPlaced;
}

function msg(text: string, type: "error" | "ok" = "error"): void {
  const box = $("checkoutMsg");
  clear(box);
  if (text) box.append(h("div", { class: `msg ${type}`, text }));
}

export function openCheckout(): void {
  if (isEmpty()) return;
  if (!isSignedIn()) {
    closeCart();
    promptSignIn("Sign in or create an account to check out.");
    return;
  }
  closeCart();
  show($("checkoutOverlay"));
  selectedPay = null;
  placing = false;
  syncPayChoice();
  setStep(1);
}

function setStep(next: Step): void {
  step = next;
  for (const n of [1, 2, 3] as const) {
    $(`coStep${n}`).hidden = n !== next;
  }
  document.querySelectorAll<HTMLElement>("#coSteps li").forEach((li) => {
    const n = Number(li.dataset.step);
    li.classList.toggle("on", n === next);
    li.classList.toggle("done", n < next);
    if (n === next) li.setAttribute("aria-current", "step");
    else li.removeAttribute("aria-current");
  });
  msg("");
  if (next === 1) renderReview();
  if (next === 2) renderFee();
  if (next === 3) renderSummary();
  $("checkoutOverlay").querySelector<HTMLElement>(".modal")?.scrollTo({ top: 0 });
}

// ---------- step 1: review the cart and customer details ----------

function renderReview(): void {
  const el = $("stepReview");
  clear(el);
  const ls = lines();
  if (ls.length === 0) {
    el.append(h("div", { class: "empty-note" }, "Your cart is empty.", h("br"), "Close this and add some items."));
    return;
  }
  for (const l of ls) {
    const dec = h("button", { type: "button", "aria-label": `Decrease ${l.product.name}`, text: "−" });
    const inc = h("button", { type: "button", "aria-label": `Increase ${l.product.name}`, text: "+" });
    const remove = h("button", { class: "remove", type: "button", text: "Remove" });
    dec.onclick = () => changeQty(l.key, -1);
    inc.onclick = () => changeQty(l.key, 1);
    remove.onclick = () => changeQty(l.key, -l.qty);
    el.append(
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
          h("div", { class: "sub", text: `${l.option.label} · ${money(l.unitPrice)} each` }),
          l.note && h("div", { class: "sub", style: "font-style:italic;", text: `"${l.note}"` }),
          h("div", { class: "stepper", style: "margin-top:6px;" }, dec, h("span", { text: String(l.qty) }), inc),
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
}

// ---------- step 2: delivery ----------

function renderFee(): void {
  const line = $("coFeeLine");
  clear(line);
  line.append(
    h("span", { text: "Delivery fee" }),
    h("strong", { text: money(getDeliveryFee()) }),
  );
  // Shown only when the store has set a time for this area. Never guessed.
  const eta = areaEtas[$<HTMLSelectElement>("coArea").value];
  if (eta) {
    line.append(h("div", { class: "co-eta", text: `Estimated delivery: ${eta}` }));
  }
}

// ---------- step 3: payment ----------

interface Bank {
  bank: string;
  accountName: string;
  accountNumber: string;
  ready: boolean;
}
let bank: Bank = { bank: "", accountName: "", accountNumber: "", ready: false };
export function setBankDetails(b: Bank | undefined): void {
  if (b) bank = b;
}
export function getBank(): Bank {
  return bank;
}

function renderSummary(): void {
  const box = $("coSummary");
  clear(box);
  const row = (label: string, value: string, cls = "totals-row") =>
    h("div", { class: cls }, h("span", { text: label }), h("span", { text: value }));
  box.append(
    row("Subtotal", money(subtotal())),
    ...(appliedDiscount() ? [row(`Discount (${appliedDiscount()!.code})`, `−${money(appliedDiscount()!.amount)}`, "totals-row saving")] : []),
    row("Delivery fee", money(getDeliveryFee())),
    row("Total", money(total()), "totals-row grand"),
  );
  $("placeOrderBtn").textContent = placeLabel();
  renderPayPanel();
}

function placeLabel(): string {
  return selectedPay === "before" ? `Place order and pay ${money(total())}` : `Place order — ${money(total())}`;
}

function syncPayChoice(): void {
  $("optDelivery").classList.toggle("selected", selectedPay === "delivery");
  $("optBefore").classList.toggle("selected", selectedPay === "before");
  $("optDelivery").setAttribute("aria-checked", String(selectedPay === "delivery"));
  $("optBefore").setAttribute("aria-checked", String(selectedPay === "before"));
  const radios = document.querySelectorAll<HTMLInputElement>("#coStep3 input[name=pay]");
  radios.forEach((r) => (r.checked = r.value === selectedPay));
}

function selectPay(val: PayMethod): void {
  selectedPay = val;
  syncPayChoice();
  $("placeOrderBtn").textContent = placeLabel();
  renderPayPanel();
}

function renderPayPanel(): void {
  const panel = $("beforePayPanel");
  clear(panel);
  panel.hidden = selectedPay !== "before";
  if (selectedPay !== "before") return;
  if (!bank.ready) {
    panel.append(
      h("div", {
        class: "small-note",
        text: "Pay-before-delivery is not available right now. Please choose pay on delivery, or contact the store.",
      }),
    );
    return;
  }
  const row = (k: string, v: string) =>
    h("div", { class: "bank-row" }, h("span", { text: k }), h("strong", { text: v }));
  panel.append(
    h("div", { class: "bank-card" },
      h("div", { class: "bank-title", text: "Pay by bank transfer to" }),
      row("Bank", bank.bank),
      row("Account name", bank.accountName),
      row("Account number", bank.accountNumber),
      row("Amount", money(total())),
    ),
    h("div", {
      class: "small-note",
      text: "After you place the order you will get a reference. Use it as the transfer narration. Your order stays 'Awaiting payment' until we confirm the money, then we start packing.",
    }),
  );
}

// ---------- placing the order ----------

function val(id: string): string {
  return $<HTMLInputElement>(id).value.trim();
}

function validateStep(n: Step): string {
  if (n === 1) {
    if (isEmpty()) return "Your cart is empty.";
    if (val("coName").length < 2) return "Please enter your full name.";
    if (!val("coPhone")) return "Please enter your phone number.";
  }
  if (n === 2) {
    if (!val("coArea")) return "Please choose your delivery area.";
    if (val("coAddress").length < 5) return "Please enter your delivery address.";
  }
  return "";
}

async function placeOrder(): Promise<void> {
  if (placing) return;
  for (const n of [1, 2] as const) {
    const problem = validateStep(n);
    if (problem) {
      setStep(n);
      msg(problem);
      return;
    }
  }
  if (!selectedPay) return msg("Please choose how you would like to pay.");
  if (selectedPay === "before" && !bank.ready) return msg("Pay before delivery is not available right now.");

  const items = lines().map((l) => {
    const [productId, optionIndex] = l.key.split("|");
    return { productId, optionIndex: Number(optionIndex), qty: l.qty, note: l.note };
  });
  const btn = $<HTMLButtonElement>("placeOrderBtn");
  placing = true;
  btn.disabled = true;
  btn.textContent = "Placing your order…";
  try {
    const data = await postJson<{ order: PlacedOrder; bank?: Bank }>("/api/orders", {
      items,
      name: val("coName"),
      address: val("coAddress"),
      phone: val("coPhone"),
      city: val("coArea"),
      instructions: val("coNote"),
      payMethod: selectedPay,
      discountCode: appliedDiscount()?.code ?? "",
    });
    clearCart();
    hide($("checkoutOverlay"));
    onOrderPlaced(data.order);
  } catch (err) {
    msg(errorMessage(err, "Couldn't place your order. Please try again."));
  } finally {
    placing = false;
    btn.disabled = false;
    btn.textContent = placeLabel();
  }
}

let areaFees: Record<string, number> = {};
let areaEtas: Record<string, string> = {};

export function setAreas(areas: { name: string; fee: number; eta?: string }[]): void {
  const sel = $<HTMLSelectElement>("coArea");
  clear(sel);
  areaFees = {};
  areaEtas = {};
  for (const a of areas) {
    areaFees[a.name] = a.fee;
    if (a.eta) areaEtas[a.name] = a.eta;
    sel.append(h("option", { value: a.name, text: `${a.name} (${money(a.fee)})` }));
  }
  applyAreaFee();
  renderFee();
}

function applyAreaFee(): void {
  const fee = areaFees[$<HTMLSelectElement>("coArea").value];
  if (typeof fee === "number") setDeliveryFee(fee);
}

export function initCheckout(): void {
  const close = (): void => hide($("checkoutOverlay"));
  $("closeCheckout").onclick = close;
  $("checkoutOverlay").onclick = (e) => {
    if (e.target === $("checkoutOverlay")) close();
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("checkoutOverlay").classList.contains("show")) close();
  });
  for (const [id, val2] of [["optDelivery", "delivery"], ["optBefore", "before"]] as const) {
    const el = $(id);
    el.onclick = () => selectPay(val2);
    el.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectPay(val2);
      }
    };
  }
  $("coArea").addEventListener("change", () => {
    applyAreaFee();
    renderFee();
  });
  $("coNext1").onclick = () => {
    const p = validateStep(1);
    if (p) return msg(p);
    setStep(2);
  };
  $("coNext2").onclick = () => {
    const p = validateStep(2);
    if (p) return msg(p);
    setStep(3);
  };
  $("coBack2").onclick = () => setStep(1);
  $("coBack3").onclick = () => setStep(2);
  $("placeOrderBtn").onclick = () => void placeOrder();
  onCartChange(() => {
    if (!$("checkoutOverlay").classList.contains("show")) return;
    if (step === 1) renderReview();
    if (step === 3) renderSummary();
  });
}

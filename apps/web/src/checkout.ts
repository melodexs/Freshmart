import { errorMessage, postJson } from "./api";
import { $, clear, h, hide, money, show } from "./dom";
import {
  changeQty,
  clearCart,
  closeCart,
  getDeliveryFee,
  isEmpty,
  lines,
  onCartChange,
  subtotal,
  total,
} from "./cart";
import { runCardPaymentFlow } from "./payment";
import type { OrderInfo, PayMethod, PaymentDetail, PlacedOrder } from "./types";

const BANKS = [
  "GTBank", "Access Bank", "Zenith Bank", "UBA", "First Bank", "Fidelity Bank", "Union Bank", "Sterling Bank",
  "Opay", "Palmpay", "Kuda Bank", "Moniepoint MFB", "LAPO Microfinance Bank", "AB Microfinance Bank",
  "Accion MFB", "VFD Microfinance Bank",
];
const USSD_CODES: Record<string, string> = {
  GTBank: "*737#", "Access Bank": "*901#", "Zenith Bank": "*966#", UBA: "*919#", "First Bank": "*894#",
};

let selectedPay: PayMethod | null = null;
let payTab: "card" | "transfer" | "ussd" = "card";
let selectedBank: string | null = null;
let isSignedIn: () => boolean = () => false;
let promptSignIn: (message: string) => void = () => undefined;
let onOrderPlaced: (order: PlacedOrder) => void = () => undefined;

export function configureCheckout(opts: {
  isSignedIn: () => boolean;
  promptSignIn: (message: string) => void;
  onOrderPlaced: (order: PlacedOrder) => void;
}): void {
  isSignedIn = opts.isSignedIn;
  promptSignIn = opts.promptSignIn;
  onOrderPlaced = opts.onOrderPlaced;
}

function checkoutMsg(text: string, type: "error" | "ok" = "error"): void {
  const box = $("checkoutMsg");
  clear(box);
  box.append(h("div", { class: `msg ${type}`, text }));
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
  setStep("review");
}

function setStep(step: "review" | "place"): void {
  $("stepReview").style.display = step === "review" ? "block" : "none";
  $("stepPlace").style.display = step === "place" ? "block" : "none";
  $("tabReview").classList.toggle("active", step === "review");
  $("tabPlace").classList.toggle("active", step === "place");
  clear($("checkoutMsg"));
  renderReview();
}

function renderReview(): void {
  const el = $("stepReview");
  clear(el);
  const ls = lines();
  if (ls.length === 0) {
    el.append(h("div", { class: "empty-note" }, "Your cart is empty.", h("br"), "Close this and add some items."));
    return;
  }
  for (const l of ls) {
    const dec = h("button", { type: "button", "aria-label": "Decrease", text: "−" });
    const inc = h("button", { type: "button", "aria-label": "Increase", text: "+" });
    const remove = h("button", { class: "remove", type: "button", text: "Remove" });
    dec.onclick = () => changeQty(l.key, -1);
    inc.onclick = () => changeQty(l.key, 1);
    remove.onclick = () => changeQty(l.key, -l.qty);
    el.append(
      h(
        "div",
        { class: "line-item" },
        h("div", { style: "font-size:1.4rem;", text: l.product.emoji }),
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
  const row = (label: string, value: string, cls = "totals-row") =>
    h("div", { class: cls }, h("span", { text: label }), h("span", { text: value }));
  const next = h("button", { class: "btn-primary", type: "button", text: "Continue to place order" });
  next.onclick = () => setStep("place");
  el.append(
    h(
      "div",
      { style: "margin-top:10px;" },
      row("Subtotal", money(subtotal())),
      row("Delivery fee", money(getDeliveryFee())),
      row("Total", money(total()), "totals-row grand"),
    ),
    next,
  );
  updatePlaceLabel();
}

function updatePlaceLabel(): void {
  $("placeOrderBtn").textContent = "Place order — " + money(total());
}

// ---------- payment method controls ----------

function selectPay(val: PayMethod): void {
  selectedPay = val;
  $("optDelivery").classList.toggle("selected", val === "delivery");
  $("optBefore").classList.toggle("selected", val === "before");
  const radio = (id: string): HTMLInputElement | null => $(id).querySelector("input");
  const delivery = radio("optDelivery");
  const before = radio("optBefore");
  if (delivery) delivery.checked = val === "delivery";
  if (before) before.checked = val === "before";
  $("beforePayPanel").style.display = val === "before" ? "block" : "none";
  if (val === "before") renderBankList();
}

function renderBankList(): void {
  const el = $("bankList");
  if (el.children.length) return;
  for (const bank of BANKS) {
    const btn = h("button", { type: "button", text: bank });
    btn.onclick = () => {
      selectedBank = bank;
      el.querySelectorAll("button").forEach((b) => b.classList.remove("picked"));
      btn.classList.add("picked");
    };
    el.append(btn);
  }
}

function setPayTab(tab: "card" | "transfer" | "ussd"): void {
  payTab = tab;
  $("payTabCard").classList.toggle("active", tab === "card");
  $("payTabTransfer").classList.toggle("active", tab === "transfer");
  $("payTabUssd").classList.toggle("active", tab === "ussd");
  $("payCardPanel").style.display = tab === "card" ? "block" : "none";
  $("payTransferPanel").style.display = tab === "transfer" ? "block" : "none";
  $("payUssdPanel").style.display = tab === "ussd" ? "block" : "none";
  if (tab === "transfer") renderBankList();
}

function updateUssdNote(): void {
  const bank = $<HTMLSelectElement>("ussdBank").value;
  const code = USSD_CODES[bank] ?? "*XXX#";
  const note = $("ussdCodeNote");
  clear(note);
  note.append(
    "You'd dial ",
    h("strong", { text: code }),
    ` on the phone linked to your ${bank} account to approve the payment.`,
  );
}

// ---------- placing the order ----------

function placeOrder(): void {
  if (isEmpty()) return checkoutMsg("Your cart is empty.");
  const address = $<HTMLInputElement>("coAddress").value.trim();
  const phone = $<HTMLInputElement>("coPhone").value.trim();
  if (!address || !phone) return checkoutMsg("Please add your delivery address and phone number.");
  if (!selectedPay) return checkoutMsg("Please choose a payment method.");

  let detail: PaymentDetail = {};
  if (selectedPay === "before") {
    if (payTab === "card") {
      const num = $<HTMLInputElement>("cardNumber").value.trim();
      if (num.replace(/\s/g, "").length < 12) {
        return checkoutMsg("Enter a card number to continue (demo — not charged).");
      }
      detail = { type: "card", last4: num.slice(-4) };
    } else if (payTab === "transfer") {
      if (!selectedBank) return checkoutMsg("Select the bank you'll transfer from.");
      detail = { type: "transfer", bank: selectedBank };
    } else {
      const bank = $<HTMLSelectElement>("ussdBank").value;
      detail = { type: "ussd", bank, code: USSD_CODES[bank] ?? "*XXX#" };
    }
  }

  const info: OrderInfo = { address, phone };
  if (selectedPay === "before" && payTab === "card") {
    hide($("checkoutOverlay"));
    runCardPaymentFlow(info, detail, {
      amount: total(),
      cardNumber: $<HTMLInputElement>("cardNumber").value,
      onPaid: (i, d) => void finalizeOrder(i, d),
      onCancel: () => show($("checkoutOverlay")),
    });
    return;
  }
  void finalizeOrder(info, detail);
}

async function finalizeOrder(info: OrderInfo, detail: PaymentDetail): Promise<void> {
  const items = lines().map((l) => {
    const [productId, optionIndex] = l.key.split("|");
    return { productId, optionIndex: Number(optionIndex), qty: l.qty, note: l.note };
  });
  let order: PlacedOrder;
  try {
    const data = await postJson<{ order: PlacedOrder }>("/api/orders", {
      items,
      address: info.address,
      phone: info.phone,
      city: $<HTMLSelectElement>("coCity").value,
      payMethod: selectedPay,
      paymentDetail: detail,
    });
    order = data.order;
  } catch (err) {
    checkoutMsg(errorMessage(err, "Couldn't place your order — please try again."));
    show($("checkoutOverlay"));
    return;
  }
  clearCart();
  hide($("checkoutOverlay"));
  onOrderPlaced(order);
}

export function initCheckout(): void {
  $("closeCheckout").onclick = () => hide($("checkoutOverlay"));
  $("checkoutOverlay").onclick = (e) => {
    if (e.target === $("checkoutOverlay")) hide($("checkoutOverlay"));
  };
  $("optDelivery").onclick = () => selectPay("delivery");
  $("optBefore").onclick = () => selectPay("before");
  $("payTabCard").onclick = () => setPayTab("card");
  $("payTabTransfer").onclick = () => setPayTab("transfer");
  $("payTabUssd").onclick = () => setPayTab("ussd");
  $("ussdBank").addEventListener("change", updateUssdNote);
  updateUssdNote();
  $("tabReview").onclick = () => setStep("review");
  $("tabPlace").onclick = () => {
    if (!isEmpty()) setStep("place");
  };
  $("backToReview").onclick = () => setStep("review");
  $("placeOrderBtn").onclick = placeOrder;
  // Keep the review list and the button total in step with the cart.
  onCartChange(() => {
    if ($("checkoutOverlay").classList.contains("show")) renderReview();
  });
}

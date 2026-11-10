import { $, clear, h, hide, show } from "./dom";
import type { OrderInfo, PaymentDetail } from "./types";

/** The simulated card flow: connect to bank, confirm amount, enter OTP.
 * No money moves and nothing is sent anywhere. A real build would call Paystack
 * or Flutterwave from the server instead. */

const BANK_NAMES_FOR_CARD = ["GTBank", "Access Bank", "Zenith Bank", "UBA", "First Bank"];

export function bankForCard(cardNumber: string): string {
  let sum = 0;
  for (const ch of cardNumber) sum += ch.charCodeAt(0);
  return BANK_NAMES_FOR_CARD[sum % BANK_NAMES_FOR_CARD.length] ?? "GTBank";
}

interface FlowHooks {
  amount: number;
  cardNumber: string;
  /** Called when the simulated payment succeeds. */
  onPaid: (info: OrderInfo, detail: PaymentDetail) => void;
  /** Called when the customer cancels, so checkout can reopen. */
  onCancel: () => void;
}

function spinner(title: string, sub?: string): HTMLElement[] {
  return [
    h("div", { class: "spinner" }),
    h("h2", { style: "text-align:center;", text: title }),
    ...(sub ? [h("p", { style: "text-align:center;font-size:.85rem;opacity:.7;", text: sub })] : []),
  ];
}

export function runCardPaymentFlow(info: OrderInfo, detail: PaymentDetail, hooks: FlowHooks): void {
  const overlay = $("processingOverlay");
  const modal = $("processingModal");
  const bank = bankForCard(hooks.cardNumber);
  const phone = info.phone;
  const maskedPhone = phone.length >= 4 ? "*******" + phone.slice(-4) : phone;

  show(overlay);
  clear(modal);
  modal.append(...spinner("Connecting to your bank…", "Verifying your card details, please wait."));

  const cancel = (): void => {
    hide(overlay);
    hooks.onCancel();
  };

  setTimeout(() => {
    clear(modal);
    const last4 = hooks.cardNumber.replace(/\s/g, "").slice(-4);
    const amountInput = h("input", { id: "payAmountInput", value: String(hooks.amount) }) as HTMLInputElement;
    const confirm = h("button", { class: "btn-primary", type: "button", text: "Confirm & Continue" });
    const cancelBtn = h("button", { class: "btn-ghost", type: "button", text: "Cancel payment" });
    cancelBtn.onclick = cancel;
    confirm.onclick = () => {
      const entered = Number(amountInput.value);
      if (!entered || entered <= 0) return;
      showOtpStep(bank, maskedPhone, () => {
        hide(overlay);
        hooks.onPaid(info, detail);
      }, cancel);
    };
    modal.append(
      h("h2", { text: "Bank connected" }),
      h(
        "div",
        { class: "bank-badge" },
        h("span", { class: "check", text: "✅" }),
        h(
          "div",
          {},
          h("div", { style: "font-weight:600;", text: bank }),
          h("div", { style: "font-size:.8rem;opacity:.75;", text: `Card ending ${last4} — connection successful.` }),
        ),
      ),
      h("div", { class: "field" }, h("label", { text: "Amount to pay" }), amountInput),
      h("div", {
        class: "small-note",
        text: "This is the total for your order. You can adjust it here only to match a demo scenario — in a real deployment the amount is fixed by your order and cannot be edited.",
      }),
      confirm,
      cancelBtn,
    );
  }, 1600);
}

function showOtpStep(bank: string, maskedPhone: string, onVerified: () => void, onCancel: () => void): void {
  const modal = $("processingModal");
  clear(modal);

  const boxes: HTMLInputElement[] = Array.from({ length: 6 }, () => {
    const b = h("input", { maxlength: 1, inputmode: "numeric" }) as HTMLInputElement;
    return b;
  });
  boxes.forEach((box, i) => {
    box.oninput = () => {
      box.value = box.value.replace(/\D/g, "").slice(0, 1);
      if (box.value) boxes[i + 1]?.focus();
    };
    box.onkeydown = (e) => {
      if (e.key === "Backspace" && !box.value) boxes[i - 1]?.focus();
    };
  });

  const msg = h("div", { id: "otpMsg" });
  const verify = h("button", { class: "btn-primary", type: "button", text: "Verify & Pay" });
  const cancelBtn = h("button", { class: "btn-ghost", type: "button", text: "Cancel payment" });
  cancelBtn.onclick = onCancel;
  verify.onclick = () => {
    const code = boxes.map((b) => b.value).join("");
    if (code.length < 6) {
      clear(msg);
      msg.append(h("div", { class: "msg error", text: "Enter all 6 digits." }));
      return;
    }
    clear(modal);
    modal.append(...spinner("Confirming payment…"));
    setTimeout(onVerified, 1100);
  };

  modal.append(
    h("h2", { text: "Enter OTP" }),
    h("p", {
      style: "font-size:.88rem;",
      text: `${bank} sent a one-time code by SMS to the phone number registered on your account (${maskedPhone}).`,
    }),
    h("div", { class: "otp-boxes" }, ...boxes),
    h("div", { class: "small-note", text: "Demo mode — no real SMS is sent. Enter any 6 digits to continue." }),
    msg,
    verify,
    cancelBtn,
  );
  boxes[0]?.focus();
}

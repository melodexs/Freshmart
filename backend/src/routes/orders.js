"use strict";
const express = require("express");
const db = require("../db");
const { findOption, DELIVERY_FEE } = require("../products");
const { requireAuth } = require("../auth");

const router = express.Router();

router.post("/", requireAuth, async (req, res) => {
  const { items, address, phone, city, payMethod, paymentDetail } = req.body || {};

  if(!Array.isArray(items) || items.length === 0){
    return res.status(400).json({ error: "Your cart is empty." });
  }
  if(!address || !phone){
    return res.status(400).json({ error: "Please add your delivery address and phone number." });
  }
  if(payMethod !== "before" && payMethod !== "delivery"){
    return res.status(400).json({ error: "Please choose a payment method." });
  }

  // Rebuild every line from the server's own catalog — never trust a price
  // sent by the browser. This is the main thing a real backend buys you
  // over the old localStorage version.
  const lines = [];
  for(const raw of items){
    const found = findOption(raw.productId, raw.optionIndex);
    if(!found) return res.status(400).json({ error: "One of the items in your cart is no longer available." });
    const qty = Number(raw.qty);
    if(!Number.isInteger(qty) || qty <= 0){
      return res.status(400).json({ error: "Invalid quantity for " + found.product.name + "." });
    }
    lines.push({
      name: found.product.name + " (" + found.option.label + ")",
      qty,
      price: found.option.price,
      note: (raw.note || "").toString().slice(0, 300),
    });
  }
  const subtotal = lines.reduce((sum, l) => sum + l.price * l.qty, 0);
  const total = subtotal + DELIVERY_FEE;

  const order = {
    id: "FM" + Date.now().toString().slice(-8),
    date: new Date().toISOString(),
    items: lines,
    subtotal,
    deliveryFee: DELIVERY_FEE,
    total,
    address, phone, city: city || "",
    payMethod,
    paymentDetail: paymentDetail || {},
    status: payMethod === "before" ? "Payment confirmed" : "Awaiting delivery — pay on arrival",
    user: req.user.email,
  };

  await db.addOrder(order);

  // Simulated store SMS notification — see routes/store.js for the real-world note.
  const itemSummary = lines.map(l => l.qty + "x " + l.name).join(", ");
  const payLine = payMethod === "before" ? "PAID (before delivery)" : "Pay on delivery";
  const text = `New order ${order.id} — ₦${total.toLocaleString("en-NG")}. ${itemSummary}. `
    + `Deliver to: ${address}, ${city || ""}. Customer: ${phone}. ${payLine}.`;
  await db.addStoreSms({ id: order.id, text, date: order.date });

  res.json({ order });
});

router.get("/mine", requireAuth, async (req, res) => {
  res.json({ orders: await db.getOrdersForUser(req.user.email) });
});

module.exports = router;

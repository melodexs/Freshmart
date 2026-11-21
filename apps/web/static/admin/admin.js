"use strict";
// OGS admin. Data is only ever put on the page with textContent / DOM nodes, never innerHTML,
// because names, addresses and notes are typed by customers.

const API = "/api/store/admin";
const $ = (s, r = document) => r.querySelector(s);

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "class") e.className = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return e;
}
const naira = (n) => "₦" + Number(n || 0).toLocaleString("en-NG");
const when = (iso) => { try { return new Date(iso).toLocaleString("en-NG", { dateStyle: "medium", timeStyle: "short" }); } catch { return iso; } };

let toastTimer;
function toast(text, bad) {
  const t = $("#toast");
  t.textContent = text; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), 3200);
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", credentials: "same-origin", headers: {} };
  if (opts.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
  let res;
  try { res = await fetch(API + path, init); } catch { throw new Error("Cannot reach the store. Check your connection."); }
  if (res.status === 401 || res.status === 403) { showLogin(); throw new Error("Please sign in again."); }
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new Error(data.error || data.detail || "Something went wrong.");
  return data;
}

// ---------- sign in ----------
function showLogin() { $("#app").hidden = true; $("#login").hidden = false; $("#staffKey").focus(); }
function showApp() { $("#login").hidden = true; $("#app").hidden = false; }

$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#loginMsg"); msg.textContent = "";
  try {
    const r = await fetch("/api/store/login", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: $("#staffKey").value }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { msg.textContent = d.error || "That did not work."; return; }
    $("#staffKey").value = ""; showApp(); go("overview");
  } catch { msg.textContent = "Cannot reach the store."; }
});
$("#logout").addEventListener("click", async () => {
  await fetch("/api/store/logout", { method: "POST", credentials: "same-origin" }).catch(() => {});
  showLogin();
});

// ---------- navigation ----------
const views = { overview, orders, products, customers, settings };
const titles = { overview: "Overview", orders: "Orders", products: "Products", customers: "Customers", settings: "Store settings" };
function go(name) {
  for (const b of document.querySelectorAll("#nav button")) b.classList.toggle("on", b.dataset.view === name);
  $("#title").textContent = titles[name]; $("#side").classList.remove("open");
  const v = $("#view"); v.replaceChildren(h("div", { class: "loading", text: "Loading…" }));
  views[name](v).catch((err) => v.replaceChildren(h("div", { class: "empty", text: err.message })));
}
$("#nav").addEventListener("click", (e) => { const b = e.target.closest("button[data-view]"); if (b) go(b.dataset.view); });
$("#menuBtn").addEventListener("click", () => $("#side").classList.toggle("open"));

function pill(status) {
  const cls = /Deliver/.test(status) && !/Out/.test(status) ? "ok" : /Cancel/.test(status) ? "bad" : /Out|Prepar/.test(status) ? "warn" : "";
  return h("span", { class: "pill " + cls, text: status });
}
function table(heads, rows, emptyText) {
  if (!rows.length) return h("div", { class: "empty", text: emptyText });
  return h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, heads.map((x) => h("th", { text: x })))), h("tbody", {}, rows)));
}

// ---------- overview ----------
async function overview(root) {
  const d = await api("/overview");
  const card = (k, v) => h("div", { class: "card" }, h("div", { class: "k", text: k }), h("div", { class: "v", text: v }));
  const max = Math.max(1, ...d.last7Days.map((x) => x.revenue));
  const chart = h("div", { class: "bar", role: "img", "aria-label": "Sales for the last 7 days" }, d.last7Days.map((x) =>
    h("div", {}, h("i", { style: `height:${Math.round((x.revenue / max) * 100)}%`, title: naira(x.revenue) }), h("b", { text: x.revenue ? naira(x.revenue) : "" }), h("span", { text: x.date.slice(5) }))));
  root.replaceChildren(
    h("div", { class: "cards" },
      card("Total revenue", naira(d.revenue)), card("Today's sales", naira(d.todaySales)), card("Total orders", d.totalOrders),
      card("Pending orders", d.pendingOrders), card("Completed orders", d.completedOrders), card("Customers", d.customers), card("Products", d.products)),
    h("div", { class: "two" },
      h("div", { class: "panel" }, h("h2", { text: "Sales, last 7 days" }), chart),
      h("div", { class: "panel" }, h("h2", { text: "Low stock" }),
        d.lowStock.length ? h("div", {}, d.lowStock.map((p) => h("p", {}, h("strong", { text: p.name }), " ", h("span", { class: "pill " + (p.stock === 0 ? "bad" : "warn"), text: p.stock === 0 ? "Out" : p.stock + " left" })))) : h("p", { class: "muted", text: "All tracked products are well stocked." }))),
    h("div", { class: "panel" }, h("h2", { text: "Recent orders" }),
      table(["Order", "Total", "Status", "When"], d.recent.map((o) => h("tr", {}, h("td", { text: o.id }), h("td", { text: naira(o.total) }), h("td", {}, pill(o.status)), h("td", { text: when(o.date) }))), "No orders yet."))
  );
}

// ---------- orders ----------
async function orders(root) {
  let q = "", status = "";
  const list = h("div");
  const load = async () => {
    const d = await api(`/orders?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}`);
    list.replaceChildren(table(["Order", "Customer", "Items", "Total", "Status", "Action"], d.orders.map((o) => orderRow(o, load)), "No orders match."));
    return d;
  };
  const first = await api("/orders");
  const sel = h("select", { "aria-label": "Filter by status", onchange: (e) => { status = e.target.value; load(); } }, h("option", { value: "", text: "All statuses" }), first.statuses.map((s) => h("option", { value: s, text: s })));
  const search = h("input", { type: "search", placeholder: "Search order, phone or email", "aria-label": "Search orders", oninput: (e) => { q = e.target.value; clearTimeout(search._t); search._t = setTimeout(load, 250); } });
  root.replaceChildren(h("div", { class: "tools" }, search, sel), list);
  await load();
}
function orderRow(o, reload) {
  const next = { "Awaiting payment": ["Cancelled"], "Payment confirmed": ["Preparing your order", "Cancelled"], "Awaiting delivery — pay on arrival": ["Preparing your order", "Cancelled"], "Preparing your order": ["Out for delivery", "Cancelled"], "Out for delivery": ["Delivered"] }[o.status] || [];
  const move = next.length ? h("select", { "aria-label": "Move order " + o.id, onchange: async (e) => {
    const to = e.target.value; if (!to) return;
    if (to === "Cancelled" && !confirm(`Cancel order ${o.id}? Its stock goes back on the shelf.`)) { e.target.value = ""; return; }
    try { await api(`/orders/${encodeURIComponent(o.id)}/status`, { method: "POST", body: { status: to } }); toast(`${o.id}: ${to}`); reload(); } catch (err) { toast(err.message, true); e.target.value = ""; }
  } }, h("option", { value: "", text: "Move to…" }), next.map((s) => h("option", { value: s, text: s }))) : h("span", { class: "muted", text: "Final" });
  const pay = o.status === "Awaiting payment" ? h("button", { class: "btn sm primary", style: "margin-bottom:6px", onclick: () => confirmPayment(o, reload), text: "Confirm payment" }) : null;
  const paid = o.paymentDetail && o.paymentDetail.paid ? h("div", { class: "muted", text: `Paid ${naira(o.paymentDetail.paidAmount)} by ${o.paymentDetail.paidMethod}, ref ${o.paymentDetail.paidReference}` }) : null;
  return h("tr", {}, h("td", {}, h("strong", { text: o.id }), h("div", { class: "muted", text: when(o.date) })),
    h("td", {}, o.customerName ? h("div", { text: o.customerName }) : null, h("div", { text: o.phone }), h("div", { class: "muted", text: o.user }), h("div", { class: "muted", text: [o.address, o.city].filter(Boolean).join(", ") }), o.instructions ? h("div", { class: "muted", text: "Note: " + o.instructions }) : null),
    h("td", {}, o.items.map((i) => h("div", { text: `${i.qty}× ${i.name}` }))),
    h("td", { text: naira(o.total) }), h("td", {}, pill(o.status), h("div", { class: "muted", text: o.payMethod === "before" ? "Pay before delivery" : "Pay on delivery" }), paid), h("td", {}, pay, h("div", {}, move), h("button", { class: "btn sm", style: "margin-top:6px", onclick: () => history_(o), text: "History" })));
}

function confirmPayment(o, reload) {
  const msg = h("p", { class: "msg", role: "alert" });
  const amount = h("input", { type: "number", min: "1", value: o.total, "aria-label": "Amount received in naira" });
  const method = h("select", { "aria-label": "How it was paid" }, ["bank transfer", "ussd", "cash", "pos", "other"].map((m) => h("option", { value: m, text: m })));
  const ref = h("input", { maxlength: "80", placeholder: "Bank or transfer reference", "aria-label": "Payment reference" });
  const form = h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault(); msg.textContent = "";
    try { await api(`/orders/${encodeURIComponent(o.id)}/confirm-payment`, { method: "POST", body: { amount: Number(amount.value), method: method.value, reference: ref.value } }); toast(`Payment confirmed for ${o.id}`); close(); reload(); } catch (err) { msg.textContent = err.message; }
  } },
    h("p", {}, "Only confirm after you have seen the money in your account. This is recorded permanently with the time and the reference."),
    h("p", {}, h("strong", { text: `Order ${o.id}: ${naira(o.total)} due` })),
    h("div", {}, h("label", { text: "Amount received (₦)" }), amount), h("div", {}, h("label", { text: "How was it paid?" }), method), h("div", {}, h("label", { text: "Reference" }), ref), msg,
    h("div", { style: "display:flex;gap:8px" }, h("button", { class: "btn primary", type: "submit", text: "Confirm payment received" }), h("button", { class: "btn", type: "button", onclick: () => close(), text: "Cancel" })));
  const modal = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": "Confirm payment" }, h("div", { class: "box" }, h("div", { class: "head" }, h("h2", { text: "Confirm payment" }), h("button", { class: "btn sm", "aria-label": "Close", onclick: () => close(), text: "✕" })), form));
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function close() { document.removeEventListener("keydown", onKey); modal.remove(); }
  document.addEventListener("keydown", onKey); document.body.append(modal); ref.focus();
}

async function history_(o) {
  let d; try { d = await api(`/audit?subject=${encodeURIComponent(o.id)}`); } catch (err) { toast(err.message, true); return; }
  const rows = d.entries.map((e) => h("tr", {}, h("td", { text: when(e.at) }), h("td", { text: e.action.replace(/_/g, " ") }), h("td", { text: Object.entries(e.detail).map(([k, v]) => `${k}: ${v}`).join(", ") })));
  const modal = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": "Order history" }, h("div", { class: "box" }, h("div", { class: "head" }, h("h2", { text: "History for " + o.id }), h("button", { class: "btn sm", "aria-label": "Close", onclick: () => modal.remove(), text: "✕" })), table(["When", "What", "Details"], rows, "Nothing recorded yet.")));
  document.body.append(modal);
}

// ---------- products ----------
async function products(root) {
  const d = await api("/products");
  let filter = "";
  const list = h("div");
  const draw = () => {
    const rows = d.products.filter((p) => p.name.toLowerCase().includes(filter) || p.cat.toLowerCase().includes(filter)).map((p) =>
      h("tr", {}, h("td", {}, h("div", { style: "display:flex;gap:10px;align-items:center" }, p.image ? h("img", { class: "thumb", src: p.image, alt: "", loading: "lazy" }) : h("span", { class: "thumb", text: p.emoji || "🛒" }), h("div", {}, h("strong", { text: p.name }), h("div", { class: "muted", text: p.id })))),
        h("td", { text: p.cat }),
        h("td", {}, p.options.map((o, i) => h("div", { text: `${o.label}: ${naira(o.price)}${p.comparePrices[i] ? " (was " + naira(p.comparePrices[i]) + ")" : ""}` }))),
        h("td", {}, p.stock == null ? h("span", { class: "muted", text: "Not tracked" }) : h("span", { class: "pill " + (p.stock === 0 ? "bad" : p.stock <= 5 ? "warn" : "ok"), text: p.stock + " in stock" })),
        h("td", {}, h("span", { class: "pill " + (p.active ? "ok" : ""), text: p.active ? "Shown" : "Hidden" }), p.featured ? h("span", { class: "pill warn", text: "Featured" }) : null),
        h("td", {}, h("button", { class: "btn sm", onclick: () => editor(p, refresh), text: "Edit" }))));
    list.replaceChildren(table(["Product", "Category", "Sizes and prices", "Stock", "Status", ""], rows, "No products match."));
  };
  const refresh = () => go("products");
  root.replaceChildren(h("div", { class: "tools" },
    h("input", { type: "search", placeholder: "Search products", "aria-label": "Search products", oninput: (e) => { filter = e.target.value.toLowerCase(); draw(); } }),
    h("span", { class: "grow" }), h("button", { class: "btn primary", onclick: () => editor(null, refresh), text: "+ Add product" })), list);
  draw();
}

function editor(p, done) {
  const isNew = !p;
  const f = { id: p?.id || "", name: p?.name || "", cat: p?.cat || "", emoji: p?.emoji || "", description: p?.description || "", image: p?.image || "", stock: p?.stock ?? "", active: p ? p.active : true, featured: p?.featured || false };
  const opts = (p?.options || [{ label: "", price: "" }]).map((o, i) => ({ label: o.label, price: o.price, was: p?.comparePrices?.[i] || "" }));
  const optBox = h("div");
  const drawOpts = () => optBox.replaceChildren(...opts.map((o, i) => h("div", { class: "optrow" },
    h("input", { placeholder: "Size, e.g. 5 cups", value: o.label, "aria-label": "Size label", oninput: (e) => (o.label = e.target.value) }),
    h("input", { type: "number", min: "1", placeholder: "Price ₦", value: o.price, "aria-label": "Price in naira", oninput: (e) => (o.price = e.target.value) }),
    h("input", { type: "number", min: "1", placeholder: "Old price ₦", value: o.was, "aria-label": "Old price in naira", oninput: (e) => (o.was = e.target.value) }),
    h("button", { type: "button", class: "btn sm danger", "aria-label": "Remove size", onclick: () => { if (opts.length > 1) { opts.splice(i, 1); drawOpts(); } }, text: "✕" }))));
  drawOpts();
  const field = (label, input) => h("div", {}, h("label", { text: label }), input);
  const bind = (k, extra = {}) => h("input", { value: f[k], oninput: (e) => (f[k] = e.target.value), ...extra });
  const msg = h("p", { class: "msg", role: "alert" });
  const uploadHint = h("p", { class: "muted", text: "Image: paste a link that starts with https:// or /static/. File upload needs cloud storage, which is not set up yet." });
  const form = h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault(); msg.textContent = "";
    const body = { ...f, options: opts.map((o) => ({ label: o.label, price: o.price === "" ? "" : Number(o.price), was: o.was === "" ? "" : Number(o.was) })), stock: f.stock === "" ? null : Number(f.stock) };
    try { await api(isNew ? "/products" : `/products/${encodeURIComponent(p.id)}`, { method: isNew ? "POST" : "PUT", body }); toast(isNew ? "Product added" : "Product saved"); close(); done(); } catch (err) { msg.textContent = err.message; }
  } },
    isNew ? field("Product code (letters, numbers, - and _)", bind("id", { required: true, maxlength: "40" })) : null,
    field("Name", bind("name", { required: true, maxlength: "80" })),
    h("div", { class: "row2" }, field("Category", bind("cat", { required: true, maxlength: "40", list: "cats" })), field("Emoji (optional)", bind("emoji", { maxlength: "8" }))),
    field("Description", h("textarea", { maxlength: "600", oninput: (e) => (f.description = e.target.value), text: f.description })),
    field("Image link", bind("image", { placeholder: "https://… or /static/…" })), uploadHint,
    h("div", {}, h("label", { text: "Sizes and prices (old price is optional and shows a discount)" }), optBox, h("button", { type: "button", class: "btn sm", onclick: () => { if (opts.length < 12) { opts.push({ label: "", price: "", was: "" }); drawOpts(); } }, text: "+ Add size" })),
    field("Stock (leave empty to not track)", bind("stock", { type: "number", min: "0" })),
    h("div", { class: "checks" },
      h("label", {}, h("input", { type: "checkbox", checked: f.active, onchange: (e) => (f.active = e.target.checked) }), "Show in store"),
      h("label", {}, h("input", { type: "checkbox", checked: f.featured, onchange: (e) => (f.featured = e.target.checked) }), "Featured")),
    msg,
    h("div", { style: "display:flex;gap:8px;flex-wrap:wrap" }, h("button", { class: "btn primary", type: "submit", text: "Save" }), h("button", { class: "btn", type: "button", onclick: () => close(), text: "Cancel" }),
      isNew ? null : h("button", { class: "btn danger", type: "button", onclick: async () => {
        if (!confirm(`Remove ${p.name}? If it has been ordered it is hidden instead, so old orders stay readable.`)) return;
        try { const r = await api(`/products/${encodeURIComponent(p.id)}`, { method: "DELETE" }); toast(r.hidden ? "Hidden (it has past orders)" : "Product removed"); close(); done(); } catch (err) { msg.textContent = err.message; }
      }, text: "Remove" })));
  const modal = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": isNew ? "Add product" : "Edit product" }, h("div", { class: "box" }, h("div", { class: "head" }, h("h2", { text: isNew ? "Add product" : "Edit " + p.name }), h("button", { class: "btn sm", "aria-label": "Close", onclick: () => close(), text: "✕" })), form));
  const dl = h("datalist", { id: "cats" });
  api("/products").then((d) => { for (const c of new Set(d.products.map((x) => x.cat))) dl.append(h("option", { value: c })); }).catch(() => {});
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function close() { document.removeEventListener("keydown", onKey); modal.remove(); dl.remove(); }
  document.addEventListener("keydown", onKey); document.body.append(dl, modal);
  (isNew ? form.querySelector("input") : form.querySelector("input")).focus();
}

// ---------- customers ----------
async function customers(root) {
  const d = await api("/customers");
  root.replaceChildren(table(["Customer", "Phone", "Orders", "Total spent"], d.customers.map((c) => h("tr", {}, h("td", {}, h("strong", { text: c.name || "(no name)" }), h("div", { class: "muted", text: c.email })), h("td", { text: c.phone }), h("td", { text: c.orders }), h("td", { text: naira(c.spent) }))), "No customers have ordered yet."));
}

// ---------- settings ----------
async function settings(root) {
  const s = await api("/settings");
  const msg = h("p", { class: "msg", role: "alert" });
  const inp = (id, label, val, extra = {}) => h("div", {}, h("label", { for: id, text: label }), h("input", { id, value: val, ...extra }));
  const areas = s.areas.map((a) => ({ name: a.name, fee: a.fee }));
  const areaBox = h("div");
  const drawAreas = () => areaBox.replaceChildren(...areas.map((a, i) => h("div", { class: "optrow", style: "grid-template-columns:2fr 1fr auto" },
    h("input", { value: a.name, placeholder: "Area name", "aria-label": "Area name", oninput: (e) => (a.name = e.target.value) }),
    h("input", { type: "number", min: "0", max: "100000", value: a.fee, placeholder: "Fee ₦", "aria-label": "Delivery fee in naira", oninput: (e) => (a.fee = e.target.value) }),
    h("button", { type: "button", class: "btn sm danger", "aria-label": "Remove area", onclick: () => { if (areas.length > 1) { areas.splice(i, 1); drawAreas(); } }, text: "✕" }))));
  drawAreas();
  const form = h("form", { class: "form panel", onsubmit: async (e) => {
    e.preventDefault(); msg.textContent = "";
    const body = { storeName: $("#sName").value, banner: $("#sBanner").value, whatsapp: $("#sWa").value, contactPhone: $("#sPhone").value,
      areas: areas.map((a) => ({ name: a.name, fee: a.fee === "" ? "" : Number(a.fee) })),
      bank: { bank: $("#sBank").value, accountName: $("#sAcctName").value, accountNumber: $("#sAcctNo").value } };
    try { await api("/settings", { method: "PUT", body }); toast("Settings saved"); } catch (err) { msg.textContent = err.message; }
  } },
    h("h2", { text: "Delivery areas and fees" }),
    h("p", { class: "muted", text: "Customers choose one of these at checkout, and the fee is looked up on the server. The first area is the default." }),
    areaBox, h("button", { type: "button", class: "btn sm", onclick: () => { if (areas.length < 40) { areas.push({ name: "", fee: "" }); drawAreas(); } }, text: "+ Add area" }),
    h("h2", { style: "margin-top:18px", text: "Bank account for pay-before-delivery" }),
    h("p", { class: "muted", text: s.bank.ready ? "Customers can pay by bank transfer to this account." : "Pay-before-delivery is OFF until you enter your real account. Nothing is shown to customers until all three fields are filled." }),
    inp("sBank", "Bank", s.bank.bank, { maxlength: "60" }), inp("sAcctName", "Account name", s.bank.accountName, { maxlength: "80" }), inp("sAcctNo", "Account number (10 digits)", s.bank.accountNumber, { inputmode: "numeric", maxlength: "13" }),
    h("h2", { style: "margin-top:18px", text: "Store details" }),
    inp("sName", "Store name", s.storeName, { maxlength: "80" }), inp("sBanner", "Promotional banner text (optional)", s.banner, { maxlength: "200" }),
    inp("sWa", "WhatsApp number", s.whatsapp, { placeholder: "0801 234 5678" }), inp("sPhone", "Contact phone", s.contactPhone, { placeholder: "0801 234 5678" }),
    msg, h("button", { class: "btn primary", type: "submit", text: "Save settings" }),
    h("p", { class: "muted", text: "Discount codes, image upload, online payment and SMS or WhatsApp notifications are not built yet." }));
  root.replaceChildren(form);
}

// ---------- start ----------
(async () => {
  try {
    const r = await fetch("/api/store/session", { credentials: "same-origin" }); const d = await r.json();
    if (d.staff) { showApp(); go("overview"); } else showLogin();
  } catch { showLogin(); }
})();

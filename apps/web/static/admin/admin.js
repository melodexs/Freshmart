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
  if (res.status === 403) {
    let d403 = {}; try { d403 = await res.clone().json(); } catch { /* empty */ }
    if (/own password/i.test(d403.detail || "")) { await afterSignIn(); throw new Error("Choose your own password first."); }
    if (/owner/i.test(d403.detail || "")) throw new Error(d403.detail);
  }
  if (res.status === 401 || res.status === 403) { showLogin(); throw new Error("Please sign in again."); }
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new Error(data.error || data.detail || "Something went wrong.");
  return data;
}

// ---------- sign in ----------
let me = null; // who is signed in: { name, email, level, mustChange }
const loginForms = ["#loginForm", "#keyForm", "#changeForm"];
function showForm(sel) { for (const f of loginForms) $(f).hidden = f !== sel; }
function showLogin() { me = null; $("#app").hidden = true; $("#login").hidden = false; showForm("#loginForm"); $("#adminEmail").focus(); }
function showApp() {
  $("#login").hidden = true; $("#app").hidden = false;
  const owner = me && me.level === "owner";
  $("#adminsNav").hidden = !owner;
  $("#changePwBtn").hidden = !(me && me.email);
  $("#whoami").textContent = me ? `${me.name} · ${owner ? "Owner" : "Staff"}` : "";
}
async function post(path, body) {
  const r = await fetch("/api/store" + path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  return { ok: r.ok, d };
}
async function loadMe() {
  const r = await fetch("/api/store/me", { credentials: "same-origin" });
  if (!r.ok) return null;
  return r.json();
}
async function afterSignIn() {
  me = await loadMe();
  if (!me) { showLogin(); return; }
  if (me.mustChange) { $("#app").hidden = true; $("#login").hidden = false; showForm("#changeForm"); $("#curPw").focus(); return; }
  showApp(); go("overview");
}

$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#loginMsg"); msg.textContent = "";
  try {
    const { ok, d } = await post("/admin-login", { email: $("#adminEmail").value, password: $("#adminPassword").value });
    if (!ok) { msg.textContent = d.error || "That did not work."; return; }
    $("#adminPassword").value = ""; await afterSignIn();
  } catch { msg.textContent = "Cannot reach the store."; }
});
$("#keyForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#keyMsg"); msg.textContent = "";
  try {
    const { ok, d } = await post("/login", { key: $("#staffKey").value });
    if (!ok) { msg.textContent = d.error || "That did not work."; return; }
    $("#staffKey").value = ""; await afterSignIn();
  } catch { msg.textContent = "Cannot reach the store."; }
});
$("#changeForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#changeMsg"); msg.textContent = "";
  if ($("#newPw").value !== $("#newPw2").value) { msg.textContent = "The two new passwords do not match."; return; }
  try {
    const { ok, d } = await post("/change-password", { current: $("#curPw").value, new: $("#newPw").value });
    if (!ok) { msg.textContent = d.error || "That did not work."; return; }
    for (const id of ["#curPw", "#newPw", "#newPw2"]) $(id).value = "";
    toast("Password saved"); await afterSignIn();
  } catch { msg.textContent = "Cannot reach the store."; }
});
$("#useKey").addEventListener("click", () => { showForm("#keyForm"); $("#staffKey").focus(); });
$("#useEmail").addEventListener("click", () => { showForm("#loginForm"); $("#adminEmail").focus(); });
$("#changePwBtn").addEventListener("click", () => { $("#app").hidden = true; $("#login").hidden = false; showForm("#changeForm"); $("#curPw").focus(); });
$("#logout").addEventListener("click", async () => {
  await fetch("/api/store/logout", { method: "POST", credentials: "same-origin" }).catch(() => {});
  showLogin();
});

// ---------- navigation ----------
const views = { overview, reports, reviews, newsletter, orders, products, stock, discounts, customers, settings, admins };
const titles = { overview: "Overview", reports: "Sales reports", reviews: "Customer reviews", newsletter: "Newsletter", orders: "Orders", products: "Products", stock: "Stock history", discounts: "Discount codes", customers: "Customers", settings: "Store settings", admins: "Admin team" };
function go(name) {
  for (const b of document.querySelectorAll("#nav button")) b.classList.toggle("on", b.dataset.view === name);
  $("#title").textContent = titles[name]; $("#side").classList.remove("open");
  const v = $("#view"); v.replaceChildren(h("div", { class: "loading", text: "Loading…" }));
  views[name](v).catch((err) => v.replaceChildren(h("div", { class: "empty", text: err.message })));
}
$("#nav").addEventListener("click", (e) => { const b = e.target.closest("button[data-view]"); if (b) go(b.dataset.view); });
$("#menuBtn").addEventListener("click", () => $("#side").classList.toggle("open"));

// ---------- new-order alerts (inside the dashboard only: nothing is emailed or messaged) ----------
let alertState = { newCount: 0, newIds: [], newest: [], waitingCount: 0, channels: {} };
const BASE_TITLE = document.title;
async function pollAlerts() {
  try {
    const d = await api("/alerts");
    const grew = d.newCount > alertState.newCount;
    alertState = d;
    const btn = document.querySelector('#nav button[data-view="orders"]');
    let badge = btn.querySelector(".badge");
    if (d.newCount) {
      if (!badge) { badge = h("span", { class: "badge", role: "status" }); btn.append(badge); }
      badge.textContent = d.newCount > 99 ? "99+" : String(d.newCount);
      badge.setAttribute("aria-label", `${d.newCount} new order${d.newCount === 1 ? "" : "s"}`);
    } else if (badge) badge.remove();
    document.title = d.newCount ? `(${d.newCount}) New orders – ${BASE_TITLE}` : BASE_TITLE;
    if (grew && alertState.__ready) toast(`${d.newCount} new order${d.newCount === 1 ? "" : "s"} waiting`);
    alertState.__ready = true;
    if ($("#title").textContent === "Overview" && !document.hidden) refreshAlertBanner();
  } catch { /* offline or signed out: the next poll tries again */ }
}
function alertBanner() {
  const d = alertState;
  if (!d.newCount && !d.waitingCount) return null;
  const parts = [];
  if (d.newCount) parts.push(h("strong", { text: `${d.newCount} new order${d.newCount === 1 ? "" : "s"}` }), " since you last looked. ");
  if (d.waitingCount) parts.push(`${d.waitingCount} waiting to be processed. `);
  return h("div", { class: "alert-banner", role: "status", id: "alertBanner" },
    h("div", {}, ...parts, h("button", { class: "link", onclick: () => go("orders"), text: "Open orders" }),
      h("div", { class: "muted", text: "These alerts show only while the dashboard is open. Email, WhatsApp and SMS alerts are not switched on yet." })),
    d.newest.length ? h("ul", {}, d.newest.map((o) => h("li", {}, h("strong", { text: o.id }), ` ${naira(o.total)} · ${o.city} · ${when(o.date)}`))) : null);
}
function refreshAlertBanner() {
  const old = $("#alertBanner"), fresh = alertBanner();
  if (old && fresh) old.replaceWith(fresh); else if (old) old.remove(); else if (fresh) { const v = $("#view"); v.insertBefore(fresh, v.firstChild); }
}
setInterval(() => { if (!document.hidden && !$("#app").hidden) pollAlerts(); }, 45000);
document.addEventListener("visibilitychange", () => { if (!document.hidden && !$("#app").hidden) pollAlerts(); });

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
  await pollAlerts();
  root.replaceChildren(
    alertBanner(),
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


// ---------- sales reports ----------
const SVG = "http://www.w3.org/2000/svg";
function svg(tag, attrs, ...kids) {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid != null) e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return e;
}
function revenueChart(series) {
  const W = 720, H = 240, L = 54, R = 12, T = 14, B = 30, iw = W - L - R, ih = H - T - B;
  const max = Math.max(1, ...series.map((x) => x.revenue));
  const step = Math.pow(10, Math.floor(Math.log10(max)));
  const top = Math.ceil(max / step) * step;
  const x = (i) => L + (series.length === 1 ? iw / 2 : (i * iw) / (series.length - 1));
  const y = (v) => T + ih - (v / top) * ih;
  const pts = series.map((d, i) => `${x(i).toFixed(1)},${y(d.revenue).toFixed(1)}`);
  const el = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "linechart", role: "img", "aria-label": `Revenue per day from ${series[0].date} to ${series[series.length - 1].date}` });
  for (let k = 0; k <= 4; k++) {
    const v = (top / 4) * k, yy = y(v);
    el.append(svg("line", { x1: L, x2: W - R, y1: yy, y2: yy, class: "grid" }), svg("text", { x: L - 8, y: yy + 4, class: "axis", "text-anchor": "end" }, v >= 1000 ? "₦" + Math.round(v / 1000) + "k" : "₦" + Math.round(v)));
  }
  const every = Math.max(1, Math.ceil(series.length / 8));
  series.forEach((d, i) => { if (i % every === 0 || i === series.length - 1) el.append(svg("text", { x: x(i), y: H - 8, class: "axis", "text-anchor": "middle" }, d.date.slice(5))); });
  el.append(svg("polygon", { points: `${L},${T + ih} ${pts.join(" ")} ${x(series.length - 1).toFixed(1)},${T + ih}`, class: "area" }), svg("polyline", { points: pts.join(" "), class: "line" }));
  series.forEach((d, i) => el.append(svg("circle", { cx: x(i), cy: y(d.revenue), r: series.length > 40 ? 2 : 3.5, class: "dot" }, svg("title", {}, `${d.date}: ${naira(d.revenue)} from ${d.orders} order${d.orders === 1 ? "" : "s"}`))));
  return el;
}
function ranked(title, rows, label, cols) {
  const max = Math.max(1, ...rows.map((r) => r.revenue));
  return h("div", { class: "panel" }, h("h2", { text: title }), rows.length
    ? h("div", { class: "rank" }, rows.map((r) => h("div", { class: "rank-row" },
        h("div", { class: "rank-top" }, h("strong", { text: r[label] }), h("span", { text: naira(r.revenue) })),
        h("div", { class: "rank-bar" }, h("i", { style: `width:${Math.max(3, Math.round((r.revenue / max) * 100))}%` })),
        h("small", { class: "muted", text: cols(r) }))))
    : h("p", { class: "muted", text: "Nothing sold in this period yet." }));
}
async function reports(root) {
  let days = 30;
  const body = h("div");
  const load = async () => {
    body.replaceChildren(h("div", { class: "loading", text: "Loading…" }));
    const d = await api(`/reports?days=${days}`);
    const card = (k, v, sub) => h("div", { class: "card" }, h("div", { class: "k", text: k }), h("div", { class: "v", text: v }), sub ? h("small", { class: "muted", text: sub }) : null);
    body.replaceChildren(
      h("div", { class: "cards" },
        card("Revenue", naira(d.revenue), `${d.from} to ${d.to}`), card("Orders", d.orders, d.cancelled ? `${d.cancelled} cancelled` : "none cancelled"),
        card("Average order", naira(d.averageOrder)), card("Items sold", d.itemsSold), card("Delivery fees", naira(d.deliveryFees)), card("Discounts given", naira(d.discountsGiven))),
      h("div", { class: "panel" }, h("h2", { text: `Revenue per day, last ${d.days} days` }), d.orders ? revenueChart(d.series) : h("div", { class: "empty", text: "No paid or confirmed orders in this period yet. Cancelled orders and unpaid pay-ahead orders are not counted as sales." })),
      h("div", { class: "two" },
        ranked("Top products", d.topProducts, "name", (r) => `${r.units} unit${r.units === 1 ? "" : "s"} in ${r.orders} order${r.orders === 1 ? "" : "s"}`),
        h("div", {}, ranked("By payment method", d.byPayment, "label", (r) => `${r.orders} order${r.orders === 1 ? "" : "s"}`), ranked("By delivery area", d.byArea, "label", (r) => `${r.orders} order${r.orders === 1 ? "" : "s"}`))));
  };
  const range = h("select", { "aria-label": "Report period", onchange: (e) => { days = Number(e.target.value); load().catch((err) => toast(err.message, true)); } },
    [[7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"]].map(([v, t]) => h("option", { value: v, text: t, selected: v === days })));
  const exportBtn = h("a", { class: "btn", href: "/api/store/admin/orders.csv", download: "", text: "Export all orders (CSV)" });
  const exportRange = h("a", { class: "btn", href: "#", text: "Export this period (CSV)", onclick: (e) => { e.preventDefault(); location.href = `/api/store/admin/orders.csv?days=${days}`; } });
  root.replaceChildren(h("div", { class: "toolbar" }, range, h("span", { class: "grow" }), exportRange, exportBtn), body);
  await load();
}

// ---------- customer reviews (moderation) ----------
async function reviews(root) {
  const d = await api("/reviews");
  const stars = (n) => "★".repeat(n) + "☆".repeat(5 - n);
  const list = d.reviews.map((r) => h("div", { class: "panel rev-admin" + (r.hidden ? " is-hidden" : "") },
    h("div", { class: "rev-admin-top" }, h("strong", { text: r.product }), h("span", { class: "stars-text", text: stars(r.rating) }), h("span", { class: "muted", text: `${r.name} (${r.email})` }), h("span", { class: "muted", text: when(r.updated) }), r.hidden ? h("span", { class: "tag", text: "Hidden" }) : null),
    r.body ? h("p", { text: r.body }) : h("p", { class: "muted", text: "(rating only, no written review)" }),
    h("button", { class: "btn sm", type: "button", text: r.hidden ? "Show again" : "Hide", onclick: async (e) => {
      e.target.disabled = true;
      try { await api("/reviews/hide", { method: "POST", body: { email: r.email, productId: r.productId, hidden: !r.hidden } }); toast(r.hidden ? "Review is visible again" : "Review hidden"); reviews(root); }
      catch (err) { toast(err.message, true); e.target.disabled = false; }
    } })));
  root.replaceChildren(
    h("p", { class: "muted", text: "Only customers who received a product can review it, so these are all verified purchases. You can hide a review that breaks your rules; it is kept on record and you can show it again. Reviews cannot be edited by staff." }),
    list.length ? h("div", {}, list) : h("div", { class: "empty", text: "No reviews yet. They appear here when a customer who received a product writes one." }));
}

// ---------- newsletter ----------
async function newsletter(root) {
  const d = await api("/subscribers");
  const rows = d.subscribers.map((r) => h("tr", {}, h("td", { text: r.email }), h("td", { text: when(r.subscribed) })));
  root.replaceChildren(
    h("div", { class: "toolbar" }, h("strong", { text: `${d.count} subscriber${d.count === 1 ? "" : "s"}` }), h("span", { class: "grow" }),
      h("a", { class: "btn", href: "/api/store/admin/subscribers.csv", download: "", text: "Export (CSV)" })),
    h("div", { class: "panel" }, h("p", { class: "muted", text: "These are people who asked, on the shop footer, to hear about offers. Nothing is sent from this site yet: sending a newsletter needs an email service to be connected. Each person can unsubscribe with their own link." })),
    d.count ? h("div", { class: "panel tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", { text: "Email" }), h("th", { text: "Subscribed" }))), h("tbody", {}, rows)))
            : h("div", { class: "panel empty", text: "No subscribers yet. The signup box is in the shop footer." }));
}

// ---------- orders ----------
async function orders(root) {
  let q = "", status = "";
  await pollAlerts();
  const freshIds = new Set(alertState.newIds);
  const list = h("div");
  const load = async () => {
    const d = await api(`/orders?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}`);
    list.replaceChildren(table(["Order", "Customer", "Items", "Total", "Status", "Action"], d.orders.map((o) => { const r = orderRow(o, load); if (freshIds.has(o.id)) r.classList.add("fresh"); return r; }), "No orders match."));
    return d;
  };
  const first = await api("/orders");
  const sel = h("select", { "aria-label": "Filter by status", onchange: (e) => { status = e.target.value; load(); } }, h("option", { value: "", text: "All statuses" }), first.statuses.map((s) => h("option", { value: s, text: s })));
  const search = h("input", { type: "search", placeholder: "Search order, phone or email", "aria-label": "Search orders", oninput: (e) => { q = e.target.value; clearTimeout(search._t); search._t = setTimeout(load, 250); } });
  root.replaceChildren(h("div", { class: "tools" }, search, sel), list);
  await load();
  // The rows are on screen with the new ones highlighted, so they now count as seen.
  if (freshIds.size) { try { await api("/alerts/seen", { method: "POST" }); await pollAlerts(); } catch { /* try again next visit */ } }
}
function orderRow(o, reload) {
  const next = { "Awaiting payment": ["Cancelled"], "Payment confirmed": ["Preparing your order", "Cancelled"], "Awaiting delivery — pay on arrival": ["Preparing your order", "Cancelled"], "Preparing your order": ["Ready for dispatch", "Cancelled"], "Ready for dispatch": ["Out for delivery", "Cancelled"], "Out for delivery": ["Delivered"] }[o.status] || [];
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
  const f = { id: p?.id || "", name: p?.name || "", cat: p?.cat || "", sub: p?.sub || "", brand: p?.brand || "", emoji: p?.emoji || "", description: p?.description || "", image: p?.image || "", stock: p?.stock ?? "", active: p ? p.active : true, featured: p?.featured || false };
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
  const preview = h("img", { class: "photo-preview", alt: "Product photo preview", hidden: !f.image, src: f.image || "" });
  const photoMsg = h("p", { class: "muted", text: f.image ? "Photo saved with this product." : "No photo yet. A picture is drawn for the product until you add one." });
  const fileInput = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", hidden: true, onchange: async (e) => {
    const file = e.target.files[0]; if (!file) return;
    photoMsg.textContent = "Uploading…";
    try {
      const fd = new FormData(); fd.append("file", file);
      let res; try { res = await fetch(API + "/images", { method: "POST", credentials: "same-origin", body: fd }); } catch { throw new Error("Cannot reach the store. Check your connection."); }
      let data = {}; try { data = await res.json(); } catch { /* empty */ }
      if (res.status === 401 || res.status === 403) { showLogin(); throw new Error("Please sign in again."); }
      if (!res.ok) throw new Error(data.error || "That photo could not be uploaded.");
      f.image = data.url; preview.src = data.url; preview.hidden = false;
      photoMsg.textContent = `Photo uploaded (${Math.round(data.bytes / 1024)} KB). Press Save to keep it.`;
    } catch (err) { photoMsg.textContent = err.message; }
    e.target.value = "";
  } });
  const photoBox = h("div", { class: "photo-box" }, preview,
    h("div", {}, h("div", { style: "display:flex;gap:8px;flex-wrap:wrap" },
      h("button", { type: "button", class: "btn sm", onclick: () => fileInput.click(), text: "Choose photo" }),
      h("button", { type: "button", class: "btn sm", onclick: () => { f.image = ""; preview.hidden = true; photoMsg.textContent = "Photo removed. Press Save to keep this change."; }, text: "Remove photo" })),
      photoMsg, h("p", { class: "muted", text: "JPEG, PNG or WebP, up to 5 MB. It is resized and stored safely for you." }), fileInput));
  const form = h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault(); msg.textContent = "";
    const body = { ...f, options: opts.map((o) => ({ label: o.label, price: o.price === "" ? "" : Number(o.price), was: o.was === "" ? "" : Number(o.was) })), stock: f.stock === "" ? null : Number(f.stock) };
    try { await api(isNew ? "/products" : `/products/${encodeURIComponent(p.id)}`, { method: isNew ? "POST" : "PUT", body }); toast(isNew ? "Product added" : "Product saved"); close(); done(); } catch (err) { msg.textContent = err.message; }
  } },
    isNew ? field("Product code (letters, numbers, - and _)", bind("id", { required: true, maxlength: "40" })) : null,
    field("Name", bind("name", { required: true, maxlength: "80" })),
    h("div", { class: "row2" }, field("Category", bind("cat", { required: true, maxlength: "40", list: "cats" })), field("Emoji (optional)", bind("emoji", { maxlength: "8" }))),
    h("div", { class: "row2" }, field("Type / subcategory (optional)", bind("sub", { maxlength: "40", list: "subs", placeholder: "e.g. Rice and grains" })), field("Brand (optional)", bind("brand", { maxlength: "40", list: "brands", placeholder: "Leave empty if unbranded" }))),
    field("Description", h("textarea", { maxlength: "600", oninput: (e) => (f.description = e.target.value), text: f.description })),
    h("div", {}, h("label", { text: "Product photo" }), photoBox),
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
  const dl = h("datalist", { id: "cats" }), dlSubs = h("datalist", { id: "subs" }), dlBrands = h("datalist", { id: "brands" });
  api("/products").then((d) => {
    const fill = (list, key) => { for (const v of new Set(d.products.map((x) => x[key]).filter(Boolean))) list.append(h("option", { value: v })); };
    fill(dl, "cat"); fill(dlSubs, "sub"); fill(dlBrands, "brand");
  }).catch(() => {});
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function close() { document.removeEventListener("keydown", onKey); modal.remove(); dl.remove(); dlSubs.remove(); dlBrands.remove(); }
  document.addEventListener("keydown", onKey); document.body.append(dl, dlSubs, dlBrands, modal);
  (isNew ? form.querySelector("input") : form.querySelector("input")).focus();
}

// ---------- stock history ----------
async function stock(root) {
  const prods = (await api("/products")).products.filter((p) => p.stock !== null);
  const sel = h("select", { "aria-label": "Product" }, h("option", { value: "", text: "All products" }), ...prods.map((p) => h("option", { value: p.id, text: `${p.name} (${p.stock} left)` })));
  const box = h("div");
  async function load() {
    const d = await api("/stock-history?limit=200" + (sel.value ? `&product=${encodeURIComponent(sel.value)}` : ""));
    box.replaceChildren(table(["When", "Product", "Change", "Left after", "Why"], d.moves.map((m) => h("tr", {},
      h("td", { text: when(m.at) }), h("td", { text: m.name }),
      h("td", {}, h("strong", { class: m.change < 0 ? "neg" : "pos", text: (m.change > 0 ? "+" : "") + m.change })),
      h("td", { text: m.after ?? "" }),
      h("td", {}, m.reason, m.orderId ? h("div", { class: "muted", text: `Order ${m.orderId}` }) : null, h("div", { class: "muted", text: m.actor === "admin" ? "by the store" : "by a customer" })))),
      "No stock changes recorded yet. Every sale, cancellation and correction will appear here."));
  }
  sel.onchange = load;
  root.replaceChildren(h("div", { class: "toolbar" }, sel, h("span", { class: "grow" }), h("span", { class: "muted", text: "Latest 200 changes" })), box);
  await load();
}

// ---------- discount codes ----------
function describeCode(c) {
  const what = c.kind === "percent" ? `${c.value}% off` : `${naira(c.value)} off`;
  const bits = [what];
  if (c.maxDiscount) bits.push(`up to ${naira(c.maxDiscount)}`);
  if (c.minOrder) bits.push(`orders from ${naira(c.minOrder)}`);
  bits.push(c.perCustomerOnce ? "once per customer" : "repeatable");
  if (c.endsAt) bits.push(`ends ${new Date(c.endsAt).toLocaleDateString("en-NG")}`);
  return bits.join(" · ");
}
async function discounts(root) {
  const d = await api("/discounts");
  const list = table(["Code", "What it does", "Used", "Given away", "Status", ""], d.codes.map((c) => {
    const expired = c.endsAt && new Date(c.endsAt) <= new Date();
    const full = c.maxUses && c.used >= c.maxUses;
    const state = !c.active ? "Paused" : expired ? "Expired" : full ? "Used up" : "Live";
    return h("tr", {}, h("td", {}, h("strong", { text: c.code }), c.note ? h("div", { class: "muted", text: c.note }) : null), h("td", { text: describeCode(c) }),
      h("td", { text: c.maxUses ? `${c.used} of ${c.maxUses}` : String(c.used) }), h("td", { text: naira(c.given) }), h("td", {}, h("span", { class: "pill " + (state === "Live" ? "ok" : ""), text: state })),
      h("td", {}, h("button", { class: "btn sm", onclick: () => codeEditor(c, () => discounts(root)), text: "Edit" })));
  }), "No discount codes yet. Create one to run a promotion.");
  root.replaceChildren(h("div", { class: "toolbar" }, h("span", { class: "grow" }), h("button", { class: "btn primary", onclick: () => codeEditor(null, () => discounts(root)), text: "+ New code" })), list);
}
function codeEditor(c, done) {
  const f = { code: c?.code || "", kind: c?.kind || "percent", value: c?.value ?? "", minOrder: c?.minOrder ?? "", maxDiscount: c?.maxDiscount ?? "", maxUses: c?.maxUses ?? "", perCustomerOnce: c ? c.perCustomerOnce : true, active: c ? c.active : true, note: c?.note || "", startsAt: (c?.startsAt || "").slice(0, 10), endsAt: (c?.endsAt || "").slice(0, 10) };
  const num = (v) => (v === "" || v == null ? null : Number(v));
  const msg = h("p", { class: "msg", role: "alert" });
  const inp = (label, key, extra = {}) => h("div", {}, h("label", { text: label }), h("input", { value: f[key], oninput: (e) => (f[key] = e.target.value), ...extra }));
  const kind = h("select", { "aria-label": "Type of discount", onchange: (e) => (f.kind = e.target.value) }, h("option", { value: "percent", text: "Percentage off", selected: f.kind === "percent" }), h("option", { value: "fixed", text: "Fixed amount off (₦)", selected: f.kind === "fixed" }));
  const form = h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault(); msg.textContent = "";
    const body = { code: f.code, kind: f.kind, value: num(f.value), minOrder: num(f.minOrder), maxDiscount: num(f.maxDiscount), maxUses: num(f.maxUses), perCustomerOnce: f.perCustomerOnce, active: f.active, note: f.note, startsAt: f.startsAt ? `${f.startsAt}T00:00:00Z` : null, endsAt: f.endsAt ? `${f.endsAt}T23:59:59Z` : null };
    try { await api("/discounts", { method: "POST", body }); toast(c ? "Code saved" : "Code created"); close(); done(); } catch (err) { msg.textContent = err.message; }
  } },
    c ? h("p", {}, h("strong", { text: c.code })) : inp("Code (letters and numbers, e.g. WELCOME10)", "code", { required: true, maxlength: "24" }),
    h("div", { class: "row2" }, h("div", {}, h("label", { text: "Type" }), kind), inp("Amount (% or ₦)", "value", { type: "number", min: "1", required: true })),
    h("div", { class: "row2" }, inp("Minimum order ₦ (optional)", "minOrder", { type: "number", min: "1" }), inp("Most it can take off ₦ (optional)", "maxDiscount", { type: "number", min: "1" })),
    h("div", { class: "row2" }, inp("Total uses allowed (optional)", "maxUses", { type: "number", min: "1" }), inp("Note for yourself (optional)", "note", { maxlength: "120" })),
    h("div", { class: "row2" }, inp("Starts (optional)", "startsAt", { type: "date" }), inp("Ends (optional)", "endsAt", { type: "date" })),
    h("div", { class: "checks" },
      h("label", {}, h("input", { type: "checkbox", checked: f.perCustomerOnce, onchange: (e) => (f.perCustomerOnce = e.target.checked) }), "Each customer can use it once"),
      h("label", {}, h("input", { type: "checkbox", checked: f.active, onchange: (e) => (f.active = e.target.checked) }), "Live (untick to pause)")),
    h("p", { class: "muted", text: "The code only takes money off the groceries, never the delivery fee. Cancelling an order gives its use back." }),
    msg, h("div", { style: "display:flex;gap:8px" }, h("button", { class: "btn primary", type: "submit", text: "Save" }), h("button", { class: "btn", type: "button", onclick: () => close(), text: "Cancel" })));
  const modal = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": c ? "Edit discount code" : "New discount code" }, h("div", { class: "box" }, h("div", { class: "head" }, h("h2", { text: c ? "Edit discount code" : "New discount code" }), h("button", { class: "x", "aria-label": "Close", onclick: () => close(), text: "✕" })), form));
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function close() { document.removeEventListener("keydown", onKey); modal.remove(); }
  document.addEventListener("keydown", onKey); document.body.append(modal);
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
  const areas = s.areas.map((a) => ({ name: a.name, fee: a.fee, eta: a.eta || "" }));
  const areaBox = h("div");
  const drawAreas = () => areaBox.replaceChildren(...areas.map((a, i) => h("div", { class: "optrow", style: "grid-template-columns:2fr 1fr 1.4fr auto" },
    h("input", { value: a.name, placeholder: "Area name", "aria-label": "Area name", oninput: (e) => (a.name = e.target.value) }),
    h("input", { type: "number", min: "0", max: "100000", value: a.fee, placeholder: "Fee ₦", "aria-label": "Delivery fee in naira", oninput: (e) => (a.fee = e.target.value) }),
    h("input", { value: a.eta, maxlength: "40", placeholder: "Time, e.g. 1-2 hours (optional)", "aria-label": "Estimated delivery time", oninput: (e) => (a.eta = e.target.value) }),
    h("button", { type: "button", class: "btn sm danger", "aria-label": "Remove area", onclick: () => { if (areas.length > 1) { areas.splice(i, 1); drawAreas(); } }, text: "✕" }))));
  drawAreas();
  const form = h("form", { class: "form panel", onsubmit: async (e) => {
    e.preventDefault(); msg.textContent = "";
    const body = { storeName: $("#sName").value, banner: $("#sBanner").value, whatsapp: $("#sWa").value, contactPhone: $("#sPhone").value,
      social: Object.fromEntries(Object.keys(s.socialNetworks).map((k) => [k, $("#soc_" + k).value])),
      areas: areas.map((a) => ({ name: a.name, fee: a.fee === "" ? "" : Number(a.fee), eta: a.eta })),
      bank: { bank: $("#sBank").value, accountName: $("#sAcctName").value, accountNumber: $("#sAcctNo").value } };
    try { await api("/settings", { method: "PUT", body }); toast("Settings saved"); } catch (err) { msg.textContent = err.message; }
  } },
    h("h2", { text: "Delivery areas and fees" }),
    h("p", { class: "muted", text: "Customers choose one of these at checkout, and the fee is looked up on the server. The first area is the default." }),
    areaBox, h("button", { type: "button", class: "btn sm", onclick: () => { if (areas.length < 40) { areas.push({ name: "", fee: "", eta: "" }); drawAreas(); } }, text: "+ Add area" }),
    h("h2", { style: "margin-top:18px", text: "Bank account for pay-before-delivery" }),
    h("p", { class: "muted", text: s.bank.ready ? "Customers can pay by bank transfer to this account." : "Pay-before-delivery is OFF until you enter your real account. Nothing is shown to customers until all three fields are filled." }),
    inp("sBank", "Bank", s.bank.bank, { maxlength: "60" }), inp("sAcctName", "Account name", s.bank.accountName, { maxlength: "80" }), inp("sAcctNo", "Account number (10 digits)", s.bank.accountNumber, { inputmode: "numeric", maxlength: "13" }),
    h("h2", { style: "margin-top:18px", text: "Store details" }),
    inp("sName", "Store name", s.storeName, { maxlength: "80" }), inp("sBanner", "Promotional banner text (optional)", s.banner, { maxlength: "200" }),
    inp("sWa", "WhatsApp number", s.whatsapp, { placeholder: "0801 234 5678" }), inp("sPhone", "Contact phone", s.contactPhone, { placeholder: "0801 234 5678" }),
    h("h2", { style: "margin-top:18px", text: "Social media links" }),
    h("p", { class: "muted", text: "Shown in the shop footer only when filled in. Paste the full address of your page. Leave blank to hide." }),
    ...Object.entries(s.socialNetworks).map(([k, label]) => inp("soc_" + k, label, (s.social || {})[k] || "", { placeholder: "https://", maxlength: "200" })),
    msg, h("button", { class: "btn primary", type: "submit", text: "Save settings" }),
    h("p", { class: "muted", text: "Online payment (Paystack) and SMS or WhatsApp notifications stay off until you supply real accounts and keys." }));
  root.replaceChildren(form);
}


// ---------- admin team (owner only) ----------
async function admins(root) {
  if (!me || me.level !== "owner") { root.replaceChildren(h("div", { class: "empty", text: "Only the store owner can manage the admin team." })); return; }
  const d = await api("/admins");
  const rows = d.admins.map((a) => {
    const self = a.email === me.email;
    return h("tr", {},
      h("td", {}, h("strong", { text: a.name }), self ? h("span", { class: "muted", text: " (you)" }) : null, h("div", { class: "muted", text: a.email }), h("div", { class: "muted", text: a.phone })),
      h("td", {}, h("span", { class: "pill " + (a.role === "owner" ? "owner" : ""), text: a.role === "owner" ? "Owner" : "Staff" })),
      h("td", {}, h("span", { class: "pill " + (a.active ? "ok" : ""), text: a.active ? (a.mustChange ? "Active, password not yet changed" : "Active") : "Deactivated" })),
      h("td", { text: a.lastLogin ? when(a.lastLogin) : "Never" }),
      h("td", {}, h("div", { style: "display:flex;gap:6px;flex-wrap:wrap" },
        h("button", { class: "btn sm", text: a.active ? "Deactivate" : "Reactivate", onclick: async () => { try { await api(`/admins/${encodeURIComponent(a.email)}/active`, { method: "POST", body: { active: !a.active } }); toast(a.active ? "Deactivated" : "Reactivated"); admins(root); } catch (err) { toast(err.message, true); } } }),
        h("button", { class: "btn sm", text: a.role === "owner" ? "Make staff" : "Make owner", onclick: async () => { try { await api(`/admins/${encodeURIComponent(a.email)}/role`, { method: "POST", body: { role: a.role === "owner" ? "staff" : "owner" } }); toast("Role changed"); admins(root); } catch (err) { toast(err.message, true); } } }),
        h("button", { class: "btn sm", text: "Reset password", onclick: () => resetPw(a, () => admins(root)) }))));
  });
  root.replaceChildren(
    h("div", { class: "toolbar" }, h("span", { class: "grow" }), h("button", { class: "btn primary", onclick: () => adminEditor(() => admins(root)), text: "+ Add admin" })),
    table(["Person", "Role", "Status", "Last sign-in", ""], rows, "No admins yet."),
    h("p", { class: "muted", text: "Owners can manage this team. Staff can run orders, products and customers but cannot see or change admin accounts. Every action is recorded under the person's name. The shared staff key only ever gives staff access." }));
}
function openModal(title, form) {
  const modal = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title }, h("div", { class: "box" }, h("div", { class: "head" }, h("h2", { text: title }), h("button", { class: "btn sm", "aria-label": "Close", onclick: () => close(), text: "✕" })), form));
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function close() { document.removeEventListener("keydown", onKey); modal.remove(); }
  document.addEventListener("keydown", onKey); document.body.append(modal);
  return close;
}
function adminEditor(done) {
  const f = { name: "", email: "", phone: "", role: "staff", password: "" };
  const msg = h("p", { class: "msg", role: "alert" });
  const inp = (label, key, extra = {}) => h("div", {}, h("label", { text: label }), h("input", { value: f[key], oninput: (e) => (f[key] = e.target.value), ...extra }));
  let close;
  const role = h("select", { "aria-label": "Role", onchange: (e) => (f.role = e.target.value) }, h("option", { value: "staff", text: "Staff (orders, products, customers)" }), h("option", { value: "owner", text: "Owner (everything, including the admin team)" }));
  const form = h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault(); msg.textContent = "";
    try { await api("/admins", { method: "POST", body: f }); toast("Admin added"); close(); done(); } catch (err) { msg.textContent = err.message; }
  } },
    inp("Full name", "name", { required: true, maxlength: "80" }), inp("Email", "email", { type: "email", required: true, maxlength: "120" }), inp("Nigerian mobile number", "phone", { required: true, inputmode: "tel", placeholder: "0803 123 4567" }),
    h("div", {}, h("label", { text: "Role" }), role),
    inp("First password (they must change it when they first sign in)", "password", { type: "text", required: true, minlength: "8", maxlength: "72", autocomplete: "off" }),
    msg, h("div", { style: "display:flex;gap:8px" }, h("button", { class: "btn primary", type: "submit", text: "Add admin" }), h("button", { class: "btn", type: "button", onclick: () => close(), text: "Cancel" })));
  close = openModal("Add admin", form);
}
function resetPw(a, done) {
  const f = { password: "" }; const msg = h("p", { class: "msg", role: "alert" }); let close;
  const form = h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault(); msg.textContent = "";
    try { await api(`/admins/${encodeURIComponent(a.email)}/reset-password`, { method: "POST", body: f }); toast("Password reset"); close(); done(); } catch (err) { msg.textContent = err.message; }
  } },
    h("p", { text: `Set a temporary password for ${a.name}. They must choose their own at next sign-in.` }),
    h("div", {}, h("label", { text: "Temporary password" }), h("input", { oninput: (e) => (f.password = e.target.value), required: true, minlength: "8", maxlength: "72", autocomplete: "off" })),
    msg, h("div", { style: "display:flex;gap:8px" }, h("button", { class: "btn primary", type: "submit", text: "Reset password" }), h("button", { class: "btn", type: "button", onclick: () => close(), text: "Cancel" })));
  close = openModal("Reset password", form);
}

// ---------- start ----------
(async () => {
  try {
    // /me answers for a signed-in admin who still has to choose a password; /session does not.
    const r = await fetch("/api/store/session", { credentials: "same-origin" }); const d = await r.json();
    if (d.staff || d.signedIn) await afterSignIn(); else showLogin();
  } catch { showLogin(); }
})();

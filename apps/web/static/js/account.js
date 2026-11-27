/* My account page. Customer data is only ever put into the page with textContent / value,
   never innerHTML, so a name or address can't inject markup. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var areas = JSON.parse(document.querySelector(".acct").dataset.areas || "[]");
  var naira = function (n) { return "₦" + Number(n || 0).toLocaleString("en-NG"); };
  var state = { addresses: [], favourites: [], profile: null };

  function el(tag, props, kids) {
    var e = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      if (k === "text") e.textContent = props[k]; else if (k === "class") e.className = props[k]; else e.setAttribute(k, props[k]);
    });
    (kids || []).forEach(function (c) { e.appendChild(c); });
    return e;
  }
  function notice(text, bad) {
    var n = $("acctNotice"); n.textContent = text; n.className = "msg " + (bad ? "err" : "ok"); n.hidden = false;
    n.scrollIntoView({ block: "nearest" });
    clearTimeout(notice.t); notice.t = setTimeout(function () { n.hidden = true; }, 6000);
  }
  async function api(method, url, body) {
    var res = await fetch(url, { method: method, headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: body ? JSON.stringify(body) : undefined });
    var data = {}; try { data = await res.json(); } catch (e) { /* empty */ }
    if (res.status === 401) { location.href = "/?signin=1"; throw new Error("signed out"); }
    if (!res.ok) throw new Error(data.error || "Something went wrong. Please try again.");
    return data;
  }

  function showTab(name) {
    document.querySelectorAll(".acct-tabs [data-tab]").forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.tab === name)); });
    document.querySelectorAll(".acct-panel").forEach(function (p) { p.hidden = p.id !== "tab-" + name; });
    if (history.replaceState) history.replaceState(null, "", "#" + name);
  }
  document.querySelectorAll("[data-tab]").forEach(function (b) { b.addEventListener("click", function () { showTab(b.dataset.tab); }); });
  document.querySelectorAll("[data-goto]").forEach(function (b) { b.addEventListener("click", function () { showTab(b.dataset.goto); }); });

  function renderAddresses() {
    var host = $("addrList"); host.textContent = "";
    if (!state.addresses.length) { host.appendChild(el("div", { class: "empty-note", text: "No saved addresses yet. Add one below and checkout gets faster." })); return; }
    state.addresses.forEach(function (a) {
      var card = el("div", { class: "addr-card" }, [
        el("div", { class: "addr-head" }, [el("strong", { text: a.label }), a.isDefault ? el("span", { class: "pill-cat", text: "Default" }) : el("span")]),
        el("div", { text: a.address }), el("div", { class: "muted", text: a.area + " · " + a.phone }),
      ]);
      var row = el("div", { class: "acct-actions" });
      var edit = el("button", { type: "button", class: "status-btn", text: "Edit" }); edit.onclick = function () { fillAddr(a); };
      var del = el("button", { type: "button", class: "status-btn danger", text: "Remove" });
      del.onclick = async function () {
        if (!confirm("Remove this address?")) return;
        try { await api("DELETE", "/api/account/addresses/" + encodeURIComponent(a.id)); await load(); notice("Address removed."); } catch (e) { notice(e.message, true); }
      };
      row.appendChild(edit); row.appendChild(del); card.appendChild(row); host.appendChild(card);
    });
  }
  function fillAddr(a) {
    $("addrFormTitle").textContent = a ? "Edit address" : "Add a delivery address";
    $("addrId").value = a ? a.id : ""; $("addrLabel").value = a ? a.label : "";
    $("addrArea").value = a ? a.area : (areas[0] ? areas[0].name : ""); $("addrAddress").value = a ? a.address : "";
    $("addrPhone").value = a ? a.phone : (state.profile ? state.profile.phone : ""); $("addrDefault").checked = a ? a.isDefault : false;
    $("addrCancel").hidden = !a; $("addrSave").textContent = a ? "Save changes" : "Save address";
    if (a) $("addrForm").scrollIntoView({ block: "center" });
  }
  function renderFavourites() {
    var host = $("favHost"); host.textContent = "";
    if (!state.favourites.length) { host.appendChild(el("div", { class: "empty-note", text: "You haven't saved any favourites yet. Tap the heart on a product to keep it here." })); return; }
    state.favourites.forEach(function (p) {
      var a = el("a", { class: "mini-card", href: "/product/" + encodeURIComponent(p.id) }, [
        el("span", { class: "mini-name", text: p.name }), el("span", { class: "mini-price", text: "From " + naira(p.from) }),
      ]);
      host.appendChild(a);
    });
  }
  async function load() {
    var d = await api("GET", "/api/account");
    state.profile = d.profile; state.addresses = d.addresses; state.favourites = d.favouriteProducts || [];
    $("stOrders").textContent = d.orderCount; $("stSpent").textContent = naira(d.totalSpent);
    $("stAddr").textContent = d.addresses.length; $("stFavs").textContent = state.favourites.length;
    $("helloLine").textContent = "Welcome back, " + d.profile.name.split(" ")[0] + ".";
    $("pfName").value = d.profile.name; $("pfEmail").value = d.profile.email; $("pfPhone").value = d.profile.phone;
    renderAddresses(); renderFavourites();
    if (!$("addrId").value) fillAddr(null);
  }

  areas.forEach(function (a) { $("addrArea").appendChild(el("option", { value: a.name, text: a.name + " (" + naira(a.fee) + " delivery)" })); });

  $("addrForm").addEventListener("submit", async function (e) {
    e.preventDefault();
    var id = $("addrId").value;
    var body = { label: $("addrLabel").value, area: $("addrArea").value, address: $("addrAddress").value, phone: $("addrPhone").value, isDefault: $("addrDefault").checked };
    try {
      await api(id ? "PUT" : "POST", "/api/account/addresses" + (id ? "/" + encodeURIComponent(id) : ""), body);
      $("addrId").value = ""; await load(); fillAddr(null); notice("Address saved.");
    } catch (err) { notice(err.message, true); }
  });
  $("addrCancel").addEventListener("click", function () { $("addrId").value = ""; fillAddr(null); });
  $("profileForm").addEventListener("submit", async function (e) {
    e.preventDefault();
    try { await api("PUT", "/api/account/profile", { name: $("pfName").value, phone: $("pfPhone").value }); await load(); notice("Your details have been updated."); } catch (err) { notice(err.message, true); }
  });
  $("passwordForm").addEventListener("submit", async function (e) {
    e.preventDefault();
    if ($("pwNew").value !== $("pwConfirm").value) { notice("The new passwords don't match.", true); return; }
    try {
      await api("POST", "/api/account/password", { currentPassword: $("pwCurrent").value, newPassword: $("pwNew").value });
      $("passwordForm").reset(); notice("Password changed.");
    } catch (err) { notice(err.message, true); }
  });
  $("acctLogout").addEventListener("click", async function () { await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" }); location.href = "/"; });

  /* "Order these again" on the orders tab: write the lines into the saved cart (ids, size, quantity only;
     the shop re-reads names and prices from the server) and open the shop with the cart showing. */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest(".reorder-btn");
    if (!btn) return;
    try {
      var ids = JSON.parse(btn.dataset.reorder), opts = JSON.parse(btn.dataset.reorderOptions), qtys = JSON.parse(btn.dataset.reorderQty);
      var cart = [];
      try { cart = JSON.parse(localStorage.getItem("fm_cart_v1") || "[]") || []; } catch (x) { cart = []; }
      ids.forEach(function (id, i) {
        var q = Math.min(50, Math.max(1, parseInt(qtys[i], 10) || 1)), o = parseInt(opts[i], 10) || 0;
        var hit = cart.filter(function (r) { return r.productId === id && r.optionIndex === o; })[0];
        if (hit) hit.qty = Math.min(50, hit.qty + q); else cart.push({ productId: id, optionIndex: o, qty: q, note: "" });
      });
      localStorage.setItem("fm_cart_v1", JSON.stringify(cart.slice(0, 40)));
      location.href = "/?cart=1";
    } catch (err) { notice("Sorry, we couldn't add those items to your cart.", true); }
  });

  // Ask for a replacement transfer account from the order history, then reload the list.
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest ? ev.target.closest("[data-reissue-account]") : null;
    if (!btn || btn.disabled) return;
    var id = btn.getAttribute("data-reissue-account");
    var label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Creating a new account\u2026";
    fetch("/api/payments/" + encodeURIComponent(id) + "/new-account", {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (res) {
        return res.json().then(function (data) { return { ok: res.ok, data: data }; });
      })
      .then(function (out) {
        if (!out.ok || !out.data || !out.data.payment) {
          throw new Error((out.data && out.data.error) || "Could not create a new account.");
        }
        btn.textContent = "New account ready";
        if (window.htmx) {
          window.htmx.ajax("GET", "/ui/orders", { target: "#ordersHost", swap: "innerHTML" });
        } else {
          location.reload();
        }
      })
      .catch(function (err) {
        btn.disabled = false;
        btn.textContent = label;
        notice(err.message || "Could not create a new account.", true);
      });
  });

  var start = (location.hash || "").slice(1);
  load().then(function () { if (["orders", "addresses", "favourites", "profile"].indexOf(start) >= 0) showTab(start); }).catch(function () {});

  // Payment instructions live in the order history too, so an account number is never lost
  // when the checkout confirmation is closed.
  document.addEventListener("click", function (ev) {
    var btn = ev.target && ev.target.closest ? ev.target.closest("[data-copy-account]") : null;
    if (!btn) return;
    var value = btn.getAttribute("data-copy-account") || "";
    var done = function (ok) {
      btn.textContent = ok ? "Copied ✓" : "Press and hold the number";
      window.setTimeout(function () { btn.textContent = "Copy account number"; }, 2000);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(function () { done(true); }, function () { done(false); });
    } else { done(false); }
  });
})();

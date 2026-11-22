// Product reviews: submits the review form. The page itself (stars, list, counts) is rendered
// by the server, so reading reviews works without JavaScript.
(function () {
  "use strict";
  var form = document.getElementById("reviewForm");
  if (!form) return;
  var msg = document.getElementById("revMsg");
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    msg.className = "rev-msg"; msg.textContent = "";
    var chosen = form.querySelector("input[name=rating]:checked");
    if (!chosen) { msg.classList.add("bad"); msg.textContent = "Please choose a star rating."; return; }
    var btn = form.querySelector("button[type=submit]"); btn.disabled = true;
    fetch("/api/products/" + encodeURIComponent(form.dataset.product) + "/reviews", {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating: Number(chosen.value), body: form.elements.body.value })
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (!x.ok) { msg.classList.add("bad"); msg.textContent = (x.d && x.d.error) || "Sorry, that did not work. Please try again."; btn.disabled = false; return; }
        msg.classList.add("ok"); msg.textContent = "Thank you. Your review has been saved.";
        setTimeout(function () { location.hash = "reviews"; location.reload(); }, 700);
      })
      .catch(function () { msg.classList.add("bad"); msg.textContent = "No connection. Please try again."; btn.disabled = false; });
  });
})();

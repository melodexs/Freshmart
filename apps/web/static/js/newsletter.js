// Footer newsletter signup. The server validates; this only submits and shows the answer.
(function () {
  "use strict";
  var form = document.getElementById("newsForm");
  if (!form) return;
  var msg = document.getElementById("newsMsg"), input = document.getElementById("newsEmail"), btn = form.querySelector("button[type=submit]");
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    msg.className = "news-msg";
    var email = input.value.trim();
    if (!email) { msg.classList.add("bad"); msg.textContent = "Please enter your email address."; input.focus(); return; }
    btn.disabled = true; msg.textContent = "Subscribing…";
    fetch("/api/newsletter", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: email }) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; }); })
      .then(function (x) {
        btn.disabled = false;
        if (x.ok) { msg.classList.add("ok"); msg.textContent = x.d.message || "Thank you. You are on our list."; input.value = ""; return; }
        msg.classList.add("bad");
        msg.textContent = x.status === 429 ? "Too many attempts. Please try again in a few minutes." : (x.d && x.d.error) || "Sorry, that did not work. Please try again.";
      })
      .catch(function () { btn.disabled = false; msg.classList.add("bad"); msg.textContent = "No connection. Please try again."; });
  });
})();

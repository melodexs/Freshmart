// Forgot / reset password pages. The server decides everything; this only submits and shows its answer.
(function () {
  "use strict";
  var msg = document.getElementById("authMsg");
  function say(text, kind) { msg.className = "auth-msg" + (kind ? " " + kind : ""); msg.textContent = text; }
  function post(url, body) {
    return fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, status: r.status, d: d }; }); });
  }

  var forgot = document.getElementById("forgotForm");
  if (forgot) {
    var help = document.getElementById("contactHelp"), btn = forgot.querySelector("button");
    // Tell the truth up front: if email is not switched on, say so before asking for anything.
    fetch("/api/auth/reset/status").then(function (r) { return r.json(); }).then(function (s) {
      if (!s.emailAvailable) {
        document.getElementById("forgotIntro").textContent = "Reset by email is not switched on for this store yet.";
        say("We cannot email a reset link right now. Please contact the store and we will help you get back in.", "bad");
        help.hidden = false; btn.disabled = true; document.getElementById("fpEmail").disabled = true;
      }
    }).catch(function () {});
    forgot.addEventListener("submit", function (e) {
      e.preventDefault();
      var email = document.getElementById("fpEmail").value.trim();
      if (!email) { say("Please enter your email address.", "bad"); return; }
      btn.disabled = true; say("Please wait…");
      post("/api/auth/forgot", { email: email }).then(function (x) {
        if (x.ok) { say(x.d.message, "ok"); btn.disabled = false; return; }
        say(x.status === 429 ? "Too many attempts. Please try again in a few minutes." : (x.d.error || "Sorry, that did not work."), "bad");
        if (x.status === 503) help.hidden = false; else btn.disabled = false;
      }).catch(function () { say("No connection. Please try again.", "bad"); btn.disabled = false; });
    });
  }

  var reset = document.getElementById("resetForm");
  if (reset) {
    var token = reset.dataset.token, rbtn = reset.querySelector("button");
    fetch("/api/auth/reset/check?token=" + encodeURIComponent(token)).then(function (r) { return r.json(); }).then(function (s) {
      if (!s.valid) {
        document.getElementById("resetIntro").textContent = "This reset link is not valid or has expired.";
        say("Please ask for a new link.", "bad");
        rbtn.textContent = "Ask for a new link"; rbtn.type = "button"; rbtn.onclick = function () { location.href = "/forgot-password"; };
        document.getElementById("newPw").disabled = true; document.getElementById("newPw2").disabled = true;
        reset.dataset.dead = "1";
      }
    }).catch(function () {});
    reset.addEventListener("submit", function (e) {
      e.preventDefault();
      if (reset.dataset.dead) return;
      var a = document.getElementById("newPw").value, b = document.getElementById("newPw2").value;
      if (a.length < 6) { say("The new password should be at least 6 characters.", "bad"); return; }
      if (a !== b) { say("The two passwords do not match.", "bad"); return; }
      rbtn.disabled = true; say("Saving…");
      post("/api/auth/reset", { token: token, password: a }).then(function (x) {
        if (x.ok) {
          say(x.d.message + " Taking you to the shop…", "ok");
          document.getElementById("newPw").value = ""; document.getElementById("newPw2").value = "";
          setTimeout(function () { location.href = "/"; }, 1800);
          return;
        }
        say(x.status === 429 ? "Too many attempts. Please try again in a few minutes." : (x.d.error || "Sorry, that did not work."), "bad");
        rbtn.disabled = false;
      }).catch(function () { say("No connection. Please try again.", "bad"); rbtn.disabled = false; });
    });
  }
})();

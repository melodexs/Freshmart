// Welcome-page motion. Progressive enhancement: the page is fully usable without this file.
(function () {
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var root = document.documentElement;

  function stagger(section) {
    var kids = section.querySelectorAll(".cat-card, .mini-card, .trust-grid > div");
    for (var i = 0; i < kids.length; i++) kids[i].style.setProperty("--i", String(Math.min(i, 10)));
  }

  function countUp(el) {
    var target = parseInt(el.getAttribute("data-count"), 10);
    if (!isFinite(target) || target <= 0 || reduce) return;
    var start = null, dur = 1300;
    el.textContent = "0";
    function frame(ts) {
      if (start === null) start = ts;
      var t = Math.min(1, (ts - start) / dur), eased = 1 - Math.pow(1 - t, 3);
      el.textContent = String(Math.round(target * eased));
      if (t < 1) requestAnimationFrame(frame); else el.textContent = String(target);
    }
    requestAnimationFrame(frame);
  }

  // Sort & filter: a toggle on phones, always-open inline controls on wide screens. A closed
  // <details> hides its content in every browser, so keep it open when the toggle isn't shown.
  var filters = document.querySelector(".more-filters");
  if (filters && window.matchMedia) {
    var wide = window.matchMedia("(min-width: 621px)");
    var sync = function () { if (wide.matches) filters.setAttribute("open", ""); };
    sync();
    if (wide.addEventListener) wide.addEventListener("change", function () {
      if (wide.matches) filters.setAttribute("open", ""); else filters.removeAttribute("open");
    });
  }

  var sections = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
  sections.forEach(stagger);

  if (!reduce && "IntersectionObserver" in window) {
    root.classList.add("js"); // only now are .reveal blocks allowed to start hidden
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    sections.forEach(function (s) { io.observe(s); });
    // Safety net: never leave content hidden if the observer is slow or blocked.
    setTimeout(function () { sections.forEach(function (s) { s.classList.add("in"); }); }, 4000);
  }

  var counters = document.querySelectorAll("[data-count]");
  for (var i = 0; i < counters.length; i++) countUp(counters[i]);

  // Gentle parallax on the hero photos (desktop pointers only).
  var stage = document.querySelector(".hero-stage");
  var fine = window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  if (stage && fine && !reduce) {
    var hero = document.querySelector(".hero"), cards = stage.querySelectorAll(".float-card"), raf = 0, mx = 0, my = 0;
    hero.addEventListener("mousemove", function (ev) {
      var r = hero.getBoundingClientRect();
      mx = (ev.clientX - r.left) / r.width - 0.5; my = (ev.clientY - r.top) / r.height - 0.5;
      if (!raf) raf = requestAnimationFrame(function () {
        raf = 0;
        for (var k = 0; k < cards.length; k++) {
          var d = (k % 2 ? -1 : 1) * (8 + k * 4);
          cards[k].style.translate = (mx * d).toFixed(1) + "px " + (my * d).toFixed(1) + "px";
        }
      });
    });
  }
})();

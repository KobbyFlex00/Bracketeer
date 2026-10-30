// Live search: <input data-filter="#table-id"> hides rows whose text doesn't match.
document.querySelectorAll("input[data-filter]").forEach(function (input) {
  var target = document.querySelector(input.dataset.filter);
  if (!target) return;
  input.addEventListener("input", function () {
    var q = input.value.trim().toLowerCase();
    target.querySelectorAll("[data-row]").forEach(function (row) {
      row.hidden = q !== "" && row.textContent.toLowerCase().indexOf(q) === -1;
    });
  });
});
// Confirm destructive buttons: <button data-confirm="Are you sure?">
document.addEventListener("click", function (e) {
  var btn = e.target.closest("[data-confirm]");
  if (btn && !window.confirm(btn.dataset.confirm)) e.preventDefault();
});
// Pause auto-refresh while the user is typing so the page doesn't reload mid-search.
document.addEventListener("input", function () {
  var meta = document.querySelector("meta[http-equiv=refresh]");
  if (meta) meta.remove();
});
// Rating chart: a crosshair snaps to the nearest round and shows its rating.
document.querySelectorAll(".rating-chart .hit").forEach(function (hit) {
  var svg = hit.ownerSVGElement, wrap = svg.parentNode;
  var points = JSON.parse(hit.dataset.points), tip = wrap.querySelector(".charttip");
  var cross = svg.querySelector(".cross"), dot = svg.querySelector(".dot"), idx = points.length - 1;
  function show(i) {
    idx = Math.max(0, Math.min(points.length - 1, i));
    var p = points[idx], box = svg.getBoundingClientRect(), scale = box.width / svg.viewBox.baseVal.width;
    cross.setAttribute("x1", p.x); cross.setAttribute("x2", p.x); cross.hidden = false;
    dot.setAttribute("cx", p.x); dot.setAttribute("cy", p.y); dot.hidden = false;
    tip.textContent = "";
    var b = document.createElement("strong"); b.textContent = p.rating; tip.appendChild(b);
    tip.appendChild(document.createTextNode(" · " + p.t + ", " + p.label));
    tip.hidden = false;
    var half = tip.offsetWidth / 2, lo = wrap.scrollLeft + half, hi = wrap.scrollLeft + wrap.clientWidth - half;
    tip.style.left = Math.max(lo, Math.min(hi, p.x * scale)) + "px"; tip.style.top = (p.y * scale) + "px";  // stay in view
  }
  function hide() { cross.hidden = dot.hidden = tip.hidden = true; }
  hit.addEventListener("pointermove", function (e) {
    var box = svg.getBoundingClientRect(), x = (e.clientX - box.left) * svg.viewBox.baseVal.width / box.width, best = 0;
    points.forEach(function (p, i) { if (Math.abs(p.x - x) < Math.abs(points[best].x - x)) best = i; });
    show(best);
  });
  hit.addEventListener("pointerleave", hide);
  hit.addEventListener("focus", function () { show(idx); });
  hit.addEventListener("blur", hide);
  hit.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); show(idx + (e.key === "ArrowLeft" ? -1 : 1)); }
  });
});
// Light/dark toggle: remembers the choice in this browser; without one the device setting applies.
(function () {
  var btn = document.querySelector("[data-theme-toggle]"), root = document.documentElement;
  if (!btn) return;
  var dark = window.matchMedia("(prefers-color-scheme: dark)");
  function current() { return root.dataset.theme || (dark.matches ? "dark" : "light"); }
  function label() { btn.setAttribute("aria-label", current() === "dark" ? "Switch to light mode" : "Switch to dark mode"); }
  btn.addEventListener("click", function () {
    var next = current() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
    label();
  });
  if (dark.addEventListener) dark.addEventListener("change", label);
  else if (dark.addListener) dark.addListener(label);  // Safari before 14
  // Another tab changed the theme: follow it.
  window.addEventListener("storage", function (e) {
    if (e.key !== "theme") return;
    if (e.newValue === "light" || e.newValue === "dark") root.dataset.theme = e.newValue;
    else delete root.dataset.theme;
    label();
  });
  label();
})();
// Admins page: a super admin manages every game, so the per-game boxes switch off when it's ticked.
document.querySelectorAll("[data-admin-form]").forEach(function (form) {
  var sup = form.querySelector("[data-super]"), boxes = form.querySelector(".sportboxes");
  if (!sup || !boxes) return;
  sup.addEventListener("change", function () { boxes.disabled = sup.checked; });
});

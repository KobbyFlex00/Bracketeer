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

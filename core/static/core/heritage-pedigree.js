/* Accessible pedigree interactions; canonical identities and COI stay server-side. */
(function () {
  "use strict";
  function init() {
    var scroll = document.getElementById("cca-pedigree-scroll");
    if (!scroll) return;
    var board = scroll.querySelector(".pedigree-board");
    if (!board) return;
    var columns = Array.prototype.slice.call(board.querySelectorAll(".pedigree-column"));
    var output = document.getElementById("cca-tree-zoom");
    var status = document.getElementById("cca-tree-status");
    var repeats = document.querySelector("[data-pedigree-repeats]");
    var scale = 1, pinned = false, selected = "";
    function announce(message) { if (status) status.textContent = message; }
    function highlight(id) {
      board.querySelectorAll(".pedigree-node[data-dog-id]").forEach(function (node) {
        node.classList.toggle("is-related-highlight",
          (pinned && node.classList.contains("repeated")) ||
          Boolean(id && node.dataset.dogId === id));
      });
    }
    function zoom() {
      board.style.zoom = String(scale);
      if (output) output.textContent = Math.round(scale * 100) + "%";
    }
    document.querySelectorAll("[data-pedigree-zoom]").forEach(function (button) {
      button.addEventListener("click", function () {
        scale = Math.max(.8, Math.min(1.5, Math.round((scale + Number(button.dataset.pedigreeZoom)) * 10) / 10));
        zoom();
        announce("Pedigree zoom set to " + Math.round(scale * 100) + " percent.");
      });
    });
    var reset = document.querySelector("[data-pedigree-fit]");
    if (reset) reset.addEventListener("click", function () {
      scale = 1; zoom(); scroll.scrollTo({ left: 0, top: 0, behavior: "auto" });
      announce("View reset to the first generation.");
    });
    document.querySelectorAll("[data-pedigree-step]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (!columns.length) return;
        var current = columns.reduce(function (best, column, i) {
          return Math.abs(column.offsetLeft - scroll.scrollLeft) <
            Math.abs(columns[best].offsetLeft - scroll.scrollLeft) ? i : best;
        }, 0);
        var next = Math.max(0, Math.min(columns.length - 1, current + Number(button.dataset.pedigreeStep)));
        scroll.scrollTo({ left: columns[next].offsetLeft, behavior: "smooth" });
        announce("Showing " + (columns[next].querySelector("h2")?.textContent.trim() || "generation " + (next + 1)) + ".");
      });
    });
    if (repeats) repeats.addEventListener("click", function () {
      pinned = !pinned; repeats.setAttribute("aria-pressed", String(pinned));
      highlight(selected);
      var ids = new Set(Array.prototype.map.call(board.querySelectorAll(".pedigree-node.repeated[data-dog-id]"),
        function (node) { return node.dataset.dogId; }));
      announce(pinned ? "Highlighting " + ids.size + " repeated canonical ancestor identities." : "Repeated ancestor highlighting cleared.");
    });
    board.querySelectorAll(".pedigree-node[data-dog-id]").forEach(function (node) {
      var id = node.dataset.dogId;
      node.addEventListener("pointerenter", function () { selected = id; highlight(id); });
      node.addEventListener("pointerleave", function () { selected = ""; highlight(""); });
      node.addEventListener("focus", function () {
        selected = id; highlight(id);
        var name = node.querySelector("strong");
        announce((name ? name.textContent.trim() : "Dog") + " selected; matching ancestry positions highlighted.");
      });
      node.addEventListener("blur", function () { selected = ""; highlight(""); });
    });
    zoom();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
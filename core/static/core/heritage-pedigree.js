/* Pedigree viewer: preserve full desktop tree, use readable generation-at-a-time navigation on phones. */
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
    var controls = document.querySelector(".cca-tree-tools");
    var mobile = window.matchMedia("(max-width: 760px)");
    var scale = 1, pinned = false, selected = "", index = 0;
    function announce(message) { if (status) status.textContent = message; }
    function highlight(id) {
      board.querySelectorAll(".pedigree-node[data-dog-id]").forEach(function (node) {
        node.classList.toggle("is-related-highlight",
          (pinned && node.classList.contains("repeated")) ||
          Boolean(id && node.dataset.dogId === id));
      });
    }
    var picker = document.createElement("select");
    picker.className = "cca-generation-picker";
    picker.setAttribute("aria-label", "Go to pedigree generation");
    columns.forEach(function (column, i) {
      var option = document.createElement("option");
      option.value = String(i);
      option.textContent = column.querySelector("h2")?.textContent.trim() || ("Generation " + i);
      picker.appendChild(option);
    });
    if (controls) {
      var label = document.createElement("label");
      label.className = "cca-generation-picker-label";
      label.textContent = "View generation ";
      label.appendChild(picker);
      controls.insertBefore(label, controls.firstChild);
    }
    function updateButtons() {
      document.querySelectorAll("[data-pedigree-step]").forEach(function (button) {
        button.disabled = mobile.matches && (index + Number(button.dataset.pedigreeStep) < 0 ||
          index + Number(button.dataset.pedigreeStep) >= columns.length);
      });
    }
    function goTo(next, focus) {
      index = Math.max(0, Math.min(columns.length - 1, next));
      picker.value = String(index);
      if (mobile.matches) {
        columns.forEach(function (column, i) {
          column.hidden = i !== index;
          column.classList.toggle("cca-generation-active", i === index);
        });
        scroll.scrollTop = 0;
      } else {
        columns.forEach(function (column) { column.hidden = false; column.classList.remove("cca-generation-active"); });
        if (focus) scroll.scrollTo({ left: columns[index].offsetLeft, behavior: "smooth" });
      }
      updateButtons();
      if (focus) announce("Showing " + picker.options[index].textContent + ".");
    }
    picker.addEventListener("change", function () { goTo(Number(picker.value), true); });
    // The viewer is keyboard navigable without intercepting links or forms.
    scroll.addEventListener("keydown", function (event) {
      if (!mobile.matches || event.target !== scroll) return;
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        goTo(index + (event.key === "ArrowRight" ? 1 : -1), true);
      }
    });

    document.querySelectorAll("[data-pedigree-step]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (!mobile.matches) {
          index = columns.reduce(function (best, column, i) {
            return Math.abs(column.offsetLeft - scroll.scrollLeft) <
              Math.abs(columns[best].offsetLeft - scroll.scrollLeft) ? i : best;
          }, 0);
        }
        goTo(index + Number(button.dataset.pedigreeStep), true);
      });
    });
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
      scale = 1; zoom(); goTo(0, false);
      scroll.scrollTo({ left: 0, top: 0, behavior: "auto" });
      announce("View reset to the subject dog.");
    });
    if (repeats) repeats.addEventListener("click", function () {
      pinned = !pinned;
      repeats.setAttribute("aria-pressed", String(pinned));
      highlight(selected);
      var ids = new Set(Array.prototype.map.call(board.querySelectorAll(".pedigree-node.repeated[data-dog-id]"),
        function (node) { return node.dataset.dogId; }));
      announce(pinned ? "Highlighting " + ids.size + " repeated ancestor identities." : "Repeated ancestor highlighting cleared.");
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
    var touchX = null, touchY = null;
    scroll.addEventListener("touchstart", function (event) {
      if (!mobile.matches || event.touches.length !== 1) return;
      touchX = event.touches[0].clientX;
      touchY = event.touches[0].clientY;
    }, { passive: true });
    scroll.addEventListener("touchend", function (event) {
      if (touchX === null || !mobile.matches || !event.changedTouches.length) return;
      var dx = event.changedTouches[0].clientX - touchX;
      var dy = event.changedTouches[0].clientY - touchY;
      touchX = null; touchY = null;
      if (Math.abs(dx) > 65 && Math.abs(dx) > Math.abs(dy) * 1.4) goTo(index + (dx < 0 ? 1 : -1), true);
    }, { passive: true });
    window.addEventListener("beforeprint", function () {
      columns.forEach(function (column) { column.hidden = false; });
      board.style.zoom = "1";
    });
    window.addEventListener("afterprint", function () { zoom(); goTo(index, false); });
    mobile.addEventListener("change", function () { goTo(index, false); });
    zoom(); goTo(0, false);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

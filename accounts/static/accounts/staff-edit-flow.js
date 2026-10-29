/* Small, no-dependency enhancement. The server remains the source of truth:
   this only reports unsaved form changes and opens deep-linked / invalid sections. */
(() => {
  "use strict";
  const form = document.querySelector("form[data-edit-form]");
  if (!form) return;
  const clean = document.querySelector("[data-edit-clean]");
  const dirty = document.querySelector("[data-edit-dirty]");
  const editor = document.querySelector("[data-edit-status]");

  function snapshot() {
    return JSON.stringify(Array.from(form.querySelectorAll("input, select, textarea"))
      .filter((field) => !["submit", "button"].includes(field.type))
      .map((field) => [
        field.name || field.id,
        field.type === "checkbox" || field.type === "radio" ? field.checked : field.value,
        field.type === "file" ? Array.from(field.files || []).map((file) => [file.name, file.size, file.lastModified]) : null,
      ]));
  }
  // Wait until the existing ancestor-search enhancement has replaced its
  // visible inputs so the baseline reflects exactly what staff first sees.
  const initial = snapshot();
  function refresh() {
    const changed = snapshot() !== initial;
    if (clean) clean.hidden = changed;
    if (dirty) dirty.hidden = !changed;
    if (editor) editor.dataset.hasUnsavedChanges = String(changed);
  }
  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  form.addEventListener("click", (event) => {
    if (event.target.closest("[data-formset-add]")) {
      // The formset insert handler updates the DOM on the same click event.
      queueMicrotask(refresh);
    }
  });

  function openAnchor() {
    const fragment = window.location.hash;
    if (!fragment) return;
    const target = document.getElementById(fragment.slice(1));
    if (!target) return;
    for (let node = target; node; node = node.parentElement) {
      if (node.tagName === "DETAILS") node.open = true;
    }
  }
  window.addEventListener("hashchange", openAnchor);
  openAnchor();
  const error = form.querySelector(".errorlist");
  if (error) {
    for (let node = error.parentElement; node; node = node.parentElement) {
      if (node.tagName === "DETAILS") node.open = true;
    }
  }
  refresh();
})();

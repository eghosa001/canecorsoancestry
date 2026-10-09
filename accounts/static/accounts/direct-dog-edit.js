// Build only the related-record rows that staff explicitly request.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-formset-add]");
  if (!button) return;
  const prefix = button.dataset.formsetAdd;
  const total = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
  const template = document.getElementById("formset-empty-" + prefix);
  const list = document.getElementById("formset-items-" + prefix);
  if (!total || !template || !list) return;
  const index = Number(total.value);
  const max = Number(document.getElementById("id_" + prefix + "-MAX_NUM_FORMS")?.value || "1000");
  if (!Number.isSafeInteger(index) || index >= max) return;
  list.insertAdjacentHTML("beforeend", template.innerHTML.replaceAll("__prefix__", String(index)));
  total.value = String(index + 1);
  list.lastElementChild?.querySelector("input:not([type=hidden]),select,textarea")?.focus();
});

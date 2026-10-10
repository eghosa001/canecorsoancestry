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


// Bounded private identity picker; never let an ambiguous dog name silently
// choose the wrong canonical ancestor. Only a clicked result sets its UUID.
document.querySelectorAll("[data-admin-parent-lookup]").forEach((input) => {
  const panel = document.querySelector('[data-parent-results-for="' + input.name + '"]');
  const endpoint = window.CCA_PARENT_LOOKUP_URL;
  if (!panel || !endpoint) return;
  let timeout, controller;
  const clear = () => { panel.replaceChildren(); panel.hidden = true; };
  clear();
  input.addEventListener("input", () => {
    window.clearTimeout(timeout);
    if (controller) controller.abort();
    const query = input.value.trim();
    clear();
    if (query.length < 2 || /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(query)) return;
    timeout = window.setTimeout(async () => {
      controller = new AbortController();
      try {
        const url = new URL(endpoint, window.location.origin);
        url.searchParams.set("q", query);
        url.searchParams.set("sex", input.dataset.parentSex);
        const response = await fetch(url.toString(), { signal: controller.signal, credentials: "same-origin" });
        if (!response.ok || input.value.trim() !== query) return;
        const data = await response.json();
        clear();
        if (!data.results?.length) {
          panel.textContent = "No matching ancestor. Check spelling or ask the Super Admin to add a verified record.";
          panel.hidden = false;
          return;
        }
        data.results.forEach((dog) => {
          const option = document.createElement("button");
          option.type = "button";
          option.className = "parent-identity-option";
          const main = document.createElement("strong");
          main.textContent = dog.name;
          const detail = document.createElement("small");
          detail.textContent = [dog.kennel || "Kennel unknown", dog.registration || "No registration", dog.dob || "DOB unknown", dog.is_public ? "Published" : "Not published", dog.id].join(" · ");
          option.append(main, detail);
          option.addEventListener("click", () => { input.value = dog.id; input.dataset.selectedName = dog.name; clear(); });
          panel.append(option);
        });
        panel.hidden = false;
      } catch (error) {
        if (error.name !== "AbortError") {
          clear();
          panel.textContent = "Search unavailable. Try again or enter the exact UUID.";
          panel.hidden = false;
        }
      }
    }, 180);
  });
  input.addEventListener("keydown", (event) => { if (event.key === "Escape") clear(); });
  document.addEventListener("pointerdown", (event) => {
    if (event.target !== input && !panel.contains(event.target)) clear();
  });
});

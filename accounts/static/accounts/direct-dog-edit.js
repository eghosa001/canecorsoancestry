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


// Progressive enhancement: staff see a readable ancestor name, but the original
// field posts only its explicit UUID. A typed name is NEVER silently interpreted
// as a different record when JavaScript is active.
document.querySelectorAll("[data-admin-parent-lookup]").forEach((referenceInput) => {
  const panel = document.querySelector('[data-parent-results-for="' + referenceInput.name + '"]');
  const status = document.querySelector('[data-parent-selection-for="' + referenceInput.name + '"]');
  const endpoint = window.CCA_PARENT_LOOKUP_URL;
  if (!panel || !status || !endpoint) return;

  const parentLabel = referenceInput.dataset.parentSex === "male" ? "sire" : "dam";
  const initialId = referenceInput.dataset.currentParentId || "";
  const initialName = referenceInput.dataset.currentParentName || "";
  const rawValue = referenceInput.value.trim();
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i;
  let selectedName = initialId && rawValue === initialId ? initialName : "";
  let timeout;
  let controller;

  // Retain the original named form control to preserve Django's validation,
  // no-JavaScript fallback and audit logic. Replace only its visible UI.
  const search = referenceInput.cloneNode(false);
  const originalId = referenceInput.id;
  search.type = "search";
  search.removeAttribute("name");
  search.removeAttribute("data-admin-parent-lookup");
  search.removeAttribute("data-current-parent-id");
  search.removeAttribute("data-current-parent-name");
  search.dataset.parentSearchVisible = "";
  search.value = selectedName || rawValue;
  search.setAttribute("role", "combobox");
  search.setAttribute("aria-autocomplete", "list");
  search.setAttribute("aria-haspopup", "listbox");
  search.setAttribute("aria-expanded", "false");
  search.setAttribute("aria-controls", panel.id);
  status.id = "parent-selection-" + referenceInput.name;
  search.setAttribute("aria-describedby", status.id);
  referenceInput.id = originalId + "-reference";
  referenceInput.type = "hidden";
  referenceInput.removeAttribute("data-admin-parent-lookup");
  referenceInput.before(search);

  const clear = () => {
    panel.replaceChildren();
    panel.hidden = true;
    search.setAttribute("aria-expanded", "false");
  };
  const describe = (error = "") => {
    status.dataset.selected = String(Boolean(referenceInput.value && selectedName));
    status.dataset.error = String(Boolean(error));
    if (error) {
      status.textContent = error;
    } else if (referenceInput.value && selectedName) {
      status.textContent = "Selected " + parentLabel + ": " + selectedName;
    } else if (referenceInput.value && uuidPattern.test(referenceInput.value)) {
      status.textContent = "Exact " + parentLabel + " ID entered; checked when you save.";
    } else if (search.value.trim()) {
      status.textContent = "Choose a matching " + parentLabel + " to confirm its identity.";
    } else {
      status.textContent = initialId
        ? "No " + parentLabel + " selected. Saving will unlink the recorded " + parentLabel + "."
        : "No " + parentLabel + " recorded.";
    }
  };

  clear();
  describe();

  search.addEventListener("input", () => {
    window.clearTimeout(timeout);
    if (controller) controller.abort();
    clear();
    const query = search.value.trim();
    selectedName = "";
    // Administrators may still paste an exact UUID if they know it.
    referenceInput.value = uuidPattern.test(query) ? query : "";
    describe();
    if (query.length < 2 || uuidPattern.test(query)) return;

    timeout = window.setTimeout(async () => {
      controller = new AbortController();
      try {
        const url = new URL(endpoint, window.location.origin);
        url.searchParams.set("q", query);
        url.searchParams.set("sex", referenceInput.dataset.parentSex);
        const response = await fetch(url.toString(), {
          signal: controller.signal, credentials: "same-origin"
        });
        if (!response.ok || search.value.trim() !== query) return;
        const data = await response.json();
        clear();
        if (!data.results?.length) {
          describe("No matching " + parentLabel + ". Check spelling or ask a Super Admin to add verified ancestry.");
          return;
        }
        data.results.forEach((dog) => {
          const option = document.createElement("button");
          option.type = "button";
          option.role = "option";
          option.className = "parent-identity-option";
          option.title = dog.id;
          const title = document.createElement("strong");
          title.textContent = dog.name;
          const details = document.createElement("small");
          details.textContent = [
            dog.kennel || "Kennel unknown",
            dog.registration || "No registration",
            dog.dob || "DOB unknown",
            dog.is_public ? "Published" : "Not published",
            "ID " + dog.id.slice(0, 8)
          ].join(" · ");
          option.append(title, details);
          option.addEventListener("click", () => {
            referenceInput.value = dog.id;
            selectedName = dog.name;
            search.value = dog.name;
            clear();
            describe();
            search.focus({ preventScroll: true });
          });
          panel.append(option);
        });
        panel.hidden = false;
        search.setAttribute("aria-expanded", "true");
      } catch (error) {
        if (error.name !== "AbortError") {
          clear();
          describe("Ancestor search is unavailable. Retry or paste the verified UUID.");
        }
      }
    }, 180);
  });

  search.addEventListener("keydown", (event) => {
    if (event.key === "Escape") clear();
    if (event.key === "ArrowDown" && !panel.hidden) {
      const first = panel.querySelector("button");
      if (first) { event.preventDefault(); first.focus(); }
    }
  });
  panel.addEventListener("keydown", (event) => {
    const options = [...panel.querySelectorAll("button")];
    const index = options.indexOf(document.activeElement);
    if (event.key === "Escape") {
      event.preventDefault();
      clear();
      search.focus({ preventScroll: true });
    } else if (index >= 0 && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      event.preventDefault();
      options[(index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length].focus();
    }
  });
  document.addEventListener("pointerdown", (event) => {
    if (event.target !== search && !panel.contains(event.target)) clear();
  });

  search.form?.addEventListener("submit", (event) => {
    if (event.defaultPrevented) return;
    if (search.value.trim() && !referenceInput.value.trim()) {
      event.preventDefault();
      clear();
      describe("Choose a result from the list before saving. A typed name alone is not a confirmed identity.");
      search.focus();
    } else if (!referenceInput.value && initialId &&
               !window.confirm("Unlink the existing " + parentLabel + " from this dog?")) {
      event.preventDefault();
      search.focus();
    }
  });
});

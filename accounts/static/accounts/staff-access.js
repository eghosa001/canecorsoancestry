// Require an explicit staff account selection, and confirm that precise
// identity before suspending or restoring login. Normal POST works without JS.
(function () {
  "use strict";
  const form = document.getElementById("staff-access-form");
  if (!form) return;

  form.addEventListener("submit", function (event) {
    const account = form.elements.namedItem("user_id");
    const action = form.elements.namedItem("action");
    if (!account || !action || !account.value || !action.value) {
      event.preventDefault();
      return;
    }
    const selected = account.options[account.selectedIndex];
    const label = (selected && selected.textContent || "").trim();
    const verb = action.value === "deactivate" ? "DEACTIVATE" : "REACTIVATE";
    if (!window.confirm(verb + " this one account?\n\n" + label + "\n\nNo other staff accounts will be changed.")) {
      event.preventDefault();
    }
  });
})();

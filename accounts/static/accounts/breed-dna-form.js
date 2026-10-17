(function () {
  "use strict";
  const type = document.getElementById("id_evidence_type");
  if (!type) return;
  const breedFields = ["dna_provider", "cane_corso_percentage", "other_breeds",
    "acknowledge_public_summary", "allow_full_report_publication"];
  const normalFields = ["test_type", "result"];
  function update() {
    const breed = type.value === "breed";
    for (const name of breedFields.concat(normalFields)) {
      const field = document.getElementById("id_" + name);
      const wrapper = field && field.closest(".form-field");
      if (wrapper) wrapper.hidden = breedFields.includes(name) !== breed;
    }
  }
  type.addEventListener("change", update);
  update();
})();

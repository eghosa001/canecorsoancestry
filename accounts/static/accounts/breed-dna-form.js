(function () {
  "use strict";
  const type = document.getElementById("id_evidence_type");
  if (!type) return;
  const marker = document.getElementById("id_genetic_marker");
  const breedFields = ["dna_provider", "cane_corso_percentage", "other_breeds",
    "acknowledge_public_summary"];
  const markers = ["genetic_marker", "genetic_status"];
  const other = ["test_type", "result"];
  function update() {
    const breed = type.value === "breed";
    const dna = type.value === "dna";
    const featured = dna && marker && !!marker.value;
    for (const name of breedFields.concat(markers, other)) {
      const field = document.getElementById("id_" + name);
      const wrapper = field && field.closest(".form-field");
      if (!wrapper) continue;
      if (breedFields.includes(name)) wrapper.hidden = !breed;
      else if (name === "genetic_marker") wrapper.hidden = !dna;
      else if (name === "genetic_status") wrapper.hidden = !featured;
      else wrapper.hidden = breed || featured;
    }
  }
  type.addEventListener("change", update);
  if (marker) marker.addEventListener("change", update);
  update();
})();

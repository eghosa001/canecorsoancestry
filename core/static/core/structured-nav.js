/* Workspace disclosure: desktop expanded; compact native <details> on phones.
   Every link is server-rendered and available without JavaScript. */
(function () {
  "use strict";
  function init() {
    var nav = document.querySelector("[data-responsive-nav]");
    if (!nav) return;
    var mq = window.matchMedia("(max-width: 760px)");
    var lastMode = null;
    function adapt() {
      if (lastMode === mq.matches) return;
      lastMode = mq.matches;
      nav.open = !mq.matches;
    }
    adapt();
    if (mq.addEventListener) mq.addEventListener("change", adapt);
    else if (mq.addListener) mq.addListener(adapt);

    // A dropdown cannot remain positioned over unrelated controls after
    // a user clicks elsewhere or switches page sections.
    document.addEventListener("pointerdown", function (event) {
      if (!event.target.closest(".workspace-more")) {
        document.querySelectorAll(".workspace-more[open]").forEach(function (menu) {
          menu.open = false;
        });
      }
      if (!event.target.closest(".cca-secondary-actions")) {
        document.querySelectorAll(".cca-secondary-actions[open]").forEach(function (menu) {
          menu.open = false;
        });
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      var menus = document.querySelectorAll(".workspace-more[open], .cca-secondary-actions[open]");
      menus.forEach(function (menu) {
        menu.open = false;
        var summary = menu.querySelector("summary");
        if (menu.contains(document.activeElement) && summary) summary.focus();
      });
      if (mq.matches && nav.open) {
        nav.open = false;
        var toggle = nav.querySelector(":scope > summary");
        if (toggle) toggle.focus();
      }
    });
    nav.querySelectorAll("a").forEach(function (anchor) {
      anchor.addEventListener("click", function () {
        if (mq.matches) nav.open = false;
      });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
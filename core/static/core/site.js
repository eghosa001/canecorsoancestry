(function () {
      var root = document.documentElement;
      var meta = document.querySelector('meta[name="theme-color"]');
      var buttons = document.querySelectorAll("[data-theme-toggle]");

      function refreshThemeControls() {
        var isLight = root.dataset.theme === "light";
        if (meta) meta.setAttribute("content", isLight ? "#f4f0e8" : "#090a09");
        buttons.forEach(function (button) {
          button.textContent = button.classList.contains("mobile-header-theme") ? (isLight ? "Dark" : "Light") : (isLight ? "Dark mode" : "Light mode");
          button.setAttribute("aria-label", isLight ? "Switch to dark mode" : "Switch to light mode");
        });
      }

      buttons.forEach(function (button) {
        button.addEventListener("click", function () {
          var next = root.dataset.theme === "light" ? "dark" : "light";
          root.dataset.theme = next;
          try { localStorage.setItem("cca-theme", next); } catch (error) {}
          refreshThemeControls();
        });
      });
      refreshThemeControls();
    })();

    (function () {
      var openSuggestions = [];
      var pickerInteracting = false;
      var lastPanelScrollAt = 0;
      var lastSearchFocusAt = 0;

      function closeMobileMenus() {
        document.querySelectorAll(".mobile-nav[open], .dashboard-mobile-nav[open]").forEach(function (menu) {
          menu.removeAttribute("open");
        });
      }

      function dismissSearchUI() {
        openSuggestions.forEach(function (entry) {
          entry.close();
        });
        var active = document.activeElement;
        if (active && active.matches && active.matches("[data-dog-autocomplete]")) {
          active.blur();
        }
      }

      window.addEventListener("scroll", function () {
        // Keep the picker stable only while its own suggestion panel is being
        // manipulated. A real page scroll should dismiss autocomplete and blur
        // the field so mobile keyboards do not remain pinned over the page.
        // iOS Safari scrolls the page automatically while raising its keyboard.
        // Do not interpret that focus-induced movement as a dismiss gesture.
        var keyboardFocusing = Date.now() - lastSearchFocusAt < 450 &&
          document.activeElement &&
          document.activeElement.matches &&
          document.activeElement.matches("[data-dog-autocomplete]");
        if (pickerInteracting || keyboardFocusing || Date.now() - lastPanelScrollAt < 180) {
          return;
        }
        closeMobileMenus();
        dismissSearchUI();
      }, { passive: true });

      document.addEventListener("pointerdown", function (event) {
        if (!event.target.closest(".dog-autocomplete-host")) {
          dismissSearchUI();
        }
        // Native <details> menus do not dismiss when a Safari user taps
        // outside. Keep the menu state synchronized with touch navigation.
        if (!event.target.closest(".mobile-nav, .dashboard-mobile-nav")) {
          closeMobileMenus();
        }
      });

      document.querySelectorAll(".mobile-nav a, .dashboard-mobile-nav a").forEach(function (link) {
        link.addEventListener("click", closeMobileMenus);
      });

      document.querySelectorAll("[data-dog-autocomplete]").forEach(function (input, inputIndex) {
        var host = input.closest(".mating-select, .filter-search, .hero-search, .header-search, .mobile-nav-search, .form-field") || input.parentElement;
        host.classList.add("dog-autocomplete-host");

        var panel = document.createElement("div");
        panel.className = "dog-suggestions";
        panel.id = "dog-suggestions-" + (inputIndex + 1);
        panel.setAttribute("role", "listbox");
        panel.hidden = true;
        host.appendChild(panel);

        input.setAttribute("role", "combobox");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-expanded", "false");
        input.setAttribute("aria-controls", panel.id);

        var panelInteracting = false;
        var panelTouchY = null;
        var activeIndex = -1;

        function setPanelInteracting(value) {
          panelInteracting = value;
          pickerInteracting = value;
        }

        panel.addEventListener("pointerdown", function (event) {
          setPanelInteracting(true);
          event.stopPropagation();
        });
        panel.addEventListener("pointerup", function (event) {
          event.stopPropagation();
          window.setTimeout(function () { setPanelInteracting(false); }, 0);
        });
        panel.addEventListener("pointercancel", function () {
          setPanelInteracting(false);
        });

        panel.addEventListener("touchstart", function (event) {
          setPanelInteracting(true);
          if (event.touches.length === 1) panelTouchY = event.touches[0].clientY;
          event.stopPropagation();
        }, { passive: true });

        panel.addEventListener("touchmove", function (event) {
          if (!event.touches.length || panelTouchY === null) return;
          var nextY = event.touches[0].clientY;
          var deltaY = nextY - panelTouchY;
          var atTop = panel.scrollTop <= 0;
          var atBottom = panel.scrollTop + panel.clientHeight >= panel.scrollHeight - 1;

          // Prevent Safari from chaining an edge swipe into the page while still
          // allowing the suggestion list itself to scroll naturally.
          if ((atTop && deltaY > 0) || (atBottom && deltaY < 0)) {
            event.preventDefault();
          }
          panelTouchY = nextY;
          event.stopPropagation();
        }, { passive: false });

        panel.addEventListener("touchend", function (event) {
          panelTouchY = null;
          event.stopPropagation();
          window.setTimeout(function () { setPanelInteracting(false); }, 0);
        }, { passive: true });

        panel.addEventListener("scroll", function () {
          lastPanelScrollAt = Date.now();
        }, { passive: true });

        if ((input.dataset.dogAutocompleteMode || "navigate") === "fill") {
          input.addEventListener("input", function () {
            var targetId = input.dataset.dogAutocompleteTarget;
            if (targetId) {
              var target = document.getElementById(targetId);
              if (target) target.value = "";
            }
          });
        }

        var timer = null;
        var requestSerial = 0;
        var inFlightController = null;

        function suggestionUrl(value, browse) {
          var url = "/dogs/suggestions/?q=" + encodeURIComponent(value || "");
          if (browse) url += "&browse=1";
          if (input.dataset.dogSex) {
            url += "&sex=" + encodeURIComponent(input.dataset.dogSex);
          }
          return url;
        }

        function requestSuggestions(value, browse) {
          clearTimeout(timer);
          // Cancel a superseded request so fast typing does not keep stale
          // database lookups running after the results are no longer useful.
          if (inFlightController) {
            inFlightController.abort();
            inFlightController = null;
          }
          // Invalidate any in-flight response immediately, even while the
          // latest keystroke is still in its debounce window.
          var serial = ++requestSerial;
          var expected = (value || "").trim();
          if (!browse && expected.length < 2) {
            close();
            return;
          }

          panel.setAttribute("aria-busy", "true");
          timer = setTimeout(function () {
            var controller = new AbortController();
            inFlightController = controller;
            fetch(suggestionUrl(expected, browse), {
              headers: { "Accept": "application/json" },
              credentials: "same-origin",
              signal: controller.signal
            })
              .then(function (response) { return response.ok ? response.json() : { results: [] }; })
              .then(function (data) {
                if (serial !== requestSerial) return;
                if (!browse && input.value.trim() !== expected) return;
                render(data.results || []);
              })
              .catch(function (error) {
                // Abort is expected when the user types again or closes the list.
                if (error && error.name === "AbortError") return;
                if (serial === requestSerial) close();
              })
              .finally(function () {
                if (inFlightController === controller) inFlightController = null;
                if (serial === requestSerial) panel.setAttribute("aria-busy", "false");
              });
          }, browse ? 0 : 100);
        }

        function close() {
          clearTimeout(timer);
          if (inFlightController) {
            inFlightController.abort();
            inFlightController = null;
          }
          requestSerial += 1;
          activeIndex = -1;
          input.removeAttribute("aria-activedescendant");
          input.setAttribute("aria-expanded", "false");
          panel.setAttribute("aria-busy", "false");
          panel.hidden = true;
          panel.replaceChildren();
        }

        openSuggestions.push({ panel: panel, input: input, close: close });

        function items() {
          return Array.prototype.slice.call(panel.querySelectorAll(".dog-suggestion"));
        }

        function setActive(nextIndex) {
          var options = items();
          if (!options.length) {
            activeIndex = -1;
            input.removeAttribute("aria-activedescendant");
            return;
          }
          activeIndex = (nextIndex + options.length) % options.length;
          options.forEach(function (option, index) {
            var selected = index === activeIndex;
            option.setAttribute("aria-selected", selected ? "true" : "false");
          });
          var activeOption = options[activeIndex];
          input.setAttribute("aria-activedescendant", activeOption.id);
          activeOption.scrollIntoView({ block: "nearest" });
        }

        function render(results) {
          panel.replaceChildren();
          activeIndex = -1;
          input.removeAttribute("aria-activedescendant");

          if (!results.length) {
            close();
            return;
          }

          results.forEach(function (dog, index) {
            var mode = input.dataset.dogAutocompleteMode || "navigate";
            var item = document.createElement(mode === "fill" ? "button" : "a");
            item.className = "dog-suggestion";
            item.id = panel.id + "-option-" + (index + 1);
            item.setAttribute("role", "option");
            item.setAttribute("aria-selected", "false");

            if (mode === "fill") {
              item.type = "button";
              item.addEventListener("click", function (event) {
                event.preventDefault();
                event.stopPropagation();
                input.value = dog.name;
                var targetId = input.dataset.dogAutocompleteTarget;
                if (targetId) {
                  var target = document.getElementById(targetId);
                  if (target) target.value = dog.id || "";
                }
                close();
                input.focus({ preventScroll: true });
              });
            } else {
              item.href = "/dogs/" + encodeURIComponent(dog.slug) + "/?source=search";
              item.addEventListener("click", function (event) {
                event.preventDefault();
                event.stopPropagation();
                var target = item.href;
                close();
                input.blur();
                window.location.assign(target);
              });
            }

            var title = document.createElement("strong");
            title.textContent = dog.name;
            var meta = document.createElement("span");
            meta.textContent = [dog.registration, dog.kennel, dog.sex].filter(Boolean).join(" · ");
            item.append(title, meta);
            panel.appendChild(item);
          });

          panel.hidden = false;
          input.setAttribute("aria-expanded", "true");
        }

        function refreshFromInput() {
          requestSuggestions(input.value.trim(), false);
        }

        input.addEventListener("input", refreshFromInput);
        input.addEventListener("search", refreshFromInput);
        input.addEventListener("compositionend", refreshFromInput);

        input.addEventListener("focus", function () {
          lastSearchFocusAt = Date.now();
          if ((input.dataset.dogAutocompleteMode || "navigate") !== "fill") return;
          if (!input.value.trim()) {
            requestSuggestions("", true);
          } else {
            requestSuggestions(input.value.trim(), false);
          }
        });

        input.addEventListener("keydown", function (event) {
          if (event.key === "ArrowDown") {
            if (panel.hidden) {
              requestSuggestions(input.value.trim(), (input.dataset.dogAutocompleteMode || "navigate") === "fill" && !input.value.trim());
              return;
            }
            event.preventDefault();
            setActive(activeIndex + 1);
            return;
          }

          if (event.key === "ArrowUp") {
            if (panel.hidden) return;
            event.preventDefault();
            setActive(activeIndex <= 0 ? items().length - 1 : activeIndex - 1);
            return;
          }

          if (event.key === "Enter" && !panel.hidden && activeIndex >= 0) {
            var activeOption = items()[activeIndex];
            if (activeOption) {
              event.preventDefault();
              activeOption.click();
            }
            return;
          }

          if (event.key === "Escape") {
            close();
            input.blur();
          }
        });

        input.addEventListener("blur", function () {
          window.setTimeout(function () {
            if (!panelInteracting && !host.contains(document.activeElement)) {
              close();
            }
          }, 180);
        });
      });
    })();

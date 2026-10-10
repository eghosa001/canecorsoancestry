/* Cane Corso Ancestry dog portraits. Native, accessible and dependency-free.
 * Fit mode: tap or swipe down closes, swipe up closes + reveals dog details,
 * horizontal swipe changes photos. Zoom mode: pinch/double-tap or Zoom button,
 * drag anywhere to inspect EVERY edge, tap to reset and pinch inward to fit.
 * The background page remains locked until dialog dismissal. */
(() => {
  "use strict";
  const gallery = document.querySelector("[data-dog-gallery]");
  const dialog = document.querySelector("[data-dog-photo-dialog]");
  if (!gallery || !dialog) return;
  const openLink = gallery.querySelector("[data-dog-photo-open]");
  const hero = gallery.querySelector("[data-dog-photo-main]");
  const caption = gallery.querySelector("[data-dog-photo-caption]");
  const counter = gallery.querySelector("[data-dog-photo-count]");
  const thumbs = [...gallery.querySelectorAll("[data-dog-photo-thumb]")];
  const stage = dialog.querySelector("[data-dog-photo-stage]");
  const viewport = dialog.querySelector("[data-dog-photo-viewport]");
  const image = dialog.querySelector("[data-dog-lightbox-image]");
  const modalCount = dialog.querySelector("[data-dog-lightbox-count]");
  const modalCaption = dialog.querySelector("[data-dog-lightbox-caption-text]");
  const prev = dialog.querySelector("[data-dog-photo-prev]");
  const next = dialog.querySelector("[data-dog-photo-next]");
  const close = dialog.querySelector("[data-dog-photo-close]");
  const zoomButton = dialog.querySelector("[data-dog-photo-zoom]");
  if (![openLink, hero, stage, viewport, image, prev, next, close, zoomButton].every(Boolean)) return;

  const photos = thumbs.length ? thumbs.map((button) => ({
    src: button.dataset.photoSrc,
    alt: button.dataset.photoAlt || hero.alt,
    caption: button.dataset.photoCaption || "Photo",
    referrerPolicy: hero.referrerPolicy || "",
  })) : [{
    src: openLink.href, alt: hero.alt,
    caption: caption?.textContent?.trim() || "Photo",
    referrerPolicy: hero.referrerPolicy || "",
  }];
  let selected = 0;
  let scale = 1;
  let panX = 0;
  let panY = 0;
  let savedPage = null;
  let gesture = null;
  let pinch = null;
  let legacyTouchStart = null;
  let suppressedClickUntil = 0;
  let tapTimer = null;
  let lastTap = null;
  const active = new Map();
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const isZoomed = () => scale > 1.01;

  const lockPage = () => {
    if (savedPage) return;
    const body = document.body, root = document.documentElement;
    savedPage = {
      y: window.scrollY,
      position: body.style.position,
      top: body.style.top, left: body.style.left,
      right: body.style.right, width: body.style.width,
      overscroll: root.style.overscrollBehavior,
    };
    body.style.position = "fixed";
    body.style.top = "-" + savedPage.y + "px";
    body.style.left = "0";
    body.style.right = "0";
    body.style.width = "100%";
    root.style.overscrollBehavior = "none";
  };
  const unlockPage = () => {
    if (!savedPage) return;
    const state = savedPage;
    savedPage = null;
    const body = document.body, root = document.documentElement;
    body.style.position = state.position;
    body.style.top = state.top;
    body.style.left = state.left;
    body.style.right = state.right;
    body.style.width = state.width;
    root.style.overscrollBehavior = state.overscroll;
    window.scrollTo({ top: state.y, behavior: "instant" });
  };

  // Bounds are based on the image's actual fitted dimensions, not the source
  // pixel count. A user can drag to all four extremities with no clipping.
  const clampPan = () => {
    const maxX = Math.max(0, (image.offsetWidth * scale - viewport.clientWidth) / 2);
    const maxY = Math.max(0, (image.offsetHeight * scale - viewport.clientHeight) / 2);
    panX = clamp(panX, -maxX, maxX);
    panY = clamp(panY, -maxY, maxY);
  };
  const paint = () => {
    clampPan();
    // Do not keep an identity GPU transform on an unzoomed Safari photo.
    image.style.transform = isZoomed() ? `translate3d(${panX}px, ${panY}px, 0) scale(${scale})` : "none";
    stage.classList.toggle("is-zoomed", isZoomed());
    zoomButton.setAttribute("aria-pressed", String(isZoomed()));
    zoomButton.textContent = isZoomed() ? "Fit photo" : "Zoom in";
    viewport.dataset.zoomed = String(isZoomed());
  };
  const fit = () => {
    scale = 1;
    panX = 0;
    panY = 0;
    paint();
  };
  const setZoom = (value, pointX, pointY) => {
    const before = scale;
    scale = clamp(value, 1, 6);
    if (scale <= 1.01) {
      fit();
      return;
    }
    const bounds = viewport.getBoundingClientRect();
    const x = Number.isFinite(pointX) ? pointX - bounds.left - bounds.width / 2 : 0;
    const y = Number.isFinite(pointY) ? pointY - bounds.top - bounds.height / 2 : 0;
    const factor = scale / before;
    panX = x - (x - panX) * factor;
    panY = y - (y - panY) * factor;
    paint();
  };
  const clearTap = () => {
    if (tapTimer) window.clearTimeout(tapTimer);
    tapTimer = null;
    lastTap = null;
  };
  const clearGestures = () => {
    active.clear();
    gesture = null;
    pinch = null;
    legacyTouchStart = null;
    clearTap();
  };
  const dismiss = (direction = "stay") => {
    if (!dialog.open) return;
    clearGestures();
    dialog.close();
    // Keep the default native close control/ESC as a safe fallback.
    unlockPage();
    if (direction === "details") {
      const details = document.querySelector("#profile-details");
      if (details) window.requestAnimationFrame(() => {
        const headerHeight = document.querySelector(".site-header")?.getBoundingClientRect().height || 0;
        const top = details.getBoundingClientRect().top + window.scrollY - headerHeight - 12;
        window.scrollTo({
          top: Math.max(0, top),
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
        });
      });
    }
  };
  const select = (index) => {
    selected = (index + photos.length) % photos.length;
    const item = photos[selected];
    openLink.href = item.src;
    if (hero.getAttribute("src") !== item.src) {
      hero.src = item.src;
      hero.alt = item.alt;
    }
    if (caption) caption.textContent = item.caption;
    if (counter) counter.textContent = `${selected + 1} of ${photos.length}`;
    thumbs.forEach((button, i) => {
      button.classList.toggle("is-active", i === selected);
      button.setAttribute("aria-pressed", String(i === selected));
    });
    if (dialog.open) {
      clearGestures();
      fit();
      image.referrerPolicy = item.referrerPolicy;
      if (image.getAttribute("src") !== item.src) image.src = item.src;
      image.alt = item.alt;
      if (modalCount) modalCount.textContent = `${selected + 1} / ${photos.length}`;
      if (modalCaption) modalCaption.textContent = item.caption;
    }
  };

  thumbs.forEach((button, index) => button.addEventListener("click", () => select(index)));
  const single = photos.length < 2;
  prev.hidden = single;
  next.hidden = single;
  stage.classList.toggle("is-single", single);
  openLink.addEventListener("click", (event) => {
    if (typeof dialog.showModal !== "function") return; // real image fallback
    event.preventDefault();
    dialog.showModal();
    lockPage();
    select(selected);
    close.focus({ preventScroll: true });
  });
  close.addEventListener("click", () => dismiss());
  prev.addEventListener("click", () => select(selected - 1));
  next.addEventListener("click", () => select(selected + 1));
  zoomButton.addEventListener("click", () => {
    clearTap();
    if (isZoomed()) fit(); else setZoom(2.5);
  });
  dialog.addEventListener("keydown", (event) => {
    if (!single && event.key === "ArrowLeft") { event.preventDefault(); select(selected - 1); }
    if (!single && event.key === "ArrowRight") { event.preventDefault(); select(selected + 1); }
    if (event.key === "Escape") dismiss();
  });
  dialog.addEventListener("close", () => {
    clearGestures();
    fit();
    unlockPage();
    // Keep src intact; removing it created a broken image in live production.
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog || event.target === stage) dismiss();
  });

  const midpoint = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
  const separation = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const startPinch = () => {
    const values = [...active.values()];
    if (values.length < 2) return;
    const mid = midpoint(values[0], values[1]);
    pinch = { distance: Math.max(5, separation(values[0], values[1])),
              mid, scale, panX, panY };
    gesture = null;
    clearTap();
  };
  const enqueueTap = (x, y) => {
    const when = performance.now();
    if (lastTap && when - lastTap.when <= 350 &&
        Math.hypot(x - lastTap.x, y - lastTap.y) < 38) {
      clearTap();
      if (isZoomed()) fit(); else setZoom(2.5, x, y);
      return;
    }
    lastTap = { x, y, when };
    tapTimer = window.setTimeout(() => {
      tapTimer = null;
      lastTap = null;
      if (dialog.open) {
        if (isZoomed()) fit(); // touching the image returns it to normal size
        else dismiss();       // touching the fitted image closes the viewer
      }
    }, 270);
  };

  viewport.addEventListener("pointerdown", (event) => {
    if (!dialog.open || (event.pointerType === "mouse" && event.button !== 0)) return;
    active.set(event.pointerId, { x: event.clientX, y: event.clientY });
    try { viewport.setPointerCapture(event.pointerId); } catch (_error) { /* Safari fallback */ }
    if (active.size >= 2) { startPinch(); return; }
    gesture = { id: event.pointerId, x: event.clientX, y: event.clientY,
                panX, panY, moved: false };
  });
  viewport.addEventListener("pointermove", (event) => {
    if (!active.has(event.pointerId) || !dialog.open) return;
    active.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (active.size >= 2) {
      if (!pinch) startPinch();
      const values = [...active.values()];
      const mid = midpoint(values[0], values[1]);
      const nextScale = clamp(pinch.scale * separation(values[0], values[1]) / pinch.distance, 1, 6);
      const bounds = viewport.getBoundingClientRect();
      const centerX = bounds.left + bounds.width / 2, centerY = bounds.top + bounds.height / 2;
      const factor = nextScale / pinch.scale;
      scale = nextScale;
      panX = mid.x - centerX - (pinch.mid.x - centerX - pinch.panX) * factor;
      panY = mid.y - centerY - (pinch.mid.y - centerY - pinch.panY) * factor;
      if (!isZoomed()) { panX = 0; panY = 0; }
      paint();
      suppressedClickUntil = performance.now() + 500;
      return;
    }
    if (!gesture || gesture.id !== event.pointerId) return;
    const dx = event.clientX - gesture.x, dy = event.clientY - gesture.y;
    if (Math.hypot(dx, dy) > 9) {
      gesture.moved = true;
      clearTap();
    }
    if (isZoomed()) {
      panX = gesture.panX + dx;
      panY = gesture.panY + dy;
      paint();
    } else if (Math.abs(dy) >= 55 && Math.abs(dy) > Math.abs(dx) * 1.25) {
      // Downward swipe returns to the normal small portrait; upward swipe
      // continues into details. Neither action scrolls the background while
      // the modal is visible.
      suppressedClickUntil = performance.now() + 450;
      dismiss(dy < 0 ? "details" : "stay");
    }
  });
  const release = (event) => {
    if (!active.has(event.pointerId)) return;
    const position = active.get(event.pointerId);
    active.delete(event.pointerId);
    if (active.size) {
      if (pinch) {
        pinch = null;
        if (!isZoomed()) fit();
        const current = [...active.entries()][0];
        gesture = { id: current[0], x: current[1].x, y: current[1].y,
                    panX, panY, moved: true };
      }
      return;
    }
    if (pinch) { pinch = null; gesture = null; if (!isZoomed()) fit(); return; }
    if (!gesture || !dialog.open) return;
    const dx = position.x - gesture.x, dy = position.y - gesture.y;
    const moved = gesture.moved;
    gesture = null;
    if (moved) {
      suppressedClickUntil = performance.now() + 300;
      if (!isZoomed() && !single && Math.abs(dx) >= 55 && Math.abs(dx) > Math.abs(dy) * 1.25) {
        select(selected + (dx < 0 ? 1 : -1));
      }
    } else if (event.type === "pointerup") {
      enqueueTap(position.x, position.y);
    }
  };
  viewport.addEventListener("pointerup", release);
  viewport.addEventListener("pointercancel", release);
  viewport.addEventListener("click", (event) => {
    // Pointer up has already handled tap/double tap. Suppress synthesized
    // click after a drag so the modal does not close accidentally.
    if (event.detail && performance.now() < suppressedClickUntil) event.preventDefault();
  });
  image.addEventListener("dragstart", (event) => event.preventDefault());
  // iPhone browser bars can emit resize events while scrolling. Only
  // recalculate pan while zoomed; fitted photos must remain motionless.
  window.addEventListener("resize", () => { if (dialog.open && isZoomed()) paint(); }, { passive: true });

  // Also support legacy iOS touch events and the previous WebKit regression
  // contract, which dispatches touchstart/touchmove on the stage directly.
  stage.addEventListener("touchstart", (event) => {
    if (!dialog.open || event.touches.length !== 1 || event.target !== stage) return;
    legacyTouchStart = { x: event.touches[0].clientX, y: event.touches[0].clientY };
  }, { passive: true });
  stage.addEventListener("touchmove", (event) => {
    if (!legacyTouchStart || !dialog.open || event.touches.length !== 1) return;
    const dx = event.touches[0].clientX - legacyTouchStart.x;
    const dy = event.touches[0].clientY - legacyTouchStart.y;
    if (Math.abs(dy) > 30 && Math.abs(dy) > Math.abs(dx) * 1.3) {
      if (event.cancelable) event.preventDefault();
      legacyTouchStart = null;
      dismiss(dy < 0 ? "details" : "stay");
    }
  }, { passive: false });
  stage.addEventListener("touchend", () => { legacyTouchStart = null; }, { passive: true });
  stage.addEventListener("touchcancel", () => { legacyTouchStart = null; }, { passive: true });
})();

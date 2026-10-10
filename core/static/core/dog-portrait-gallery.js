/* Public dog profile only. No framework, no network calls, no database edits. */
(() => {
  "use strict";

  const gallery = document.querySelector("[data-dog-gallery]");
  const dialog = document.querySelector("[data-dog-photo-dialog]");
  if (!gallery || !dialog) return;

  const openLink = gallery.querySelector("[data-dog-photo-open]");
  const heroImage = gallery.querySelector("[data-dog-photo-main]");
  const caption = gallery.querySelector("[data-dog-photo-caption]");
  const counter = gallery.querySelector("[data-dog-photo-count]");
  const thumbs = Array.from(gallery.querySelectorAll("[data-dog-photo-thumb]"));
  const stage = dialog.querySelector("[data-dog-photo-stage]");
  const enlarged = dialog.querySelector("[data-dog-lightbox-image]");
  const lightboxCount = dialog.querySelector("[data-dog-lightbox-count]");
  const lightboxCaption = dialog.querySelector("[data-dog-lightbox-caption]");
  const prev = dialog.querySelector("[data-dog-photo-prev]");
  const next = dialog.querySelector("[data-dog-photo-next]");
  const close = dialog.querySelector("[data-dog-photo-close]");
  const zoom = dialog.querySelector("[data-dog-photo-zoom]");
  if (!openLink || !heroImage || !stage || !enlarged || !prev || !next || !close || !zoom) return;

  const photos = thumbs.length
    ? thumbs.map((thumb) => ({
      src: thumb.dataset.photoSrc,
      alt: thumb.dataset.photoAlt || heroImage.alt,
      caption: thumb.dataset.photoCaption || "Photo",
      referrerPolicy: "no-referrer",
    }))
    : [{
      src: openLink.href,
      alt: heroImage.alt,
      caption: caption ? caption.textContent.trim() : "Photo",
      referrerPolicy: heroImage.referrerPolicy || "",
    }];
  if (!photos.length) return;

  let selected = 0;
  let touchOrigin = null;
  let savedScrollY = null;
  let previousScrollStyles = null;
  const documentRoot = document.documentElement;
  const body = document.body;

  const lockBackground = () => {
    if (savedScrollY !== null) return;
    savedScrollY = window.scrollY;
    previousScrollStyles = {
      bodyPosition: body.style.position,
      bodyTop: body.style.top,
      bodyLeft: body.style.left,
      bodyRight: body.style.right,
      bodyWidth: body.style.width,
      rootOverscroll: documentRoot.style.overscrollBehavior,
    };
    body.style.position = "fixed";
    body.style.top = "-" + savedScrollY + "px";
    body.style.left = "0";
    body.style.right = "0";
    body.style.width = "100%";
    documentRoot.style.overscrollBehavior = "none";
  };

  const unlockBackground = () => {
    if (savedScrollY === null) return;
    const current = savedScrollY;
    body.style.position = previousScrollStyles.bodyPosition;
    body.style.top = previousScrollStyles.bodyTop;
    body.style.left = previousScrollStyles.bodyLeft;
    body.style.right = previousScrollStyles.bodyRight;
    body.style.width = previousScrollStyles.bodyWidth;
    documentRoot.style.overscrollBehavior = previousScrollStyles.rootOverscroll;
    savedScrollY = null;
    previousScrollStyles = null;
    window.scrollTo({ top: current, behavior: "instant" });
  };

  const closeAndScrollProfile = (fingerTravel) => {
    // Upward swipe means move down the profile. A downward swipe returns
    // toward the portrait. Restore the locked page before scrolling either.
    dialog.close();
    unlockBackground();
    const details = document.querySelector("#profile-details");
    const header = document.querySelector(".site-header");
    const fixedOffset = header ? header.getBoundingClientRect().height + 12 : 20;
    const top = fingerTravel < 0 && details
      ? details.getBoundingClientRect().top + window.scrollY - fixedOffset
      : Math.max(0, window.scrollY - Math.max(180, window.innerHeight * .55));
    window.requestAnimationFrame(() => window.scrollTo({
      top: Math.max(0, top),
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
    }));
  };
  const single = photos.length === 1;
  prev.hidden = single;
  next.hidden = single;
  stage.classList.toggle("is-single", single);

  const resetZoom = () => {
    stage.classList.remove("is-zoomed");
    zoom.setAttribute("aria-pressed", "false");
    zoom.textContent = "Zoom in";
    stage.scrollTop = 0;
    stage.scrollLeft = 0;
  };

  const select = (index, fromThumb = false) => {
    selected = (index + photos.length) % photos.length;
    const item = photos[selected];
    if (!item) return;

    openLink.href = item.src;
    if (fromThumb || heroImage.getAttribute("src") !== item.src) {
      heroImage.src = item.src;
      heroImage.alt = item.alt;
    }
    if (caption) caption.textContent = item.caption;
    if (counter) counter.textContent = (selected + 1) + " of " + photos.length;
    thumbs.forEach((thumb, indexInList) => {
      const active = indexInList === selected;
      thumb.classList.toggle("is-active", active);
      thumb.setAttribute("aria-pressed", String(active));
    });

    // Update the open lightbox only, avoiding duplicate large-image downloads.
    if (dialog.open) {
      resetZoom();
      enlarged.referrerPolicy = item.referrerPolicy;
      enlarged.src = item.src;
      enlarged.alt = item.alt;
      if (lightboxCount) lightboxCount.textContent = (selected + 1) + " / " + photos.length;
      if (lightboxCaption) lightboxCaption.textContent = item.caption;
    }
  };

  thumbs.forEach((thumb, index) => {
    thumb.addEventListener("click", () => select(index, true));
  });

  openLink.addEventListener("click", (event) => {
    // Older browsers keep a working full-resolution image link as fallback.
    if (typeof dialog.showModal !== "function") return;
    event.preventDefault();
    dialog.showModal();
    lockBackground();
    select(selected);
    close.focus({ preventScroll: true });
  });

  close.addEventListener("click", () => dialog.close());
  prev.addEventListener("click", () => select(selected - 1));
  next.addEventListener("click", () => select(selected + 1));
  zoom.addEventListener("click", () => {
    const enlargedNow = stage.classList.toggle("is-zoomed");
    zoom.setAttribute("aria-pressed", String(enlargedNow));
    zoom.textContent = enlargedNow ? "Reset zoom" : "Zoom in";
  });

  dialog.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft" && !single) {
      event.preventDefault();
      select(selected - 1);
    } else if (event.key === "ArrowRight" && !single) {
      event.preventDefault();
      select(selected + 1);
    }
    // Escape and focus trapping belong to the native <dialog>.
  });

  // Horizontal swipes navigate images. Avoid intercepting vertical scrolling,
  // two-finger pinch gestures and manual scrolling in zoom mode.
  stage.addEventListener("touchstart", (event) => {
    if (single || stage.classList.contains("is-zoomed") || event.touches.length !== 1) {
      touchOrigin = null;
      return;
    }
    touchOrigin = { x: event.touches[0].clientX, y: event.touches[0].clientY };
  }, { passive: true });
  // Handle vertical swipes as immediate dismissal. Without intercepting
  // touchmove, iPhone Safari can scroll the page beneath an open dialog.
  // Horizontal swipes still change the displayed photograph.
  stage.addEventListener("touchmove", (event) => {
    if (!touchOrigin || event.touches.length !== 1 ||
        stage.classList.contains("is-zoomed")) return;
    const dx = event.touches[0].clientX - touchOrigin.x;
    const dy = event.touches[0].clientY - touchOrigin.y;
    if (Math.abs(dy) > 22 && Math.abs(dy) > Math.abs(dx) * 1.3) {
      event.preventDefault();
      touchOrigin = null;
      closeAndScrollProfile(dy);
    }
  }, { passive: false });

  stage.addEventListener("touchend", (event) => {
    if (!touchOrigin || event.changedTouches.length !== 1) return;
    const dx = event.changedTouches[0].clientX - touchOrigin.x;
    const dy = event.changedTouches[0].clientY - touchOrigin.y;
    touchOrigin = null;
    if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.7) {
      select(selected + (dx < 0 ? 1 : -1));
    }
  }, { passive: true });
  stage.addEventListener("touchcancel", () => { touchOrigin = null; }, { passive: true });

  dialog.addEventListener("click", (event) => {
    // Clicking the backdrop (not the image/controls) dismisses the viewer.
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener("close", () => {
    touchOrigin = null;
    resetZoom();
    unlockBackground();
    // Keep the image src valid to avoid broken thumbnails in page audits.
  });
})();

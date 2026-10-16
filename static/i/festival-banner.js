/* Keep the festival announcement above the schedule until dismissed. */
(() => {
  const banner = document.querySelector(".festival-banner");
  if (!banner) return;
  const key = `festival-${banner.dataset.festival}-banner-dismissed`;
  try { banner.hidden = localStorage.getItem(key) === "1"; } catch {}
  if (banner.hidden) return;
  const program = banner.closest(".program");
  const update = () => {
    const height = banner.hidden ? 0 : banner.offsetHeight + parseFloat(getComputedStyle(banner).marginBottom);
    program.style.setProperty("--schedule-top", `${height}px`);
  };
  const button = banner.querySelector("button");
  button.hidden = false;
  button.addEventListener("click", () => {
    banner.hidden = true;
    update();
    try { localStorage.setItem(key, "1"); } catch {}
  });
  update();
  banner.classList.add("sticky");
  new ResizeObserver(update).observe(banner);
})();

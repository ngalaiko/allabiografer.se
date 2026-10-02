/* Refresh showtime colours using explicit Stockholm UTC offsets. */
(() => {
  const showtimes = [...document.querySelectorAll(".schedule-cell a[data-start]")]
    .map(link => ({ link, start: Date.parse(link.dataset.start) }));
  if (!showtimes.length) return;
  const refresh = () => {
    const now = Date.now();
    for (const { link, start } of showtimes) link.classList.toggle("past", start <= now);
  };
  refresh();
  setInterval(refresh, 30000);
  document.addEventListener("visibilitychange", refresh);
})();

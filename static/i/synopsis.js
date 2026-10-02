/* Two-line synopses with per-page expansion stored locally. */
(() => {
  const buttons = [...document.querySelectorAll("[data-more]")];
  if (!buttons.length) return;
  const ids = new Set(buttons.map(button => button.dataset.more));
  const key = `synopsis:${location.pathname}`;
  let expanded = new Set();
  try {
    const saved = JSON.parse(localStorage.getItem(key) || "[]");
    if (Array.isArray(saved)) expanded = new Set(saved.filter(id => ids.has(id)));
  } catch {}
  const url = new URL(location.href);
  if (url.searchParams.has("expanded")) {
    url.searchParams.delete("expanded");
    history.replaceState(history.state, "", url);
  }
  const text = button => document.getElementById(button.getAttribute("aria-controls"));
  const measure = document.createElement("canvas").getContext("2d");
  function needsCollapse(paragraph) {
    paragraph.classList.remove("clamped");
    const range = document.createRange();
    range.selectNodeContents(paragraph);
    const lines = [...range.getClientRects()];
    const overflow = lines.slice(2).reduce((width, line) => width + line.width, 0);
    measure.font = getComputedStyle(paragraph).font;
    return overflow > measure.measureText("Visa mer…").width + 1;
  }
  function render() {
    for (const button of buttons) {
      const paragraph = text(button);
      const collapsible = needsCollapse(paragraph);
      const open = expanded.has(button.dataset.more);
      paragraph.classList.toggle("clamped", collapsible);
      paragraph.classList.toggle("expanded", open);
      button.setAttribute("aria-expanded", String(open));
      button.textContent = open ? "Visa mindre" : "Visa mer…";
      button.hidden = !collapsible;
    }
  }
  for (const button of buttons) {
    button.addEventListener("click", () => {
      const id = button.dataset.more;
      if (expanded.has(id)) expanded.delete(id); else expanded.add(id);
      try { localStorage.setItem(key, JSON.stringify([...expanded].sort())); } catch {}
      render();
    });
  }
  // Re-measures when a hidden view is shown or the layout width changes.
  const observer = new ResizeObserver(render);
  for (const button of buttons) observer.observe(text(button));
  document.fonts?.addEventListener("loadingdone", render);
  render();
})();

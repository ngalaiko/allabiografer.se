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
  const items = buttons.map(button => ({ button, paragraph: text(button), width: null }));
  const byParagraph = new Map(items.map(item => [item.paragraph, item]));
  const measure = document.createElement("canvas").getContext("2d");
  function needsCollapse(paragraph) {
    const range = document.createRange();
    range.selectNodeContents(paragraph);
    const lines = [...range.getClientRects()];
    const overflow = lines.slice(2).reduce((width, line) => width + line.width, 0);
    measure.font = getComputedStyle(paragraph).font;
    return overflow > measure.measureText("Visa mer…").width + 1;
  }
  function render({ button, paragraph }) {
    const open = expanded.has(button.dataset.more);
    paragraph.classList.toggle("expanded", open);
    button.setAttribute("aria-expanded", String(open));
    button.textContent = open ? "Visa mindre" : "Visa mer…";
  }
  function refresh(items) {
    // Unclamp together, read layout together, then apply the results together.
    for (const { paragraph } of items) paragraph.classList.remove("clamped");
    const results = items.map(({ paragraph }) => ({
      width: paragraph.getBoundingClientRect().width,
      collapsible: needsCollapse(paragraph),
    }));
    for (const [index, item] of items.entries()) {
      item.width = results[index].width;
      item.paragraph.classList.toggle("clamped", results[index].collapsible);
      item.button.hidden = !results[index].collapsible;
      render(item);
    }
  }
  for (const item of items) {
    const { button } = item;
    button.addEventListener("click", () => {
      const id = button.dataset.more;
      if (expanded.has(id)) expanded.delete(id); else expanded.add(id);
      try { localStorage.setItem(key, JSON.stringify([...expanded].sort())); } catch {}
      render(item);
    });
  }
  const pending = new Set();
  let frame = null;
  function schedule(items) {
    for (const item of items) pending.add(item);
    if (frame !== null) return;
    frame = requestAnimationFrame(() => {
      frame = null;
      const dirty = [...pending];
      pending.clear();
      refresh(dirty);
    });
  }
  // Expansion changes height, not wrapping. Only changed widths invalidate clamping.
  const observer = new ResizeObserver(entries => {
    const changed = entries.filter(entry => byParagraph.get(entry.target).width !== entry.contentRect.width);
    if (changed.length) schedule(changed.map(entry => byParagraph.get(entry.target)));
  });
  for (const { paragraph } of items) observer.observe(paragraph);
  document.fonts?.addEventListener("loadingdone", () => schedule(items));
  refresh(items);
})();

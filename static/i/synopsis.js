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
  function render() {
    for (const button of buttons) {
      const open = expanded.has(button.dataset.more);
      text(button).classList.toggle("expanded", open);
      button.setAttribute("aria-expanded", String(open));
      button.textContent = open ? "Visa mindre" : "Visa mer…";
      button.hidden = !open && text(button).scrollHeight <= text(button).clientHeight + 1;
    }
  }
  for (const button of buttons) {
    text(button).classList.add("clamped");
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
  render();
})();

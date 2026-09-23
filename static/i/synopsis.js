/* Two-line synopses with "Visa mer…"; expanded films are kept in the URL. */
(() => {
  const buttons = [...document.querySelectorAll("[data-more]")];
  if (!buttons.length) return;
  const ids = new Set(buttons.map(button => button.dataset.more));
  const read = () => new Set((new URL(location.href).searchParams.get("expanded") || "").split(",").filter(id => ids.has(id)));
  let expanded = read();
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
      const url = new URL(location.href);
      if (expanded.size) url.searchParams.set("expanded", [...expanded].sort().join(","));
      else url.searchParams.delete("expanded");
      history.replaceState(history.state, "", url);
      render();
    });
  }
  // Re-measures when a hidden view is shown or the layout width changes.
  const observer = new ResizeObserver(render);
  for (const button of buttons) observer.observe(text(button));
  addEventListener("popstate", () => { expanded = read(); render(); });
  render();
})();

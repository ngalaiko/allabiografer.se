/* Festival selections persist locally and in the URL; dates use explicit UTC offsets. */
(() => {
  function conflicts(events) {
    const result = new Set();
    for (let i = 0; i < events.length; i++) {
      for (let j = i + 1; j < events.length; j++) {
        const a = events[i], b = events[j];
        if (a.end && b.end && Date.parse(a.start) < Date.parse(b.end) && Date.parse(b.start) < Date.parse(a.end)) {
          result.add(a.id);
          result.add(b.id);
        }
      }
    }
    return result;
  }

  function calendar(festival, events, now = new Date()) {
    const stamp = value => new Date(value).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
    const escape = value => String(value).replace(/\\/g, "\\\\").replace(/\r?\n/g, "\\n").replace(/;/g, "\\;").replace(/,/g, "\\,");
    const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//allabiografer.se//Festival planner//SV", "CALSCALE:GREGORIAN"];
    for (const event of events) {
      lines.push("BEGIN:VEVENT", `UID:${encodeURIComponent(festival.slug)}-${festival.year}-${encodeURIComponent(event.id)}@allabiografer.se`,
        `DTSTAMP:${stamp(now)}`, `DTSTART:${stamp(event.start)}`);
      if (event.end) lines.push(`DTEND:${stamp(event.end)}`);
      lines.push(`SUMMARY:${escape(event.title)}`, `LOCATION:${escape(event.venue)}`,
        `URL:${event.url}`, "END:VEVENT");
    }
    lines.push("END:VCALENDAR");
    // RFC 5545 limits physical lines to 75 UTF-8 octets.
    return lines.map(line => {
      let folded = "", bytes = 0;
      for (const char of line) {
        const size = new TextEncoder().encode(char).length;
        if (bytes + size > 75) { folded += "\r\n "; bytes = 1; }
        folded += char;
        bytes += size;
      }
      return folded;
    }).join("\r\n") + "\r\n";
  }

  if (typeof module !== "undefined") module.exports = { conflicts, calendar };
  if (typeof document === "undefined") return;
  const source = document.getElementById("festival-data");
  if (!source) return;
  const festival = JSON.parse(source.textContent);
  const events = new Map(festival.screenings.map(event => [event.id, event]));
  const get = id => document.getElementById(`festival-${id}`);
  const storageKey = `festival-${festival.slug}-${festival.year}-selected`;
  let selected = new Set();
  let view = "program";
  const capture = (name, properties = {}) => window.posthog?.capture(name, {
    festival_slug: festival.slug,
    festival_year: festival.year,
    city: festival.city,
    view,
    selected_count: selected.size,
    ...properties,
  });
  const readURL = () => {
    const params = new URL(location.href).searchParams;
    let saved = params.get("selected");
    if (saved === null) {
      try { saved = localStorage.getItem(storageKey); } catch {}
    }
    selected = new Set((saved || "").split(",").filter(id => events.has(id)));
    view = params.get("view") === "selected" ? "selected" : "program";
  };
  const saveURL = () => {
    const url = new URL(location.href);
    const saved = [...selected].sort().join(",");
    try { localStorage.setItem(storageKey, saved); } catch {}
    if (selected.size || url.searchParams.has("selected")) url.searchParams.set("selected", saved);
    else url.searchParams.delete("selected");
    if (view === "selected") url.searchParams.set("view", view);
    else url.searchParams.delete("view");
    history.replaceState(null, "", url);
  };
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const stockDate = value => new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Stockholm", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value));
  const stockTime = value => new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Stockholm", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(value));
  const minutes = value => { const [h, m] = stockTime(value).split(":").map(Number); return h * 60 + m; };

  function renderPlan(chosen) {
    const grid = get("calendar");
    grid.replaceChildren();
    const overlap = conflicts(chosen);
    const days = new Set(festival.days.map(day => day.date));
    for (const event of chosen) if (event.end) days.add(stockDate(Date.parse(event.end) - 1));
    const corner = node("div", "festival-calendar-corner");
    grid.append(corner);
    const labels = node("div", "festival-calendar-hours");
    for (let h = 0; h < 24; h++) labels.append(node("div", "", `${String(h).padStart(2, "0")}:00`));
    grid.append(labels);
    let column = 2;
    for (const day of [...days].sort()) {
      const heading = node("div", "festival-calendar-day", `${day.slice(8)}/${day.slice(5, 7)}`);
      heading.style.gridColumn = column;
      const track = node("div", "festival-calendar-track");
      track.style.gridColumn = column++;
      const fragments = chosen.filter(event => stockDate(event.start) <= day && stockDate(event.end ? Date.parse(event.end) - 1 : event.start) >= day)
        .map(event => ({ event, start: stockDate(event.start) < day ? 0 : minutes(event.start),
          end: event.end ? (stockDate(event.end) > day ? 1440 : minutes(event.end)) : Math.min(1440, minutes(event.start) + 60) }))
        .sort((a, b) => a.start - b.start);
      const lanes = [];
      for (const fragment of fragments) {
        const lane = lanes.findIndex(until => until <= fragment.start);
        fragment.lane = lane < 0 ? lanes.length : lane;
        lanes[fragment.lane] = Math.max(fragment.end, fragment.start + 90);
      }
      track.style.width = `${Math.max(200, lanes.length * 170)}px`;
      for (const { event, start, end, lane } of fragments) {
        const card = node("article", "festival-calendar-event" + (overlap.has(event.id) ? " conflict" : ""));
        card.style.top = `${start}px`;
        card.style.height = `${Math.max(90, end - start)}px`;
        card.style.left = `${lane / lanes.length * 100}%`;
        card.style.width = `${100 / lanes.length}%`;
        const link = node("a", "", event.title);
        link.href = event.url;
        link.target = "_blank";
        link.rel = "noopener";
        card.append(link, node("div", "", `${event.time}–${event.end ? stockTime(event.end) : "?"} · ${event.venue}`));
        // The card removes its screening; the title link opens tickets.
        card.tabIndex = 0;
        card.setAttribute("role", "button");
        card.setAttribute("aria-label", `Ta bort ${event.title}, ${event.date} ${event.time}`);
        link.addEventListener("click", clicked => {
          clicked.stopPropagation();
          capture("festival_ticket_clicked", { screening_id: event.id, film_id: event.film_id });
        });
        card.addEventListener("click", () => toggle(event.id));
        card.addEventListener("keydown", key => {
          if (key.target === card && (key.key === "Enter" || key.key === " ")) { key.preventDefault(); toggle(event.id); }
        });
        track.append(card);
      }
      grid.append(heading, track);
    }
    grid.style.gridTemplateColumns = `60px repeat(${days.size}, auto)`;
  }

  function render() {
    const chosen = festival.screenings.filter(event => selected.has(event.id));
    const count = get("count");
    if (count.textContent !== String(selected.size) && count.dataset.ready) {
      const tab = get("selected");
      tab.classList.remove("pulse");
      void tab.offsetWidth; // Restarts the animation.
      tab.classList.add("pulse");
    }
    count.textContent = selected.size;
    count.dataset.ready = "1";
    get("export").disabled = !selected.size;
    get("all").setAttribute("aria-pressed", String(view === "program"));
    get("selected").setAttribute("aria-pressed", String(view === "selected"));
    if (get("program")) get("program").hidden = view !== "program";
    get("plan").hidden = view !== "selected";
    document.querySelector(".festival-actions").hidden = view !== "selected";
    const overlap = conflicts(chosen);
    document.querySelectorAll("[data-select]").forEach(button => {
      const active = selected.has(button.dataset.select);
      const event = events.get(button.dataset.select);
      const conflicting = overlap.has(event.id);
      button.setAttribute("aria-pressed", String(active));
      button.setAttribute("aria-label", `${active ? "Ta bort" : "Välj"} ${event.title}, ${event.date} ${event.time}, ${event.venue}${conflicting ? ", överlappar en annan vald visning" : ""}`);
      button.closest(".festival-screening").classList.toggle("selected", active);
      button.closest(".festival-screening").classList.toggle("conflict", conflicting);
    });
    renderPlan(chosen);
  }

  function toggle(id) {
    if (selected.has(id)) selected.delete(id); else selected.add(id);
    saveURL();
    render();
    capture(selected.has(id) ? "festival_screening_selected" : "festival_screening_deselected", {
      screening_id: id,
      film_id: events.get(id).film_id,
    });
  }
  function revealScreenings() {
    // The document scrolls on desktop; the page wrapper scrolls on mobile, as on the schedule page.
    const wrapper = get("page");
    const page = getComputedStyle(wrapper).overflowY === "auto" ? wrapper : document.scrollingElement;
    const origin = page === wrapper ? wrapper.getBoundingClientRect() : { top: 0, left: 0 };
    const offset = element => element.getBoundingClientRect();
    if (view === "selected") {
      const chosen = festival.screenings.filter(event => selected.has(event.id));
      const grid = get("calendar");
      const first = grid.querySelector(".festival-calendar-event");
      const heading = grid.querySelector(".festival-calendar-day");
      const covered = heading.offsetHeight + parseFloat(getComputedStyle(heading).top);
      const track = grid.querySelector(".festival-calendar-track");
      const top = offset(track).top - origin.top + page.scrollTop + (chosen.length ? Math.min(...chosen.map(event => event.minutes)) : 600) - covered - 10;
      const left = first ? offset(first).left - origin.left + page.scrollLeft - 96 : 0;
      page.scrollTo(Math.max(0, left), Math.max(0, top));
      return;
    }
    const program = get("program");
    if (!program) return;
    const cards = [...program.querySelectorAll("[data-screening]")];
    cards.sort((a, b) => events.get(a.dataset.screening).start.localeCompare(events.get(b.dataset.screening).start));
    if (!cards.length) return;
    const column = Number(cards[0].closest(".schedule-cell").style.getPropertyValue("--day-column"));
    page.scrollLeft = (column - 1) * 200;
  }
  document.querySelectorAll("[data-enhanced]").forEach(element => { element.hidden = false; });
  get("selected").addEventListener("animationend", () => get("selected").classList.remove("pulse"));
  document.querySelectorAll("[data-select]").forEach(button => button.addEventListener("click", () => toggle(button.dataset.select)));
  for (const [id, value] of [["all", "program"], ["selected", "selected"]]) get(id).addEventListener("click", () => {
    const changed = view !== value;
    view = value;
    saveURL();
    render();
    revealScreenings();
    if (changed) capture("festival_view_changed");
  });
  get("share").addEventListener("click", async () => {
    const method = navigator.share ? "native" : "clipboard";
    const selected_count = selected.size;
    try {
      if (navigator.share) await navigator.share({ title: `${festival.name} ${festival.year}`, url: location.href });
      else await navigator.clipboard.writeText(location.href);
      capture("festival_schedule_shared", { method, selected_count });
    } catch {}
  });
  get("export").addEventListener("click", () => {
    const chosen = festival.screenings.filter(event => selected.has(event.id));
    if (!chosen.length) return;
    const url = URL.createObjectURL(new Blob([calendar(festival, chosen)], { type: "text/calendar;charset=utf-8" }));
    const link = node("a", "");
    link.href = url;
    link.download = `${festival.slug}-${festival.year}.ics`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    capture("festival_schedule_exported", { format: "ics" });
  });
  window.addEventListener("popstate", () => { readURL(); saveURL(); render(); revealScreenings(); });
  readURL();
  saveURL();
  render();
  revealScreenings();
})();

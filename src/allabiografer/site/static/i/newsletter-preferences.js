/* This private page deliberately has no analytics or persistent token storage. */
(() => {
  const token = new URLSearchParams(location.hash.slice(1)).get("token");
  history.replaceState(null, "", location.pathname + location.search);
  document.addEventListener("DOMContentLoaded", () => {
    const controls = document.getElementById("preferences-controls");
    const unsubscribeAll = document.getElementById("preferences-unsubscribe-all");
    const cities = document.getElementById("preferences-cities");
    const status = document.getElementById("preferences-status");
    const error = document.getElementById("preferences-error");
    const retry = document.getElementById("preferences-retry");
    let state;
    let busy = false;
    let invalid = !token;

    function lock() {
      controls.setAttribute("aria-busy", String(busy));
      unsubscribeAll.disabled = busy || invalid || !state?.cities.length;
      cities.querySelectorAll("button").forEach(el => { el.disabled = busy || invalid; });
      retry.disabled = busy;
    }

    async function request(body) {
      const response = await fetch("/api/newsletter/preferences", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        credentials: "omit",
        cache: "no-store",
        referrerPolicy: "no-referrer",
        body: JSON.stringify(body),
      });
      if (response.status === 401 || response.status === 403) invalid = true;
      if (!response.ok) throw new Error("Request rejected");
      const data = await response.json();
      if (!Array.isArray(data.cities) || !data.cities.every(city => typeof city === "string")) {
        throw new Error("Invalid response");
      }
      return data;
    }

    function render(data) {
      state = data;
      document.getElementById("preferences-delivery-warning").hidden = data.delivery_blocked !== true;
      unsubscribeAll.parentElement.hidden = !data.cities.length;
      cities.classList.toggle("preferences-empty", !data.cities.length);
      cities.replaceChildren();
      for (const city of data.cities) {
        const row = document.createElement("div");
        row.className = "preferences-city";
        const name = document.createElement("span");
        name.textContent = city;
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "Avsluta";
        button.setAttribute("aria-label", `Avsluta ${city}`);
        row.append(name, button);
        button.addEventListener("click", () => load({ city, unsubscribe: true }));
        cities.append(row);
      }
      if (!data.cities.length) cities.textContent = "Du prenumererar inte på någon stad just nu.";
      controls.hidden = false;
    }

    async function load(update) {
      if (busy || invalid) return;
      busy = true;
      error.textContent = "";
      retry.hidden = true;
      status.textContent = update ? "Sparar…" : "Hämtar inställningar…";
      lock();
      try {
        if (update) await request(update);
        render(await request({}));
        status.textContent = update ? "Dina inställningar har sparats." : "Dina inställningar är hämtade.";
      } catch {
        status.textContent = "";
        error.textContent = invalid
          ? "Länken är ogiltig eller har gått ut. Öppna länken till inställningar i ditt senaste nyhetsbrev."
          : "Kunde inte hämta eller spara inställningarna. Försök igen. Om du sparade kan ändringen redan ha genomförts.";
        retry.hidden = invalid;
      } finally {
        busy = false;
        lock();
      }
    }
    unsubscribeAll.addEventListener("click", () => load({ unsubscribe: true }));
    retry.addEventListener("click", () => load());
    if (invalid) {
      status.textContent = "";
      error.textContent = "Länken saknar behörighet. Öppna länken till inställningar i ditt nyhetsbrev.";
    } else load();
  });
})();

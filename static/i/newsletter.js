/* Single opt-in, independent of the site's anonymous analytics SDK. */
(() => {
  const form = document.querySelector(".newsletter-form");
  if (!form) return;
  const row = form.closest(".newsletter-row");
  const city = form.elements.city.value;
  const storageKey = `newsletter-hidden:${city}`;
  try {
    if (localStorage.getItem(storageKey)) row.hidden = true;
  } catch { /* Signup still works when storage is unavailable. */ }
  const dismiss = row.querySelector(".newsletter-dismiss");
  dismiss.hidden = false;
  dismiss.addEventListener("click", () => {
    row.hidden = true;
    try { localStorage.setItem(storageKey, "dismissed"); } catch { /* Optional persistence. */ }
  });
  const button = form.querySelector("button");
  const note = document.getElementById("newsletter-note");
  button.disabled = false;
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    form.setAttribute("aria-busy", "true");
    note.textContent = "Skickar…";
    try {
      const response = await fetch("/api/newsletter/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: form.elements.email.value, city }),
        credentials: "omit",
      });
      const result = await response.json();
      if (!response.ok || result.success !== true) throw new Error("Signup rejected");
      note.textContent = `Tack! Du prenumererar nu på nyhetsbrevet för ${city}.`;
      form.querySelector(".newsletter-controls").hidden = true;
      try { localStorage.setItem(storageKey, "subscribed"); } catch { /* Optional persistence. */ }
    } catch {
      note.textContent = "Kunde inte nå servern. Försök igen om en stund.";
    } finally {
      button.disabled = false;
      form.removeAttribute("aria-busy");
    }
  });
})();

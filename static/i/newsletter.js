/* Single opt-in, independent of the site's anonymous analytics SDK. */
(() => {
  const form = document.querySelector(".newsletter-form");
  if (!form) return;
  const button = form.querySelector("button");
  const note = document.getElementById("newsletter-note");
  const token = form.dataset.posthogToken;
  const host = form.dataset.posthogHost;
  if (!token || !host) {
    note.textContent = "Nyhetsbrevet är inte tillgängligt just nu.";
    return;
  }
  button.disabled = false;
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    form.setAttribute("aria-busy", "true");
    note.textContent = "Skickar…";
    try {
      const email = form.elements.email.value.trim().toLowerCase();
      const city = form.elements.city.value;
      // Keep the existing newsletter identity convention. Hash long addresses
      // to stay within PostHog's 200-character distinct_id limit without collisions.
      let identity = email;
      if (email.length > 189) {
        const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(email));
        identity = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, "0")).join("");
      }
      const response = await fetch(`${host.replace(/\/$/, "")}/i/v0/e/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_key: token,
          event: "newsletter_signup",
          distinct_id: `newsletter:${identity}`,
          properties: {
            $process_person_profile: true,
            $geoip_disable: true,
            $set: { email, newsletter_confirmed: "yes", [`newsletter_subscribed_city_${city}`]: "yes" },
          },
        }),
        credentials: "omit",
      });
      const result = await response.json();
      if (!response.ok || ![1, "Ok"].includes(result.status)) throw new Error("Signup rejected");
      note.textContent = `Tack! Du prenumererar nu på nyhetsbrevet för ${city}.`;
    } catch {
      note.textContent = "Kunde inte nå servern. Försök igen om en stund.";
    } finally {
      button.disabled = false;
      form.removeAttribute("aria-busy");
    }
  });
})();

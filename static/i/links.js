/* Attribute outbound web links, including dynamically rendered links. */
(() => {
  const attribute = event => {
    const link = event.target.closest?.("a[href]");
    if (!link) return;
    const url = new URL(link.href);
    if (!["http:", "https:"].includes(url.protocol) || url.origin === location.origin) return;
    url.searchParams.set("utm_source", "allabiografer.se");
    link.href = url.href;
  };
  for (const event of ["click", "auxclick", "contextmenu"]) {
    document.addEventListener(event, attribute, true);
  }
})();

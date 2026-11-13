# Development

## Setup (Nix on Linux)

Enter the pinned development shell with Nix flakes enabled:

```sh
nix develop
git lfs install --local
git lfs pull origin
uv sync --locked --group dev --group parse --group build
```

The shell supplies uv, Git LFS, mise, Node, Chromium, fallback fonts, and the
C++ runtime needed by Python wheels such as greenlet and curl_cffi. Python
dependencies and tasks are managed by `pyproject.toml`, `uv.lock`, and
`mise.toml`; Nix does not install Python packages. The database, posters, and
web fonts use Git LFS: hydrate them before building or testing rather than
using pointer files from an unhydrated checkout.

Before using `mise run` in a new checkout, review `mise.toml` and run
`mise trust` if mise reports that the configuration is not trusted.

### Amp MCP connections

Repository-local servers are configured in [`.amp/settings.json`](../.amp/settings.json).
Approve them when Amp prompts after opening the repository or reloading MCP.

- **Cloudflare** and **PostHog** use the existing personal remote MCP connections
  in [Amp integrations](https://ampcode.com/settings/integrations), rather than
  duplicating their OAuth credentials in this repository. PostHog's
  `allabiografer.se` project ID is `273892`.
- **Fly.io** connects to the [official hosted server](https://mcp.fly.io) using
  OAuth. Sign in when Amp prompts and limit the grant to the required
  organization and the `allabiografer-se` app. No Fly token belongs in the repo.
- **Google Search Console** runs the unofficial
  [open-gsc-mcp](https://github.com/onlymoein/google-search-console-mcp) server,
  pinned to `1.4.0`, through the repository's Nix-provided `uvx`. Its write tools
  are disabled with `GSC_ENABLE_WRITES=0`. Authentication is separate from MCP
  discovery: tools can load before Google credentials are available.

For Search Console, enable the Google Search Console API in your Google Cloud
project and create a **Desktop app** OAuth client. Keep the downloaded JSON
outside the checkout, at `~/.config/open-gsc-mcp/client_secret.json` on the machine
running Amp. Follow the server's [authentication instructions](https://github.com/onlymoein/google-search-console-mcp#quick-start),
including consent-screen configuration, then sign in with read-only access:

```sh
nix develop --command uvx open-gsc-mcp==1.4.0 auth login --read-only --no-browser --client-file "$HOME/.config/open-gsc-mcp/client_secret.json"
nix develop --command uvx open-gsc-mcp==1.4.0 auth status
```

The login command provides instructions for completing authorization from another
device. OAuth tokens stay in the server's per-user configuration directory, never
in Git. For a headless service account instead, supply `GSC_SERVICE_ACCOUNT_FILE`
through the executor environment with an absolute path to a key outside the
checkout, and grant that account access to the `allabiografer.se` Search Console
property. Credentials on one runner are not automatically available in orbs.
Verify access by calling `list_sites` and use the exact property it returns;
do not assume a domain property rather than a URL-prefix property.

These connections do not authorize deployments or production changes. Continue
to obtain approval before changing Cloudflare settings, deploying on Fly.io, or
modifying PostHog resources.

## Tests

Run tests inside the shell:

```sh
uv run --locked --group dev --group parse --group build pytest
node --test tests/*.test.cjs
```

Browser tests use the shell's `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` and font
configuration; no `playwright install` or browser download is needed. Outside
Nix, tests use Playwright's default browser lookup or the same environment
variable for an existing Chromium. The Nix shell supports x86_64 and aarch64 Linux.

## Parse, build and preview

Screenings, movies, films and venues live in `data/allabiografer.db`. Posters
live in `data/posters/`: `{tmdb_id}.jpg` for TMDB, `{source}/{title}.jpg` for
posters taken from a cinema's own site.

```sh
mise run parse
mise run build
mise run serve
```

The static preview serves the built site on port 8000; it does not run the
newsletter's nginx/Lua API. See [newsletter operations](newsletter.md) for that backend.

Film pages normally show the same 14-day timetable as city programmes. When a
national or city-specific film page has only later bookings, it shows the next
booked day instead, with film details, ticket links and an explicit notice giving
the next screening's date, year and time. HTML and Markdown use the same fallback;
city, cinema, genre programmes and city JSON feeds retain their 14-day window.

### Markdown for agents

The build writes an `index.md` beside each HTML page, directly from the same
database-backed page data rather than converting HTML. Programme text includes
film descriptions, versions, cinemas, dates, times and ticket links; festival
pages include their full programmes. Scripts, forms and layout are omitted.

Production nginx serves this representation at the original page URL when
`Accept: text/markdown` is explicitly requested with a positive quality value
at least as high as HTML's. Explicit types take precedence over `text/*` and
`*/*`; ties prefer Markdown. HTML remains the default for browsers and wildcard-only
requests, and unsupported types retain the HTML fallback rather than returning 406.
Public HTML pages advertise their direct `index.md` URL with `rel="alternate"`.
Successful HTML and Markdown responses also include reciprocal HTTP `Link` headers.
Screening times in programme and festival HTML use `<time datetime="…">` with
the screening's full date and Stockholm UTC offset, without changing visible labels.
Responses declare `Vary: Accept` so caches distinguish
the variants, and Markdown uses `Content-Type: text/markdown; charset=utf-8`.
Assets, API routes and missing-page fallbacks keep their existing behavior.
No tokenizer is configured, so no `x-markdown-tokens` estimate is emitted.

The Python static preview does not negotiate content; open `index.md` directly
there. `tests/test_nginx.py` exercises negotiation and discovery through real
Lua-enabled nginx (`openresty` in `nix develop`, the same runtime used by newsletter tests).

The build also generates `/llms.txt`: a factual access guide covering Markdown
negotiation and direct URLs, programme indexes, the city JSON contract and its
freshness/coverage limitations. Its city feed links come from the generated city
list, not hard-coded examples. HTML pages link to the guide with `rel="help"`.
It is a convenience for clients that discover or are given the URL, not a claim
that assistants automatically fetch it. There is no full-site `llms-full.txt` dump.

### City JSON feeds

Every generated city programme also has a static `/stad/{slug}/index.json`,
for example `/stad/göteborg/index.json`. City HTML advertises it with
`<link rel="alternate" type="application/json">`; both HTML and Markdown
responses advertise it in HTTP `Link` headers. Fetch the JSON URL directly;
`Accept: application/json` does not change the representation at the HTML URL.
JSON responses link back to the HTML programme. No authentication or backend is needed.

The version 1 contract contains:

- `schema_version`, `city`, the canonical programme `url`, and `timezone`
  (`Europe/Stockholm`).
- `generated_at`: an ISO 8601 build timestamp with UTC offset, shared by all
  city feeds in a build. This is **not** the time a cinema's programme was fetched.
- `coverage.starts_on` (inclusive) and `coverage.ends_before` (exclusive): the
  same 14 local calendar days as HTML/Markdown, including elapsed times today.
  `screening_count` counts records; `cinema_count` counts cinemas represented in
  those records. `status` is `listings_found` or `no_listings_found`, while
  `completeness` is always `unknown`: an empty feed does not prove that nothing
  is showing, or distinguish an unpublished programme from a failed parser.
- `sources`: source IDs observed in stored upcoming city data, including records
  beyond the feed window. Each `fetched_at` is currently `null`: the database
  records neither source fetch timestamps nor parser health. Failed/empty parses
  can retain older listings. The source list is not a registry of every cinema or
  an assurance that every source was fetched successfully.
- `screenings`: chronologically ordered records with a timezone-aware `start`,
  `film` (title, nullable TMDB ID, source key, programme URL and runtime in minutes),
  `cinema` (name, nullable address and screen, programme URL), `ticket_url`, `source`,
  `version`, `presentation`, and `accessibility`. Build-only synthetic movie IDs
  are published as `null`. Missing URLs and metadata are `null`, not guessed.

Version and presentation values follow the stored screening facts, not inferred
film languages or merged display labels. Audio `kind: "unknown"` and an empty
audio-language list mean unknown. Subtitle languages are `null` for unknown,
`[]` for explicitly no subtitles, or an array of Swedish language names such as
`["Engelska"]`. Presentation dimensions/media use `"unknown"` when missing;
empty feature arrays mean no recorded facts, not confirmed absence. Accessibility
is `null` when unknown, otherwise a list of recorded features (not an exhaustive
assessment). No prices, seat availability or screening end times are inferred.
Ticket links may target a cinema's general booking page rather than a specific show.

Feeds contain regular programme data only, not the separate festival planner.
Compatible observations of one screening across sources are combined; distinct
or ambiguous variants can still overlap. There is no 100-event JSON-LD cap.
A city without a generated programme has no feed. Changes to the contract require
updating this documentation and, for breaking changes, its version.

### Sharing images

The build generates 1200 × 630 JPEG cards in `/og/` for every public page type.
`src/build/og.py` reads the light-mode colours from `static/i/style.css` and uses
the same Fira Sans Regular/SemiBold WOFF2 files as the website. Cards have a header
with the existing favicon and domain, with the title and subtitle below and an
optional poster on the right. Text-only cards use the full content width. Titles
have generous space below the header and shrink to fit longer names. Cards use
the site's background and text colours without footers or grid lines. Check text
at actual 300px and 600px preview widths. Film cards contain
the original poster without cropping; missing or unreadable posters fall back to
text-only cards. Festival cards include the edition year in the title.
Newsletter preferences use the generic site card, without subscriber data.

Image URLs hash the card content, artwork, renderer, CSS, fonts and favicon so changes get
new URLs. Generated images are build output, not tracked assets. Open Graph and
Twitter metadata share the same absolute image URL, dimensions and descriptive alt
text. To inspect a card locally, follow its generated HTML's `og:image` path under
the output directory.

Successful non-empty parses replace each source's screenings from today onward
(Europe/Stockholm), removing cancelled or rescheduled listings. Screenings on
past dates are retained. Failed or empty parses keep the previous programme.

Individual parsers can run separately:

```sh
mise run parse:folkets_hus_och_parker
mise run parse:cinemascenen_se
```

Folkets Hus och Parker includes Bio Roy in Göteborg, Spegeln in Malmö, and
Röda Kvarn in Helsingborg. Cinemascenen includes Ystad, Katrineholm, Strängnäs,
Söderhamn, and Hudiksvall. See [mise tasks](../mise.toml) for all parser commands.

## Programme data and grouping

Screenings store typed content versions, presentation, and accessibility in JSON
columns. Film languages belong to film metadata. Missing audio, subtitles,
dimension, and projection remain unknown; explicit no subtitles is distinct.

Film metadata is pooled only across screenings with the same TMDB identity.
Unmatched films retain their source film key as a separate build-time identity;
equal titles alone do not prove that two recordings or adaptations are the same
work. Source metadata and posters stay with that identity. Same-title works have
distinct programme pages and feed URLs; the preferred existing TMDB identity
keeps the plain title slug and the others receive identity suffixes. Bio.se and
Osby Borgen supply source runtimes to TMDB matching, so an incompatible runtime
does not fall back to a cached title-only match.

Programme blocks group compatible content and presentation facts, including all
screening modifiers. Atmos, 4K, Laser, VIP, XL, and audio description each define
distinct variants. Overlapping spoken-language facts merge; disjoint facts and
ambiguous screenings stay separate. Unknown subtitle facts have no heading;
explicit no subtitles remains distinct. The standard presentation has no label.

## Festivals

Festival planners live at `/festival/{slug}/{year}/`. Editions are defined in
[`src/parse/festivals.py`](../src/parse/festivals.py); their screenings are stored
in the `festivals` and `festival_screenings` tables, independently of the regular
two-week cinema programme. Times include explicit UTC offsets.

Refresh programmes with `mise run parse:festivals` (also included in
`mise run parse`), then build normally. Importers read public APIs selected by
each edition's `source`:

- `stockholm`: dated screenings with a festival section. End times use film
  runtimes and exclude talks and travel.
- `prisma` (Göteborg Film Festival): films and short-film packages; happenings
  are excluded.

The planner supports selections, a personal calendar, overlap warnings, shared
URLs, and downloaded iCal files. Selections are stored in the URL and locally
in the browser for each festival edition. Explicit selections in a shared URL
replace the saved selection; otherwise, the saved schedule is restored.
Calendar exports are snapshots; export again after programme changes.

Run planner logic tests with `node --test tests/festival.test.cjs`.

## Deployment

The site runs on [Fly.io](https://fly.io) using [fly.toml](../fly.toml).

```sh
fly deploy
```

The newsletter backend runs in the same nginx container and requires a single
backend instance. Runtime secrets, signing, and delivery configuration are
documented in [Newsletter](newsletter.md#backend-api-credentials-and-concurrency).

### HTTP caching

Nginx defines cache policies in `etc/nginx/cache.conf`:

- CSS, JavaScript and fonts with the build's `?v=` content hash, content-hashed
  posters, and sharing images get `public, max-age=31536000, immutable`.
- Unversioned icons get a one-day public cache lifetime.
- Pages, Markdown, JSON feeds, other unversioned files, redirects and errors use
  `no-cache`: stored responses must be revalidated before reuse. Nginx supplies
  ETag and Last-Modified validators for static files.
- Newsletter APIs retain their Lua `no-store` policy; the analytics proxy retains
  upstream cache headers. Neither receives the static-site cache policy.

Cache and `Vary: Accept` headers are set together at server scope, including on
304 responses. Gzip and Brotli cover HTML, CSS, JavaScript, JSON, Markdown, plain
text and XML.

Cloudflare's Browser Cache TTL is set to **Respect Existing Headers** (API value
`0`), so nginx owns browser expiration. Keep negotiated HTML/Markdown URLs out of
edge caching unless the cache key distinguishes their representations; the
origin's `Vary: Accept` alone is not sufficient for Cloudflare's default cache key.

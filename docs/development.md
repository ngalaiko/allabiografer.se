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

### Film consolidation and stable URLs

`mise run parse` first runs independent source fetches (`mise run fetch`), then
`mise run reconcile`. Fetches save source films, screenings and constrained TMDB
query hints without contacting TMDB. Reconciliation first groups source films,
then optionally matches those groups to TMDB, combines compatible observations of the same
screening, and atomically saves the final catalogue and schedule. The static
`build` command reads that saved snapshot; it does not match films or allocate URLs.

`catalogue_films` reserves a permanent identity and title-based slug. Collisions
receive numeric suffixes, never source names or source hashes. Adding a TMDB
match, changing a title, or losing a competing film's screenings does not rename
an existing identity. Confirmed later merges retain the oldest identity; old
slugs point directly to its slug through the generated nginx map. Initial import
also records the current legacy slugs as aliases. Only canonical URLs enter links
and sitemaps. Known film, city-film, city, cinema and city-genre pages remain static
pages when their screenings expire. Film pages retain metadata and explicitly say
that no upcoming screenings are published; expired tickets and structured-data
events are removed. The snapshot retains film/location associations independently
of its current schedule, including after a source removes its listings. Raw historical
place names outside the catalogue are not imported as page URLs. Confirmed aliases
still redirect permanently, while unknown URLs return 404 rather than redirecting
to unrelated city or home pages. Retention makes pages eligible for indexing; it
does not guarantee that a search engine will index sparse pages.

Matching rules:

- Initial grouping uses source facts only, never metadata inferred from TMDB.
  Existing TMDB IDs are claims to validate, not proof that two source films match.
- The same source film key and exact nonempty film URL preserve identity across
  partial TMDB enrichment.
- Otherwise, normalized titles or confirmed group aliases must overlap. Evidence
  is a shared venue/date/time with compatible halls, the same release year with
  runtimes within two minutes, or substantial shared synopsis text.
- Shared synopsis evidence requires at least 20 consecutive words and 100
  characters, plus half the shorter synopsis, 90% total word alignment, or a
  corroborating known director credit where available. Only this stronger evidence allows
  programme-duration differences up to 25% of the shorter runtime.
- Source groups also accept a complete shorter synopsis of at least 15 words and
  100 characters contained verbatim in the other description after normalization.
  This still requires overlapping titles and source runtimes within two minutes
  when both are known. Short fragments, descriptions below these length limits
  and conflicting years do not qualify. This rule does not relax TMDB's synopsis
  or runtime requirements.
- Strong matches precede weaker year/runtime matches; confirmed groups share
  aliases and evidence until no further joins are possible. All group members
  are checked to prevent weak runtime chains or bridges between different works.
  Source years differing by more than one remain barriers.
- Each established source group pools its titles, original titles, runtime/year
  hints and explicit credits before validating TMDB candidates. Search results
  include alternative and translated titles; exact normalized title overlap is
  required, alongside independent year, runtime, director or substantial synopsis
  evidence. The first search result and bare historical IDs never win by default.
- After checking the complete inventory, independently validated source titles
  also discover candidates for other groups. These aliases supply no year,
  duration, director or synopsis evidence: every group must still qualify on its
  own facts. All groups are rechecked against the expanded inventory, including
  competing candidates. Inferred aliases are rebuilt on every reconciliation,
  not saved as authoritative TMDB titles or used to bootstrap further aliases.
- Explicit four-digit original years and query/title years constrain candidates;
  complete source premiere dates provide positive year evidence but do not veto
  an earlier original release. Ordinary runtime tolerance is five minutes,
  inclusive, and every known source/query duration must fit that tolerance.
  Substantial shared synopsis permits differences up to 25% of the shorter runtime;
  explicitly documented cuts permit edition differences with other corroboration.
  Conflicting explicit director credits reject a candidate.
- Source director lists are stored independently of TMDB. Capitol Stockholm,
  Cinemascenen and Kiviks Bio read their labelled `Regi` fields without mixing
  credits into the synopsis. Filmography, country and conductor fields are not
  part of a director's name. Explicit synopsis credit phrases remain a fallback, including Swedish
  `regisserat av`, `[director] har regisserat` and introductions from a named director;
  actor names, possessive names and comparison mentions alone supply no director evidence. bio.se accepts
  explicit introductory original years with multiple descriptive adjectives, but
  never plot-setting, screening or comparison-film years.
- Each source's director list needs at least one verified name in common with the
  candidate; lists need not be exhaustive or identical. Disjoint claims from separate
  sources remain a conflict. When needed, enrichment caches English credits and
  person aliases only for people credited as `Director`, handling different scripts
  without guessed transliterations. Director comparison folds Latin diacritics
  without changing film-title normalization or other scripts. The
  `tmdb_director_aliases` cache is reused offline and invalidated when the movie's
  metadata is refreshed; retrieval errors cannot silently eliminate a competing
  candidate.
- A unique candidate with both an explicit matching director credit and runtime
  corroboration takes precedence over weaker qualifying candidates. Contradictions
  still reject it. Otherwise exactly one candidate must satisfy the evidence without
  contradictions; multiple qualifying candidates leave the group unenriched.
  Groups independently validated to the same TMDB ID then join, including translated
  titles and documented editions.
  The whole discovered inventory is checked before final decisions, so later alias
  searches cannot leave earlier false-unique matches. During an outage only an
  unchanged, still-valid previously validated association can be retained.
- A confirmed TMDB detail 404 rejects that ID rather than treating its stale
  cached metadata as a competing film. Transient failures do not eliminate
  candidates. `tmdb_fetches` records successful alias-complete detail fetches
  and confirmed 404s; a later successful fetch clears the missing-ID status.
  Mature, already fetched unrelated candidates reuse their metadata instead
  of being downloaded again for every broad title search.
- Uncertain records stay separate and publication continues. Equal titles alone
  never prove identity. `reconciliation_candidates` saves unresolved pairs and
  reasons, excluding pairs already joined; `catalogue_members.data` saves source
  facts and match reasons.
  `catalogue_tmdb_matches.data` records group members, independent source facts,
  candidate IDs, corroborating evidence, rejection reasons and the selected ID.
  Evidence is reevaluated on every run so corrected metadata or rules can split
  an incorrect previous join. A correction may necessarily create a new identity.
  Current source film rows supersede historical copies of their metadata; past
  screening evidence and URL ownership remain. Inputs are canonically ordered
  so parser completion order cannot select fallback titles or change the saved
  schedule.

Deferred TMDB hints retain the first lookup's runtime/year constraints. Fetching
does not execute a parser's relaxed fallback branches without a matching result;
reconciliation never silently drops those constraints.

For a reproducible offline backtest, copy the database, keep its poster directory
beside it (or symlink the existing directory), and run:

```sh
uv run reconcile --db /path/to/copy.db --today 2026-11-17
uv run --group build build /path/to/site --db /path/to/copy.db
```

Add `--enrich` with the parse dependency group to resolve saved query hints against
TMDB. The offline command validates source groups against stored candidate
metadata and aliases, without requests or blind reuse of historical IDs.
Inspect unresolved cases with `SELECT * FROM reconciliation_candidates` and
confirmed groups by joining `catalogue_members.film_id` to `catalogue_films.id`.
Keep these identity and slug tables when refreshing sources; rebuilding them
from scratch discards URL history.

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
Each film has one heading, with any format or language variants listed beneath it.
Showtimes are grouped into compact lists by cinema. Links between generated
pages point directly to `index.md`; external festival and ticket links are unchanged.

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

### Schedule representations

Every schedule page has four representations: the normal HTML programme,
Markdown (`index.md`) limited to the next 14 local calendar days, and two
uncapped feeds: Schema.org JSON-LD (`index.jsonld`, `application/ld+json`)
and iCalendar (`index.ics`, `text/calendar`). The feeds include all available
showtimes for the page's filter, including those beyond the display window.
HTML advertises its siblings with `<link rel="alternate">`, and all four
representations advertise their siblings with HTTP `Link` headers. Fetch the
feed URLs directly; screening events are not duplicated in the HTML head.

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
BioSverige schedule failures and malformed Bio.se cinema payloads abort the whole
source import, even if another cinema succeeded, so partial results cannot erase
the failed cinema's stored listings.

Individual parsers can run separately:

```sh
mise run parse:folkets_hus_och_parker
mise run parse:cinemascenen_se
```

Folkets Hus och Parker includes Bio Roy in Göteborg, Spegeln in Malmö, and
Röda Kvarn in Helsingborg. Cinemascenen includes Ystad, Katrineholm, Strängnäs,
Söderhamn, and Hudiksvall. See [mise tasks](../mise.toml) for all parser commands.

`bioguiden_se` imports 90 public Bioguiden programme records for 89 cinemas
not currently supplied by our other sources. Coverage includes Lycksele,
Leksand (Visir), Kristinehamn, Saga in Höganäs, Scala in
Ystad and smaller-town cinemas across Sweden. The explicit URLs, canonical
venue names and addresses are in
[`_SITES`](../src/parse/parsers/bioguiden_se.py).
Run it with `mise run parse:bioguiden_se`; it is also included in `mise run parse`.
Existing venue names and city groupings are reused where available; otherwise
towns come from the cinema's address rather than Bioguiden's municipality selector.
Varbergs Teater has two programme records, both imported under one venue name.

When verified programmes disagree, pick one schedule per cinema instead of
combining conflicting times. `bioaspen_se` and `biofagelbla_se` use the cinemas'
own programmes and dated ticket links; the aggregators no longer import those
venues. Separately ticketed events are a coverage question, not timing conflicts.

The 2026-11-14 nationwide audit covered all 203 municipalities and 442 cinema
records listed by Bioguiden: 297 had programmes, of which 91 were imported at the
time, 204 had coverage through other sources, and two were held back.
The other 145 records had no screenings. In particular, Odeon in Skövde is
already supplied under Skövde Filmfestival, and Ersboda is covered by Tickster.
Bollnäs Filmklubb remains excluded because membership restrictions are unclear.
Biograf Fokus in Jönköping is also excluded: the operator mixes public screenings
with membership-only Filmstudion screenings, and Bioguiden does not distinguish
them. Varbergs Filmklubb is included: its operator explicitly sells individual
public tickets. See [Fokus ticket policies](https://www.jonkoping.se/fritid-kultur--natur/kultur-konst-och-upplevelser/film/filmvisningar-i-biograf-fokus)
and [Varbergs Filmklubb's ticket FAQ](https://varbergsfilmklubb.se/faq).

Booking redirects are resolved to direct ticket links; screenings without
online booking link to the cinema's Bioguiden programme instead. Cinema-name
aliases are not treated as auditoriums. When the programme names distinct halls,
all hall names are retained, including Aspen's eponymous hall and Lusoperan.
Duplicate listings prefer the online booking link without merging simultaneous
shows in different auditoriums. Placeholder posters are ignored. Language,
presentation and screening accessibility remain unknown rather than inferred
from film-level metadata. Failed requests, wrong-cinema pages and malformed
screenings abort the import, preserving the previous programme.

`capitolbio_se` imports Bio & Bistro Capitol in Stockholm for the next 14 days,
using the public calendar's date filter to avoid its infinite-scroll limit.
It is separate from Capitol Göteborg (`wp_theatre`) and Capitol Varberg
(`filmstaden_se`). Wine-tasting events are excluded.

`tickster_se` imports verified cinema organisers in Finspång, Emmaboda,
Grebbestad, Sjöbo, Gnesta, Vilhelmina, Säter, Älvsbyn, Kristianstad (Roxy),
Karlshamn (Metropol), Umeå (Ersboda) and Skarpnäck. It follows organiser pagination and
uses event-page start times, not doors-open times. Only events tagged `bio`
at the configured venues qualify; gift cards, templates, non-film events and
dates more than a year ahead are excluded. Cinemas covered by another parser
are deliberately left out. Extend its organiser list only after checking for
existing coverage. A failed programme or event request aborts the import,
preserving the previous programme rather than replacing it with partial data.

`kraftenifinspang_se` supplements Tickster with explicitly free `Film/Bio`
events from Kraften i Finspång's public calendar API. It follows every result
page, converts UTC starts to Stockholm time and links to the event information
page instead of requiring a purchase link. Unknown prices are not assumed free;
paid events and events linking to Tickster are excluded to avoid overlap.

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
does not fall back to a cached title-only match. BioSverige and Söderköpings Bio
also retain supplied runtimes when trying either the listed or original title.

TMDB title-index hits enforce the same five-minute runtime tolerance as search
results, using refreshed metadata when available. Upcoming releases and films
whose original or Swedish release was within the last 30 days refresh once per
movie and database per parser process, including failed refresh attempts.
Older complete metadata stays cached; missing language/director metadata is
also fetched once per process. A failed refresh preserves the stored movie.

Programme durations use the cinema's source runtime; a missing source duration
stays null rather than borrowing TMDB's or another cinema's duration. Movie metadata
is used only when no source film record exists. Zero means unknown, not a zero-length
film. Whole-hour durations display without a redundant zero-minute suffix.
Within the same film and screening variant, programme blocks
combine durations spanning at most five minutes, using the shortest duration in
the block's heading. Groups are formed in ascending duration order, so chains of
small differences cannot merge cuts more than five minutes apart. Unknown durations
share the shortest known block of that same variant (or one duration-free block
when all are unknown), never bridging distinct known cuts. This display placement
does not assign a duration to an unknown screening. Film identity and URLs do not
change. City JSON retains exact durations or null; structured events omit end times
when duration is unknown. A film with multiple or unknown listed durations has no
single duration in its structured Movie node.

Programme blocks group compatible content and presentation facts, including all
screening modifiers. Atmos, 4K, Laser, VIP, XL, and audio description each define
distinct variants. Overlapping spoken-language facts merge; disjoint facts and
ambiguous screenings stay separate. Unknown subtitle facts have no heading;
explicit no subtitles remains distinct. The standard presentation has no label.

## Festivals

Festival planners live at `/festival/{slug}/{year}/`. Editions and their
screenings are stored in the `festivals` and `festival_screenings` tables,
independently of the regular two-week cinema programme. Times include explicit
UTC offsets. The 2026 Stockholm and Göteborg Prisma editions are no longer
refreshed or published; their stored screenings are retained.

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

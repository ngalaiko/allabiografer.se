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

### Sharing images

The build generates 1200 × 630 JPEG cards in `/og/` for every public page type.
`src/build/og.py` reads the light-mode colours from `static/i/style.css` and uses
the same Fira Sans Regular/SemiBold WOFF2 files as the website. Cards have a header
with the existing favicon and domain, followed by the poster (when available),
title and subtitle, using the site's background and text colours without footers
or grid lines. Poster and title share a top edge. Check text at actual 300px
and 600px preview widths. Film cards contain
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

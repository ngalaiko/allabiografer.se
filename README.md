# allabiografer.se

A static site aggregating cinema screenings across Sweden. Reimplementation of [allekinos.de](https://allekinos.de/) by [Nikita Tonsky](https://tonsky.me/) for the Sweden.

## Usage

Screenings, movies, films and venues live in `data/allabiografer.db`; posters in `data/posters/` — `{tmdb_id}.jpg` for TMDB, `{source}/{title}.jpg` for posters taken from a cinema's own site.

Parse screenings from all supported cinemas:

```
mise run parse
```

Parse Folkets Hus och Parker (Bio Roy in Göteborg, Spegeln in Malmö, Röda Kvarn
in Helsingborg):

```
mise run parse:folkets_hus_och_parker
```

This replaces `bioroy_se`; its stored screenings are replaced on a successful run.

Build the static site:

```
mise run build
```

Serve locally:

```
mise run serve
```

Screenings store typed content versions, presentation, and accessibility in JSON
columns. Film languages belong to film metadata. Missing audio, subtitles,
dimension, and projection remain unknown; explicit no subtitles is distinct.

Programme blocks group compatible content and presentation facts, including all
screening modifiers. Atmos, 4K, Laser, VIP, XL, and audio description each define
distinct variants. Overlapping spoken-language facts merge; disjoint facts and
ambiguous screenings stay separate. Unknown subtitle facts have no heading;
explicit no subtitles remains distinct. The standard presentation has no label.

Legacy screening databases require a fresh parse; no data migration runs.
Parse into a new database with `parse --output /path/to/new.db <parser>`.

## Deployment

Deployed to [Fly.io](https://fly.io).

```
fly deploy
```

## Festivals

Festival planners live at `/festival/{slug}/{year}/`. Editions are defined in
`src/parse/festivals.py`; their screenings are stored in the `festivals` and
`festival_screenings` tables, independently of the regular two-week cinema
programme. Times include explicit UTC offsets.

Refresh programmes with `mise run parse:festivals` (also included in
`mise run parse`), then build normally. Importers read the festivals' public
APIs, selected by each edition's `source`:

- `stockholm`: dated screenings with a festival section. End times use film
  runtimes and exclude talks and travel.
- `prisma` (Göteborg Film Festival): films and short-film packages; happenings
  are excluded.

The planner supports selections, a personal calendar, overlap warnings, shared
URLs, and downloaded iCal files. Selections are stored in the URL. Calendar
exports are snapshots; export again after programme changes.

Run planner logic tests with `node --test tests/festival.test.cjs`.

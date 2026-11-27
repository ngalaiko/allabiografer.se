# Adapters

An adapter reads one website's programmes. Each is a package here named after the site
(`roxy_bio`, `filmstaden_se`), with three modules:

| Module | Contract |
|---|---|
| `__init__.py` | `SITE = "roxy.bio"`: the website, naming its steps (`Download roxy.bio`) and datasets |
| `fetch.py` | `fetch_pages(session, inputs, today, *, selectors=None)` saves every file the reader needs into `inputs` |
| `parse.py` | `rows(inputs, today)` yields one row per screening from those files alone |

`site.py` holds what both share: URLs, venue lists, page parsing. `roxy_bio` is a small,
complete example: one cinema, a JSON API, a details request per film.

## Download

- Save with the helpers in `_shared.py`: `capture_json`, `capture` and `saved` record each
  file's URL, which the stored `DataDownload` keeps as `isBasedOn`.
- File names are stable and say what the file is: `programme.json`, `movie-<id>.json`. The
  reader finds files by these names.
- Save everything the reader will read; it gets no network. Save posters too when the site
  serves them only to a browser, and name them in the movie's `image`.
- `selectors` is the set of venue IDs the run's feeds select (`None` means all). A
  single-cinema site calls `single(selectors)`; a multi-venue site downloads the selected
  venues only and rejects unknown IDs with `schedule.checked`.
- Raise when the site answers but makes no sense (an error code, a page without its
  programme): a failed download keeps the feeds' previous screenings, a wrong one replaces them.

## Read

`rows` yields `(venue, show_id, start, ticket, version, presentation, movie_id, capture, movie, listing)`:

| Field | Meaning |
|---|---|
| `venue` | `(venue_id, name, address, city)`; `venue_id` is what the `DataFeed` identifier's `value` names, `None` for single-cinema sites |
| `show_id` | stable across runs: the site's ID, else `stable_key(...)` of what identifies the show |
| `start` | timezone-aware `datetime` in `STOCKHOLM` |
| `ticket` | the booking URL for this screening, else the most specific page |
| `version`, `presentation` | from `facts(format=..., language=..., subtitles=...)`, which reads the site's labels |
| `movie_id` | stable per film on this site |
| `capture` | the file the movie's fields were read from |
| `movie` | the film's fields: build them with `movie_fields`, `film_fields`, `details_fields` or `booking_fields` |
| `listing` | the file, or tuple of files, this screening was read from |

Skip screenings before `today` and duplicates. Read only what the site states: no guessing
a year, a director or a language. Fields are normalised afterwards (`movie_fields.normalise`),
so pass the site's words.

## Register the cinemas

For each cinema the site publishes:

1. A `MovieTheater` in `data/allabiografer/schema/MovieTheater/<name>.jsonld`, unless one
   exists: its own `name`, `containedInPlace` its `City`, `address`, `url`.
2. A `DataFeed` in `data/allabiografer/schema/DataFeed/<name>.jsonld`: `about` the cinema,
   one identifier `{"propertyID": "allabiografer:schedule:<adapter>", "value": "<venue_id>"}`
   (no `value` for single-cinema sites), and `publisher` when an organiser other than the
   cinema publishes it.

See `data/allabiografer/README.md` for naming.

## Try it

```sh
nix run .#run -- --cinema "Roxy Bio"            # download, read and build into the local store
nix run .#trace -- --step "Read roxy.bio" --open  # what the read made of each feed
nix run .#serve                                  # the rendered site on :8000
```

## Test it

```sh
nix run .#fixture -- save roxy_bio      # the newest download in the local store becomes the fixture
nix run .#test -- -k roxy_bio
```

The fixture (`tests/allabiografer/fixtures/sources/<adapter>/`) is the site's pages and the
rows read from them. Every adapter must have one; the tests fail on any change in what the
reader makes of its pages.

## Change a reader

1. `nix run .#pull` to have production's downloads locally.
2. Change the reader. `nix run .#fixture -- diff <adapter>` shows how its rows change on the
   saved pages; `nix run .#run -- --cinema <cinema>` runs it on today's.
3. When the change is intended, `nix run .#fixture -- update <adapter>` and commit the rows
   with the code: the diff of `rows.json.zst` is the review.

A site whose layout changed: `nix run .#fixture -- save <adapter>` after a fresh download
records the new pages.

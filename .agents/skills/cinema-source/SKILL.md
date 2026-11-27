---
name: cinema-source
description: Add or fix an allabiografer.se cinema source: a new adapter for a cinema website, a new cinema on an existing site, or a reader that misreads or stopped reading a site.
---

`src/allabiografer/sources/README.md` is the contract: read it in full first. `roxy_bio` is the reference adapter.

Work in the local store only. `nix run .#pull` copies production's downloads into it; nothing you run touches production.

## New adapter

1. Find where the site's programme comes from: an API the page calls, embedded JSON, or HTML. Prefer the API. Note which requests carry screenings, film details and booking links.
2. Write `__init__.py` (`SITE`), `fetch.py` and `parse.py` (plus `site.py` when they share parsing), copying the structure of the nearest existing adapter.
3. Register each cinema: `MovieTheater` and `DataFeed` under `data/allabiografer/schema/`, as the README says. Run `nix run .#test -- -k registry`.
4. `nix run .#run -- --cinema "<MovieTheater ID>"`, then `nix run .#trace -- --step "Read <SITE>" --open`. Done when every feed shows screenings and a sample checked against the live site matches: date, time, film, language, subtitles, booking link.
5. `nix run .#fixture -- save <adapter>` and `nix run .#test`.

## Fix a reader

1. Reproduce on stored pages: `nix run .#fixture -- diff <adapter>` for the fixture, or a `--cinema` run for today's pages. `nix run .#trace -- --film <slug> --open` shows which file a wrong value came from.
2. Change the reader until the diff shows the fix and nothing else.
3. `nix run .#fixture -- update <adapter>`; when the site's layout changed, `save` after a fresh run instead.
4. `nix run .#test`, `nix run .#lint`, `nix run .#format`.

The fixture's `rows.json.zst` diff is the reviewer's evidence: every changed row is intended.

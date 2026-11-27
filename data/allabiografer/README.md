# allabiografer data

The `allabiografer` package (`src/allabiografer/`) reads and writes this directory.
```text
assets/<sha256>                  raw bytes: HTML, API responses, images
schema/<Schema.org type>/<id>.jsonld
```

The registry is read from this directory. Everything generated (actions, datasets, pages, images) lives in a store, by default this directory. Production is the Cloudflare R2 bucket, read and written directly with immutable objects cached under `.cache/`; commands open it only with `--production`. Object keys are the same paths in both: `schema/<Type>/<id>.jsonld` and `assets/<sha256>`. `nix run .#pull` makes this directory a copy of production, deleting what production lacks; it refuses a bucket without a completed run and never writes to it. Credentials come from `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` and `R2_JURISDICTION`, or `~/.config/allabiografer/r2.env`.

Run `nix run .#run`, optionally limited to the feeds of `-- --cinema <MovieTheater ID>` (repeatable). It prints the `Programme` and the website directory. `--fresh` ignores the previous result; `--render-only` renders the latest result without fetching.

## Registry

Checked in: `MovieTheater`, `DataFeed`, `City`, `AdministrativeArea` (län), and `Country`. IDs are Swedish names; shared cinema names get the locality in parentheses. `containedInPlace` links each cinema to its city, county, and `Country/Sverige.jsonld`. County names and codes are from [SCB](https://www.scb.se/hitta-statistik/regional-statistik-och-kartor/regionala-indelningar/lan-och-kommuner/lan-och-kommuner-i-kodnummerordning/); locality assignments use [GeoNames](https://www.geonames.org/) (CC BY 4.0), with ambiguous names checked against venue locations.

`MovieTheater.url` is the venue or operator's public website, omitted when unknown. `name` is the cinema's own name, without the town prefix ticketing sites add ("Göteborg Hagabion" is Hagabion); the town stays where it is part of the name or of a chain branch's ("Arboga Bio", "Filmstaden Lund"). A former name is kept as `alternateName`; its old page becomes a redirect page.

A `DataFeed` is one published programme. Its `about` is the cinema the screenings take place in; its one `PropertyValue` identifier, `allabiografer:schedule:<adapter>` with the adapter's venue ID, tells fetch and parse where to read it. Each source listing belongs to one feed. Most cinemas have one feed; a cinema whose screenings are also published by an organiser, such as a film society, has one per publisher. Such feeds name the organiser as `publisher`, and their screenings carry it as `organizer`.

The seed comes from parsed captures and adapter configuration, so venues absent from those may be missing. The Finspång calendar source has no verified venue binding.

## Pipeline output

Generated and not checked in. Each run is an action:

| Step | Action | `object` | `result` |
|---|---|---|---|
| `Download <site>` | `DownloadAction` | | `<site> pages`: `Dataset` of `DataDownload`s, `about` the registry feeds |
| `Read <site>` | `CreateAction` | `<site> pages` | `<site> listings`: `Dataset` of `Movie`s and, per feed, a `Dataset` of `ScreeningEvent`s |
| `Look up films on TMDB` | `DownloadAction` | previous `Programme`, new listings | `TMDB answers`: `Dataset` of TMDB responses and checked posters |
| `Build programme` | `CreateAction` | previous `Programme`, new listings, `TMDB answers` | `Programme` |
| `Render allabiografer.se` | `CreateAction` | `Programme`, previous `Published pages` | `www/`, and `Published pages`: every page ever published |

`<site>` is the website an adapter reads, declared as `SITE` in its package: `filmstaden.se`, `bio.se`, `tickster.com`. One download covers every feed of that site. Names are labels; no step reads them.

The run's `result` is the `Programme`. Following `isBasedOn` from it is a waterfall: each link goes one step back, and nothing is repeated that the step before states.

```text
Programme ─▶ <site> listings in effect ─▶ <site> pages (about: DataFeeds, temporalCoverage: day) ─▶ files ─▶ URLs
  #film-…      ─▶ parsed #movie-… ─▶ file ─▶ URL
               ─▶ TMDB responses, checked posters ─▶ URLs
  #screening-… ─▶ parsed #screening-… ─▶ files ─▶ URLs
                    in a per-feed #feed-… Dataset ─▶ DataFeed ─about─▶ MovieTheater
```

A film without screenings is settled: it links the files its records were read from (`DataDownload`s) instead of the records, so listings it no longer needs are pruned, and it stays in every later `Programme`. A film listed again groups with its settled self and keeps its slug.

A `Programme` `Movie`'s `sameAs` keeps the TMDB and IMDb entries that identify it; the source pages it was read from are reached through its parsed records. Each action's `instrument` is the code, and the registry, it ran with.

A listings `Dataset` or `Programme` keeps its parts in one document: its `distribution` is a `DataDownload` of `application/ld+json+zstd` whose `hasPart` holds the `Movie`s, `ScreeningEvent`s and nested per-feed `Dataset`s. Parts carry `#fragment` identifiers and link to each other by them (`"workPresented": {"@id": "#film-…"}`); their links to entities resolve against the `Dataset` entity, and links into another dataset read `../Dataset/<hash>.jsonld#fragment`. Unchanged inputs give the same document and entity, so reruns write only what changed. After a run, `allabiografer.prune` keeps whole runs, newest first, while they fit 9 GB (R2's free tier is 10 GB), and deletes what none of them reach; `--keep N` caps the count. The newest run is always kept, a run still going is never touched, and the registry is never pruned.

A run is an `UpdateAction` named `Update programme` over the previous result (`targetCollection`) for the selected feeds (`object`): download and read per site, look up films on TMDB, then build the programme. Each feed's screenings come from the newest listings covering it, so feeds not run, or whose adapter failed, keep their previous screenings. A show listed by several feeds of one cinema appears once, from the cinema's own feed. Screenings before the run day drop out.

Source `Movie`s pass through `movie_fields.normalise`, so every adapter writes one vocabulary: `genre` from a fixed Swedish list (programme labels such as "Jul" or "Live på bio" drop), `contentRating` as "Barntillåten" or "Från 7/11/15/18 år", `inLanguage` as BCP 47 tags, `duration` in minutes, people as `Person`s and trailers as `VideoObject`s. Unrated and implausible values drop.

Sources that state a TMDB or IMDb identity carry it in `sameAs`; matching treats a shared identity as the same film and different ones as different films. Showing films missing a poster, description or director are looked up on TMDB: by stated identity, else as in merging. Search results in Swedish and English whose title matches are one work, split where year, director, plot or runtime contradict the listing. A single namesake left standing is the film; among several, the one whose year, director, plot, exact runtime or original language agrees. TMDB fills missing properties only. `TMDB answers` holds every response and source poster the lookups used; building the programme replays it and reads nothing else. The token is read from `TMDB_ACCESS_TOKEN` or `~/.config/allabiografer/tmdb-token`. A TMDB failure is reported; the programme is then built without answers and films stay as their sources state them.

A poster is an image at least 200 px wide and 1.2 times taller than wide; stills, banners and placeholders are dropped, and TMDB fills the gap. Bioguiden's listing thumbnails are 150x90 banners, so its poster is taken from the film page's gallery with the dark canvas cropped off; the gallery serves the real image only with the film page as referrer.

Each `Movie` in a `Programme` has a stable slug, its `allabiografer:film` identifier, and `url` `https://allabiografer.se/film/<slug>/`. Grouping is re-evaluated every run. A group reuses the oldest identity among its members, slugs are never reassigned, and slugs of joined films remain as `allabiografer:film-alias`.

Actions record `startTime`, `endTime`, `actionStatus`, and `error` for failures. Problems never cost data:

- a failing site does not stop the others, and its feeds keep their previous screenings;
- a feed read empty keeps the screenings it listed before; one that loses more than half of ten or more is reported;
- without TMDB, films keep the answers that filled them before;
- a run with problems prunes nothing.

The run then exits non-zero. In CI the site still deploys, and the problems are filed in one open issue, *Programme update problems*, which the next clean scheduled run closes.

Entities other than actions are named by the SHA-256 of their content, so identical outputs are shared between runs. Links are relative paths.

`DataDownload` and `ImageObject` describe stored bytes. `contentUrl` is an [RFC 6920](https://www.rfc-editor.org/rfc/rfc6920) `ni:///sha-256;…` URI. `sha256` names the file under `assets/`. Bytes are zstd-compressed when that saves at least 10%; `encodingFormat` then carries the registered `+zstd` suffix, e.g. `text/html+zstd`.

`ScreeningEvent` links `workPresented` to a `Movie` and `location` to a registry `MovieTheater`. `inLanguage` and `subtitleLanguage` are BCP 47 tags; an empty `subtitleLanguage` means the source states there are none. `videoFormat` lists picture and sound formats, in display order: `2D`, `3D`, `IMAX`, `Dolby Cinema`, `4DX`, `ScreenX`, `D-Box`, `iSense`, `Infinity Vision`, `4K`, `Laser`, `Dolby Atmos`, `35 mm`, `70 mm`. Schema.org has no sound format on a screening, so `Dolby Atmos` is listed there too.

Each action's `instrument` is a `SoftwareSourceCode` entity naming the module it ran. That module is `isPartOf` a snapshot of all pipeline code. The snapshot records the git commit as `version`, suffixed `-dirty` when the source files differ from it. Its `encoding` is a deterministic tar of `src/allabiografer/`, `pyproject.toml`, `uv.lock` and the registry under `data/allabiografer/schema/`, stored as an asset, so a run can be traced to the exact bytes it executed and the registry it read, even when uncommitted or since edited.

## Website

`www/` is the allabiografer.se site rendered from the latest `Programme`, regenerated on every run and not checked in. `src/allabiografer/site/` holds the page code, templates, styles, scripts and fonts; `render.py` translates the `Programme` into its page data. Each programme has an `index.md` and an `index.jsonld`. Former film and cinema slugs are static redirect pages: a meta refresh, a canonical link to the new address, `noindex`, and a script that keeps the URL fragment.

Every film has a page, its screenings when it has any; a city lists a film while it shows there. Every page published stays reachable. A render's result lists, as `WebPage` parts, every path it served and every path the render before had listed. A listed path no longer served gets a redirect page to its nearest live page: a city's film page to the film's page, a genre page to the genre's current name or the city, a cinema or genre page to its city, the rest to the home page. Only rendered pages enter the sitemap.

Posters are downloaded into the store once; render crops and resizes them to WebP at 104, 125, 250 and 500 px directly into `www/posters/`.

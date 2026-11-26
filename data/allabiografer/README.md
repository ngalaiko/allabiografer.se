# allabiografer data

The `allabiografer` package (`src/allabiografer/`) reads and writes this directory. It shares no code with the `parse`, `store`, and `build` packages.

```text
assets/<sha256>                  raw bytes: HTML, API responses, images
schema/<Schema.org type>/<id>.jsonld
```

Run `uv run --group parse --group build allabiografer`, optionally limited with `--cinema <MovieTheater ID>` (repeatable). It prints the merged `Dataset` and the website directory. `--fresh` ignores the previous result; `--render-only` renders the latest result without fetching.

## Registry

Checked in: `MovieTheater`, `City`, `AdministrativeArea` (län), and `Country`. IDs are Swedish names; shared cinema names get the locality in parentheses. `containedInPlace` links each cinema to its city, county, and `Country/Sverige.jsonld`. County names and codes are from [SCB](https://www.scb.se/hitta-statistik/regional-statistik-och-kartor/regionala-indelningar/lan-och-kommuner/lan-och-kommuner-i-kodnummerordning/); locality assignments use [GeoNames](https://www.geonames.org/) (CC BY 4.0), with ambiguous names checked against venue locations.

`MovieTheater.url` is the venue or operator's public website, omitted when unknown. Each cinema has one `PropertyValue` identifier: `allabiografer:schedule:<adapter>` with the adapter's venue ID, shared by fetch and parse.

The seed comes from parsed captures and adapter configuration, so venues absent from those may be missing. The Finspång calendar source has no verified venue binding.

## Pipeline output

Generated and not checked in. Each run is an action:

| Step | Action | `object` | `result` |
|---|---|---|---|
| fetch | `DownloadAction` | registry cinemas | `Dataset` of `DataDownload`s |
| parse | `CreateAction` | fetch `Dataset` | `Dataset` of `Movie`s and `ScreeningEvent`s |
| merge | `CreateAction` | previous merged `Dataset`, new parse `Dataset`s | merged `Dataset` |
| render | `CreateAction` | merged `Dataset` | `www/` |

A run is an `UpdateAction` over the previous result (`targetCollection`) for the selected cinemas (`object`): fetch and parse per adapter, then one merge. Each cinema's screenings come from the newest parse covering it, so cinemas not run, or whose adapter failed, keep their previous screenings. Screenings before the run day drop out.

Each `Movie` in a merged `Dataset` has a stable slug, its `allabiografer:film` identifier, and `url` `https://allabiografer.se/film/<slug>/`. Grouping is re-evaluated every run. A group reuses the oldest identity among its members, slugs are never reassigned, and slugs of joined films remain as `allabiografer:film-alias`.

Actions record `startTime`, `endTime`, `actionStatus`, and `error` for failures. A failing adapter does not stop the others; the run exits non-zero after merging.

Entities other than actions are named by the SHA-256 of their content, so identical outputs are shared between runs. Links are relative paths.

`DataDownload` and `ImageObject` describe stored bytes. `contentUrl` is an [RFC 6920](https://www.rfc-editor.org/rfc/rfc6920) `ni:///sha-256;…` URI. `sha256` names the file under `assets/`. Bytes are zstd-compressed when that saves at least 10%; `encodingFormat` then carries the registered `+zstd` suffix, e.g. `text/html+zstd`.

`ScreeningEvent` links `workPresented` to a `Movie` and `location` to a registry `MovieTheater`. `inLanguage` and `subtitleLanguage` are BCP 47 tags; an empty `subtitleLanguage` means the source states there are none. `videoFormat` lists picture and projection formats only: `2D`, `3D`, `IMAX`, `Dolby Cinema`, `4DX`, `ScreenX`, `35 mm`, `70 mm`.

A merged `Movie` lists its source records in `isBasedOn`.

Each action's `instrument` is a `SoftwareSourceCode` entity naming the module it ran. That module is `isPartOf` a snapshot of all pipeline code. The snapshot records the git commit as `version`, suffixed `-dirty` when the source files differ from it. Its `encoding` is a deterministic tar of `src/allabiografer/`, `pyproject.toml`, and `uv.lock`, stored as an asset, so a run can be traced to the exact bytes it executed even when uncommitted.

## Website

`www/` is the allabiografer.se site rendered from the latest merged `Dataset`, regenerated on every run and not checked in. Rendering is v1's: `src/allabiografer/site/` holds copies of `src/build`'s page code, templates, styles, scripts and fonts, so the pages look the same. `render.py` only translates the merged graph into v1's page data. Each programme has an `index.md` and an `index.jsonld`; there are no iCalendar feeds or festival pages.

Posters are cropped and resized to v1's WebP widths and stored as `ImageObject`s in `assets/`; source URLs are downloaded into the store first. `www/posters/` holds symlinks to those assets, so image bytes are stored once; a deploy must copy them as files.

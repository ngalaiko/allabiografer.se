# Data

```text
assets/<sha256>                  raw bytes: HTML, API responses, images
schema/<Schema.org type>/<id>.jsonld
```

Run `python -m v2.pipeline --all`, or pass cinema IDs (`MovieTheater` filename stems). The command prints the merged `Dataset`.

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
| merge | `CreateAction` | parse `Dataset`s | merged `Dataset` |

Actions record `startTime`, `endTime`, `actionStatus`, and `error` for failures. A failing adapter does not stop the others; the run exits non-zero after merging the rest.

Entities other than actions are named by the SHA-256 of their content, so identical outputs are shared between runs. Links are relative paths.

`DataDownload` and `ImageObject` describe stored bytes. `contentUrl` is an [RFC 6920](https://www.rfc-editor.org/rfc/rfc6920) `ni:///sha-256;…` URI. `sha256` names the file under `assets/`. Bytes are zstd-compressed when that saves at least 10%; `encodingFormat` then carries the registered `+zstd` suffix, e.g. `text/html+zstd`.

`ScreeningEvent` links `workPresented` to a `Movie` and `location` to a registry `MovieTheater`. `inLanguage` and `subtitleLanguage` are BCP 47 tags; an empty `subtitleLanguage` means the source states there are none. `videoFormat` lists picture and projection formats only: `2D`, `3D`, `IMAX`, `Dolby Cinema`, `4DX`, `ScreenX`, `35 mm`, `70 mm`.

Merge reconciles movies across sources: a merged `Movie` lists its source records in `isBasedOn`.

Each action's `instrument` is a `SoftwareSourceCode` entity naming the module it ran. That module is `isPartOf` a snapshot of all pipeline code. The snapshot records the git commit as `version`, suffixed `-dirty` when the source files differ from it. Its `encoding` is a deterministic tar of `v2/`, `src/`, `pyproject.toml`, and `uv.lock`, stored as an asset, so a run can be traced to the exact bytes it executed even when uncommitted.

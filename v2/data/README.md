# Cinema registry

Store JSON-LD as `schema/<Schema.org type>/<id>.jsonld`, relative to this directory or a job's output directory. Registry IDs use Swedish names; disambiguate shared cinema names with the locality in parentheses. Use relative, URL-encoded links.

`containedInPlace` connects `MovieTheater` → `City` → `AdministrativeArea` (län) → `Country/Sverige.jsonld`. County names and codes are from [SCB](https://www.scb.se/hitta-statistik/regional-statistik-och-kartor/regionala-indelningar/lan-och-kommuner/lan-och-kommuner-i-kodnummerordning/). Locality assignments use [GeoNames](https://www.geonames.org/) (CC BY 4.0), with ambiguous names checked against venue locations.

Use `MovieTheater.url` for the venue or operator’s public website. Omit it when unknown; do not substitute a ticketing or scraper URL. Initial links come from published venue pages, Bio.se’s website field, and Bioguiden’s venue homepage links.

The seed comes from the latest local parse catalogue for each source with saved output, plus Filmhuset Palladium from its adapter. Snapshot coverage is not exhaustive: venues without screenings in those captures may be absent. The Finspång calendar source has no verified venue binding.

Parse and merge jobs index their output at `schema/Dataset/catalogue.jsonld`. Replay raw captures from `fetch/` to regenerate older parse outputs in this layout.

Each cinema has one `PropertyValue` identifier: `propertyID` is `allabiografer:schedule:<adapter>` and `value` is the adapter’s stable venue ID, shared by fetch and parse. The adapter translates between that ID and any upstream API parameters. Parse uses source-local filenames; merge prefixes cinema filenames with the adapter from `propertyID`.

Run `python -m v2.fetch 'Ale Medborgarhusets Bio'` (repeat cinema IDs as needed) or `python -m v2.fetch --all`. IDs are `MovieTheater` filename stems. Parse the printed fetch directory with the corresponding adapter. Each source's `selection.json` records the bindings for replay. Nortic provides one shared feed; its parser keeps only selected venues.

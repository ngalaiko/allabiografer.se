# Cinema registry

Store JSON-LD as `schema/<Schema.org type>/<id>.jsonld`, relative to this directory or a job's output directory. Registry IDs use Swedish names; disambiguate shared cinema names with the locality in parentheses. Use relative, URL-encoded links.

`containedInPlace` connects `MovieTheater` → `City` → `AdministrativeArea` (län) → `Country/Sverige.jsonld`. County names and codes are from [SCB](https://www.scb.se/hitta-statistik/regional-statistik-och-kartor/regionala-indelningar/lan-och-kommuner/lan-och-kommuner-i-kodnummerordning/). Locality assignments use [GeoNames](https://www.geonames.org/) (CC BY 4.0), with ambiguous names checked against venue locations.

Use `MovieTheater.url` for the venue or operator’s public website. Omit it when unknown; do not substitute a ticketing or scraper URL. Initial links come from published venue pages, Bio.se’s website field, and Bioguiden’s venue homepage links.

Each cinema `identifier` is a `PropertyValue`: `propertyID` names the source adapter and `value` is the source-local venue ID (the parsed cinema filename without `.jsonld`). The pair identifies at most one cinema. The venue ID is not necessarily a fetch selector.

The seed comes from the latest local parse catalogue for each source with saved output, plus Filmhuset Palladium from its adapter. Snapshot coverage is not exhaustive: venues without screenings in those captures may be absent. The Finspång calendar source has no verified venue binding.

Parse and merge jobs index their output at `schema/Dataset/catalogue.jsonld`. Replay raw captures from `fetch/` to regenerate older parse outputs in this layout.

TODO: Wire the registry into the pipeline commands.

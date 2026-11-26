# Cinema geography in Schema.org

Keep the postal address separate from the geographic hierarchy:

```text
MovieTheater ── address ──► PostalAddress
     │
     └── containedInPlace ──► City ── containedInPlace ──► AdministrativeArea (län)
                                                               │
                                                               └── containedInPlace ──► Country
```

[`MovieTheater`](https://schema.org/MovieTheater) is a `Place` via `CivicStructure`. [`City`](https://schema.org/City) and [`Country`](https://schema.org/Country) are administrative areas, which are places. [`containedInPlace`](https://schema.org/containedInPlace) connects places; [`address`](https://schema.org/address) describes a physical address.

| `PostalAddress` property | Expected values | Use |
| --- | --- | --- |
| [`addressLocality`](https://schema.org/addressLocality) | `Text` | Postal locality, such as `Skövde` |
| [`addressRegion`](https://schema.org/addressRegion) | `AdministrativeArea` or `Text` | Optional link to the län |
| [`addressCountry`](https://schema.org/addressCountry) | `Country` or `Text` | `SE` (recommended ISO code) or a link to Sverige |

The expected types are declared in the [official machine-readable vocabulary](https://schema.org/version/latest/schemaorg-current-https.jsonld). `City` is a subtype of `AdministrativeArea`, but using it as `addressRegion` would describe the region, not the postal locality. Giving [`PostalAddress`](https://schema.org/PostalAddress) a file and an ID makes the address reusable, but does not turn it into a `Place` or add a locality link.

If several venues share a building worth representing, add a [`Place`](https://schema.org/Place) for the building. Use `MovieTheater → containedInPlace → Place → containedInPlace → City`, with `Place.address` holding the building's postal address. Skip that node when the cinema itself is the physical place.

"""BioSverige (Videvox Cinecore) cinema sites — per-site schedule API."""

from dataclasses import dataclass


@dataclass(frozen=True)
class _Site:
    url: str
    name: str
    city: str
    address: str
    # The site's "@booking" setting: where its buy buttons lead.
    tickets: str
    # Tickster organiser listing with one event per showing.
    programme: str = ""


# Söderköping has its own parser; Vårgårda Rialto and Robertsfors are on bio.se.
_SITES = (
    _Site(
        "https://filipstad.biosverige.se",
        "Bio Monitor",
        "Filipstad",
        "Viktoriagatan 8",
        "https://secure.tickster.com/sv/y4vknkelzhvmpp6/",
        "https://www.tickster.com/se/sv/events/by/ukh54uat4kwp0b4/bio-monitor",
    ),
    _Site(
        "https://jarpen.biosverige.se",
        "Järpen Bion",
        "Järpen",
        "Strandvägen 22",
        "https://www.tickster.com/se/sv/events/by/t93wpddl1nc93uz/jarpen-bion",
        "https://www.tickster.com/se/sv/events/by/t93wpddl1nc93uz/jarpen-bion",
    ),
    _Site(
        "https://gislaved.biosverige.se",
        "Folkets Hus Gislaved",
        "Gislaved",
        "Danska vägen 6 A",
        "https://boka.folketshusgislaved.se/gislaved/resource/movies",
    ),
    _Site(
        "https://casablancabio.se",
        "Bio Casablanca",
        "Karlsborg",
        "Strandvägen 15",
        "https://secure.tickster.com/sv/eaukgpvmklav5gg",
        "https://www.tickster.com/se/sv/events/by/fer7uddjdxuaa8u/bio-casablanca",
    ),
    _Site(
        "https://mariannelundsbio.se",
        "Mariannelunds Bio",
        "Mariannelund",
        "Östra Storgatan 6",
        "https://secure.tickster.com/sv/fjnrhjm4dltbtfl",
        "https://www.tickster.com/se/sv/events/by/jdg9ek45zlh6xtu/mariannelunds-bio",
    ),
    # No "@booking" setting.
    _Site(
        "https://smedjebacken.biosverige.se",
        "Folkets Hus Smedjebacken",
        "Smedjebacken",
        "Vasagatan 11",
        "https://smedjebacken.biosverige.se",
    ),
)

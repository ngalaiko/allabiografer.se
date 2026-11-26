import json
import re
from urllib.parse import quote, unquote, urlsplit

from allabiografer.graph import DATA

SCHEMA = DATA / "schema"
CONTEXT = "https://schema.org"


def read_entity(path, kind):
    entity = json.loads(path.read_bytes())
    assert entity["@context"] == CONTEXT
    assert entity["@id"] == ""
    assert entity["@type"] == kind
    assert entity["name"].strip()
    return entity


def container(path, entity):
    iri = entity["containedInPlace"]["@id"]
    relative_path = unquote(iri)
    assert iri == quote(relative_path)
    return (path.parent / relative_path).resolve()


def test_registry_links_and_source_identifiers():
    counties = set((SCHEMA / "AdministrativeArea").glob("*.jsonld"))
    cities = set((SCHEMA / "City").glob("*.jsonld"))
    cinemas = set((SCHEMA / "MovieTheater").glob("*.jsonld"))
    assert len(counties) == 21
    assert cities
    assert cinemas

    country = SCHEMA / "Country" / "Sverige.jsonld"
    assert read_entity(country, "Country")["name"] == country.stem
    codes = set()
    for path in counties:
        entity = read_entity(path, "AdministrativeArea")
        assert path.stem == entity["name"]
        assert container(path, entity) == country
        identifier = entity["identifier"]
        assert identifier["@type"] == "PropertyValue"
        assert identifier["propertyID"] == "SCB länskod"
        codes.add(identifier["value"])
    assert len(codes) == len(counties)

    for path in cities:
        entity = read_entity(path, "City")
        assert path.stem == entity["name"]
        assert container(path, entity) in counties

    for path in cinemas:
        entity = read_entity(path, "MovieTheater")
        # IDs disambiguate shared names with the locality; names are as displayed.
        assert "(" not in entity["name"], path
        assert container(path, entity) in cities
        address = entity["address"]
        assert address["@type"] == "PostalAddress"
        assert address["addressCountry"] == "SE"
        assert address["streetAddress"].strip(), path
        if "addressLocality" in address:
            assert isinstance(address["addressLocality"], str), path
            assert address["addressLocality"].strip(), path
        if "postalCode" in address:
            assert re.fullmatch(r"[1-9][0-9]{2} [0-9]{2}", address["postalCode"]), path
        if "url" in entity:
            url = urlsplit(entity["url"])
            assert url.scheme in {"http", "https"}, path
            assert url.hostname, path
            assert not any(char.isspace() for char in entity["url"]), path
        # How a programme is collected belongs to its DataFeed, not the cinema.
        assert "identifier" not in entity, path

    covered = set()
    for path in (SCHEMA / "DataFeed").glob("*.jsonld"):
        entity = read_entity(path, "DataFeed")
        cinema = (path.parent / unquote(entity["about"]["@id"])).resolve()
        assert cinema in cinemas, path
        assert "(" not in entity["name"], path
        covered.add(cinema)
        identifier = entity["identifier"]
        assert identifier["@type"] == "PropertyValue"
        assert identifier["propertyID"].startswith("allabiografer:schedule:"), path
        if "publisher" in entity:
            assert entity["publisher"]["@type"] == "Organization"
            assert entity["publisher"]["name"].strip(), path
    assert covered == cinemas

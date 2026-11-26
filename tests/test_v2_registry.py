import json
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

SCHEMA = Path(__file__).resolve().parents[1] / "v2" / "data" / "schema"
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

    bindings = set()
    for path in cinemas:
        entity = read_entity(path, "MovieTheater")
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
        assert entity["identifier"], path
        for identifier in entity["identifier"]:
            assert identifier["@type"] == "PropertyValue"
            key = (identifier["propertyID"], identifier["value"])
            assert all(part.strip() for part in key), path
            assert key not in bindings, key
            bindings.add(key)

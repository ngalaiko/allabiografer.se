import pytest

from allabiografer.schedule import Feed, feeds


def test_registry_feeds_route_to_cinemas():
    all_feeds = feeds()
    assert all_feeds["Biocafé Tellus"].venue_id == "5abe9f74b43fc5a465bff57e"
    assert all_feeds["Aveny Ludvika"].venue_id == "ncg23111"
    assert all_feeds["Biostaden Eskilstuna"].venue_id == "3"
    assert all_feeds["Cinemascenen (Hudiksvall)"].venue_id == "hudiksvall"
    assert all_feeds["Ale Medborgarhusets Bio"] == Feed(
        "Ale Medborgarhusets Bio", "Ale Medborgarhusets Bio", "bio_se", "16484"
    )
    assert all_feeds["Bio Rio"] == Feed("Bio Rio", "Bio Rio", "biorio_se", None)
    # Organisers publishing their own programme are further feeds of the cinema they screen in.
    assert all_feeds["Arboga Bio Kontrast"] == Feed("Arboga Bio Kontrast", "Arboga Bio", "bio_se", "48734")
    assert all_feeds["Skövde Filmfestival"].cinema == all_feeds["Biograf Odeon"].cinema == "Biograf Odeon"
    assert all_feeds["Biograf Odeon"].adapter == "kulturiskovde_se"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_missing_duplicate_or_dangling_feeds_are_rejected(tmp_path):
    write(tmp_path / "schema" / "MovieTheater" / "Biograf.jsonld", "{}")
    feed = tmp_path / "schema" / "DataFeed" / "Biograf.jsonld"
    write(feed, '{"about": {"@id": "../MovieTheater/Biograf.jsonld"}}')
    with pytest.raises(ValueError, match="expected one schedule identifier"):
        feeds(tmp_path)

    identifier = '"identifier": {"propertyID": "allabiografer:schedule:bio_se", "value": "42"}'
    write(feed, '{"about": {"@id": "../MovieTheater/Biograf.jsonld"}, ' + identifier + "}")
    write(feed.with_name("Annan.jsonld"), feed.read_text())
    with pytest.raises(ValueError, match="duplicate schedule identifier"):
        feeds(tmp_path)

    feed.with_name("Annan.jsonld").unlink()
    write(feed, '{"about": {"@id": "../MovieTheater/Saknas.jsonld"}, ' + identifier + "}")
    with pytest.raises(ValueError, match="about must be a registry MovieTheater"):
        feeds(tmp_path)

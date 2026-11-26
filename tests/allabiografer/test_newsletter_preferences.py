import json

from allabiografer.site.pages import SiteData, _write_newsletter_cities


def test_newsletter_city_allowlist_contains_every_current_city(tmp_path):
    sd = SiteData(out_dir=tmp_path, cities={"Göteborg": 10, "Åmål": 0, "Örnsköldsvik": 2})
    _write_newsletter_cities(sd)
    assert json.loads((tmp_path / "i/newsletter-cities.json").read_text()) == {
        "Göteborg": "newsletter-city-goteborg",
        "Åmål": "newsletter-city-amal",
        "Örnsköldsvik": "newsletter-city-ornskoldsvik",
    }

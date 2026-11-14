"""Bioguiden — selected cinema programmes not supplied by our other sources."""

import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, time
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from parse import _http
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

_SOURCE = "bioguiden_se"
_BASE = "https://www.bioguiden.se/"
# Verified programmes missing from other sources. Reuse existing Bio.se venue names.
# Municipality IDs do not necessarily name the cinema's town (e.g. Bollnäs / Arbrå).
_SITES = {
    _BASE + "biografer.aspx?cityid=185&theatreid=d980609d-d35b-46b7-9012-c5d2bb5b5692": Venue(
        name="Medborgarhus Bio", city="Lycksele", address="Norra Torggatan 14"
    ),
    _BASE + "biografer.aspx?cityid=11&theatreid=4395ab77-fc3f-4da5-9e62-cd6ddea0cf1d": Venue(
        name="Leksand Visir Bio", city="Leksand", address="Faluvägen 16"
    ),
    _BASE + "biografer.aspx?cityid=79&theatreid=258bc339-0589-422c-8ee7-b13a977332e5": Venue(
        name="Arjeplog Centrumbion", city="Arjeplog", address="Storgatan 4"
    ),
    _BASE + "biografer.aspx?cityid=22&theatreid=f459e791-a5e7-4567-b2cd-8a5a0cb5ca3e": Venue(
        name="Arbrå Saga Bio", city="Arbrå", address="Bondegatan 51"
    ),
    _BASE + "biografer.aspx?cityid=184&theatreid=9c8a50dc-28b9-463c-a0e1-660cbcad7765": Venue(
        name="Medborgarhuset", city="Dorotea", address="Byvägen 5"
    ),
    _BASE + "biografer.aspx?cityid=170&theatreid=d5c074d7-ed02-49ee-92e9-39a5e020a9f3": Venue(
        name="Forshaga Folkets Hus Bio", city="Forshaga", address="Vinkelgatan 18"
    ),
    _BASE + "biografer.aspx?cityid=49&theatreid=8ffb8ddf-ac9d-4ea5-904e-691e5ba7c3bd": Venue(
        name="Hammargårdens Bio", city="Gnosjö", address="Läroverksgatan 2"
    ),
    _BASE + "biografer.aspx?cityid=267&theatreid=7ba5c5ab-c2dd-4378-a413-1ab71098ed1e": Venue(
        name="Hallsberg Spektrum Bio", city="Hallsberg", address="Södra Allén 14"
    ),
    _BASE + "biografer.aspx?cityid=268&theatreid=bcba08dc-479f-458a-964e-048f5ffc74a6": Venue(
        name="Hällefors Folkets Hus Bio", city="Hällefors", address="Sikforsvägen 19-21"
    ),
    _BASE + "biografer.aspx?cityid=84&theatreid=b1442452-d0f5-468e-b07e-76f4ee9d3e70": Venue(
        name="Folkets Hus Bio", city="Jokkmokk", address="Föreningsgatan 8"
    ),
    _BASE + "biografer.aspx?cityid=84&theatreid=3a7f62b6-565e-4092-98a7-d1926545bd4a": Venue(
        name="Folkets Hus Bio", city="Vuollerim", address="Älvvägen 4 A"
    ),
    _BASE + "biografer.aspx?cityid=176&theatreid=02127f66-cf4a-4481-8589-06b217f0b94d": Venue(
        name="Kristinehamns Bio", city="Kristinehamn", address="Broängsgatan 3"
    ),
    _BASE + "biografer.aspx?cityid=270&theatreid=abf2587c-c7ad-45da-81b0-a741bba9ce8f": Venue(
        name="Kumla Folkets Hus", city="Kumla", address="Skolvägen 10"
    ),
    _BASE + "biografer.aspx?cityid=240&theatreid=02bc06b8-f892-466d-8a32-9a3810bbd97a": Venue(
        name="Mellerud Centrumsalongen", city="Mellerud", address="Änggatan 2"
    ),
    _BASE + "biografer.aspx?cityid=188&theatreid=c1306d3f-748d-4c80-abe8-3fd55e21e2c0": Venue(
        name="Norsjö Folkets Hus", city="Norsjö", address="Nygatan 32"
    ),
    _BASE + "biografer.aspx?cityid=88&theatreid=a7924d72-3a81-4508-b305-961ce0978f5c": Venue(
        name="Folkets Hus Bio", city="Pajala", address="Fridhemsvägen 1"
    ),
    _BASE + "biografer.aspx?cityid=178&theatreid=50c3c0f9-4343-4d25-b668-201379efba8d": Venue(
        name="Storfors Biograf", city="Storfors", address="Centrumplan 1"
    ),
    _BASE + "biografer.aspx?cityid=192&theatreid=3ddb5f48-50db-4519-9857-5dc7d9564ba0": Venue(
        name="Folkets Hus Bio", city="Storuman", address="Blåvägen 256"
    ),
    _BASE + "biografer.aspx?cityid=179&theatreid=101e2089-ebab-47c0-b52c-7b3f9d6dfa27": Venue(
        name="Teaterbiografen", city="Sunne", address="Kvarngatan 22"
    ),
    _BASE + "biografer.aspx?cityid=253&theatreid=4580d9d7-a670-4d7d-890b-e58c6af5296b": Venue(
        name="Saga", city="Tidaholm", address="Nya Torget"
    ),
    _BASE + "biografer.aspx?cityid=75&theatreid=6bdb924a-efa0-445f-9fde-209e2ec82215": Venue(
        name="Bio Konga Folkets Hus", city="Konga", address="Ronnebyvägen 8"
    ),
    _BASE + "biografer.aspx?cityid=56&theatreid=9303801f-942a-4fb6-8412-877a659fa706": Venue(
        name="Centrum", city="Vaggeryd", address="Götaforsvägen 8"
    ),
    _BASE + "biografer.aspx?cityid=286&theatreid=be807e6a-4d48-4eda-a13b-a9150ad10ac5": Venue(
        name="Folkan", city="Gusum", address="Furuvägen 3-5"
    ),
    _BASE + "biografer.aspx?cityid=160&theatreid=bd8c85ee-879c-447e-9dc6-abcbbd73cf76": Venue(
        name="Vingåkers Bio", city="Vingåker", address="Storgatan 56"
    ),
    _BASE + "biografer.aspx?cityid=196&theatreid=5ec56f94-393c-40bd-8a7d-a14b2117d543": Venue(
        name="Medborgarhus Bio", city="Vännäs", address="Östra Järnvägsgatan 10"
    ),
    _BASE + "biografer.aspx?cityid=197&theatreid=76ef241c-4949-4f74-ad72-15f1b8254f3b": Venue(
        name="Bion i Åsele", city="Åsele", address="Lillgatan 2"
    ),
    _BASE + "biografer.aspx?cityid=20&theatreid=918e44a5-fadd-49b6-9d74-cfe13a88c5a2": Venue(
        name="Älvdalens Bio", city="Älvdalen", address="Dalgatan 104"
    ),
    _BASE + "biografer.aspx?cityid=91&theatreid=df7b68d4-44d9-4d99-b508-e4bf79b1444b": Venue(
        name="Överkalix Bio", city="Överkalix", address="Bulandsgatan 2"
    ),
    _BASE + "biografer.aspx?cityid=92&theatreid=eabbcf94-51a7-416e-b302-cd85be9a6955": Venue(
        name="Folkets Hus Bio", city="Övertorneå", address="Sockenvägen 1"
    ),
    _BASE + "biografer.aspx?cityid=71&theatreid=3c855571-dbfd-4520-98a6-473e8ee8b6a5": Venue(
        name="Moheda Bio", city="Moheda", address="Banérsgatan 3"
    ),
    _BASE + "biografer.aspx?cityid=46&theatreid=fede9b30-79e9-428e-b04e-f51e9b55d06b": Venue(
        name="Konserthus Bio", city="Aneby", address="Konserthusgatan 15"
    ),
    _BASE + "biografer.aspx?cityid=38&theatreid=b7de2f89-10fb-4df9-990e-53090d0ba261": Venue(
        name="Hoverbergs Bio", city="Svenstavik", address="Hoverberg 211"
    ),
    _BASE + "biografer.aspx?cityid=81&theatreid=20cc1667-0638-4ec6-9f16-e6cf70448995": Venue(
        name="Gunnarsbyn Saga Bio", city="Gunnarsbyn", address="Lingonvägen 6"
    ),
    _BASE + "biografer.aspx?cityid=39&theatreid=6c06882c-0599-4778-b38f-75103e1e2248": Venue(
        name="Norden Bio", city="Kälarne", address="Södervägen 4"
    ),
    _BASE + "biografer.aspx?cityid=168&theatreid=ba937ef7-670f-474a-89f8-96fc61d8782f": Venue(
        name="Folkets Hus Bio", city="Åmotfors", address="Älvuddsgatan 21"
    ),
    _BASE + "biografer.aspx?cityid=60&theatreid=8924df42-3f99-4709-85e2-d500eabbb641": Venue(
        name="Vissefjärda Bio", city="Vissefjärda", address="Storgatan 31"
    ),
    _BASE + "biografer.aspx?cityid=32&theatreid=f9b754c2-db3f-4c2f-9dd5-f90cf8fd26f9": Venue(
        name="Ullareds Bygdegård", city="Ullared", address="Skolvägen 12"
    ),
    _BASE + "biografer.aspx?cityid=8&theatreid=6816f0f7-bc01-47f5-88b9-182f8f164b55": Venue(
        name="Bjursås Bio", city="Bjursås", address="Skovägen 31"
    ),
    _BASE + "biografer.aspx?cityid=8&theatreid=5a033ac9-f50d-44c2-a312-b9371af0f97b": Venue(
        name="Kulturstöten Bio", city="Falun", address="Teatergatan 3"
    ),
    _BASE + "biografer.aspx?cityid=21&theatreid=5a91bee1-9695-4fd9-abc3-7e0dc2edba9a": Venue(
        name="Bergmancenter", city="Fårö", address="Svens 1118"
    ),
    _BASE + "biografer.aspx?cityid=21&theatreid=7ed28fdb-6dff-4075-9eef-959f3b62bc51": Venue(
        name="Östergarns Bio", city="Katthammarsvik", address="Bygdegården Östergarn"
    ),
    _BASE + "biografer.aspx?cityid=227&theatreid=c12ff623-32f1-41a8-9288-c215cc1de994": Venue(
        name="Sankt Jörgen Park Biografen", city="Göteborg", address="Knipplekullen 8"
    ),
    _BASE + "biografer.aspx?cityid=227&theatreid=c02545f8-6088-4cae-a107-43190c1322dd": Venue(
        name="Göteborg Bio Vingen Torslanda", city="Göteborg", address="Amhults Torg 7"
    ),
    _BASE + "biografer.aspx?cityid=208&theatreid=ebb89ac0-28ed-470a-8816-3b7e60702251": Venue(
        name="Heby Folkets Hus", city="Heby", address="Centralgatan 1"
    ),
    _BASE + "biografer.aspx?cityid=61&theatreid=78cbe22c-d8f2-4cb4-96ca-ded23b90ee5f": Venue(
        name="Virserums Bio", city="Virserum", address="Storgatan 72"
    ),
    _BASE + "biografer.aspx?cityid=40&theatreid=6093fefc-2074-4096-8a7c-6c26f9deb14f": Venue(
        name="Ytterhogdal Folkets Hus Bio", city="Ytterhogdal", address="Hogdalsvägen 3"
    ),
    _BASE + "biografer.aspx?cityid=40&theatreid=64ae3d67-796c-45c3-956f-f88fb1ac55d9": Venue(
        name="Sveg Cinema", city="Sveg", address="Ljusnegatan 1"
    ),
    _BASE + "biografer.aspx?cityid=40&theatreid=e09bdd62-9127-4126-a89c-88867c30243f": Venue(
        name="Vemdals Bio", city="Vemdalen", address="Centrumgatan 20"
    ),
    _BASE + "biografer.aspx?cityid=100&theatreid=957fd843-c879-4359-a62b-7cbfe079e65b": Venue(
        name="Saga", city="Höganäs", address="Köpmansgatan 2"
    ),
    _BASE + "biografer.aspx?cityid=101&theatreid=a2eb58c9-809b-4f51-8d11-d07a60989109": Venue(
        name="Bio Sågen", city="Hörby", address="Svensköp 6518"
    ),
    _BASE + "biografer.aspx?cityid=51&theatreid=f8f0b250-6768-430b-98fc-f3b3b13fa1c3": Venue(
        name="Gränna Grenna Bio", city="Gränna", address="Torget"
    ),
    _BASE + "biografer.aspx?cityid=51&theatreid=ebc80e13-ad8e-4440-9683-fef6dace89e6": Venue(
        name="Visingsö Ö-bion", city="Visingsö", address="Vrixlösa"
    ),
    _BASE + "biografer.aspx?cityid=279&theatreid=fd7c6bf3-bd50-4528-ada8-ab1361611fbd": Venue(
        name="Hornbio", city="Horn", address="Stångågatan 25"
    ),
    _BASE + "biografer.aspx?cityid=86&theatreid=c305ecac-f784-4944-8eb6-fcb394450551": Venue(
        name="Vittangi Bio Skandia", city="Vittangi", address="Kirunavägen 24"
    ),
    _BASE + "biografer.aspx?cityid=103&theatreid=14fee2fc-bfd9-4988-9ad7-32eab87fc0b0": Venue(
        name="Grand", city="Ljungbyhed", address="Storgatan 7"
    ),
    _BASE + "biografer.aspx?cityid=104&theatreid=34e2444c-6ed4-40a9-ab15-b313a87d2619": Venue(
        name="Kristianstad Filmmuseet", city="Kristianstad", address="Östra Storgatan 53"
    ),
    _BASE + "biografer.aspx?cityid=41&theatreid=93038d07-bb7d-458d-9a6f-6663adc2abd9": Venue(
        name="Valsjövallen", city="Valsjöbyn", address="Valsjöbyn"
    ),
    _BASE + "biografer.aspx?cityid=72&theatreid=e40efd03-b3b6-431c-a91d-34641fc89cc6": Venue(
        name="Kosta Folkbio", city="Kosta", address="Stora Vägen 47"
    ),
    _BASE + "biografer.aspx?cityid=280&theatreid=9c206b34-12cd-40df-9075-299678f2e441": Venue(
        name="Bestorp Eklunda Bio", city="Bestorp", address="Bonäsvägen 19"
    ),
    _BASE + "biografer.aspx?cityid=12&theatreid=ad817100-d4cd-466a-ae78-b0ca6a245f9b": Venue(
        name="Folkets Hus Bio", city="Fredriksberg", address="Ludvikavägen 22"
    ),
    _BASE + "biografer.aspx?cityid=13&theatreid=33b09ff2-e504-4fca-901e-2bbbe3801f46": Venue(
        name="Malungs Bio", city="Malung", address="Lisagatan 69"
    ),
    _BASE + "biografer.aspx?cityid=74&theatreid=8344cebc-71f8-414c-b887-4d47a46e8920": Venue(
        name="Strömsnäs Bio", city="Strömsnäsbruk", address="Nya Åbrovägen 6"
    ),
    _BASE + "biografer.aspx?cityid=244&theatreid=c3e756bf-6098-4f66-bc1f-5ddf09cad95c": Venue(
        name="Partille Bio Kulturum", city="Partille", address="Gamla Kronvägen 56"
    ),
    _BASE + "biografer.aspx?cityid=42&theatreid=3b9fee83-419b-4e78-97c0-d99b2176709a": Venue(
        name="Centrum", city="Hammarstrand", address="Centralgatan 29"
    ),
    _BASE + "biografer.aspx?cityid=112&theatreid=c0352cc1-0b8a-47aa-bce2-3e07a7b6db8c": Venue(
        name="Borrby Bio", city="Borrby", address="Sandbyvägen 4"
    ),
    _BASE + "biografer.aspx?cityid=190&theatreid=c416a3eb-83eb-4999-bb9c-90c2cf3c5d50": Venue(
        name="Bio Monsunen", city="Lövånger", address="Skolvägen"
    ),
    _BASE + "biografer.aspx?cityid=191&theatreid=5ab846b9-794e-4d25-9683-2691eb43304f": Venue(
        name="Bio Skatten", city="Sorsele", address="Stationsgatan 16"
    ),
    _BASE + "biografer.aspx?cityid=1000&theatreid=122103ca-575b-4712-becd-be8e3c075587": Venue(
        name="Aspen", city="Stockholm", address="Hägerstensvägen 100"
    ),
    _BASE + "biografer.aspx?cityid=43&theatreid=00710e6a-9e91-4ab5-8f94-8902f2d4f63f": Venue(
        name="Gåxsjö Bygdeg.för.bio", city="Gåxsjö", address="Gåxsjö 4420"
    ),
    _BASE + "biografer.aspx?cityid=43&theatreid=a1f710cf-ca40-4bd3-8acf-a45fe5202243": Venue(
        name="Saga Bio", city="Gäddede", address="Sagavägen 5"
    ),
    _BASE + "biografer.aspx?cityid=43&theatreid=28b91488-fb9d-4cea-8585-d02ffa62176e": Venue(
        name="Valhall Bio", city="Rossön", address="Hotingsvägen 23"
    ),
    _BASE + "biografer.aspx?cityid=18&theatreid=6f293985-0485-47a6-801c-fb2e22768d96": Venue(
        name="Rio-Säters Biografmuseum", city="Säter", address="Järnvägsgatan 26"
    ),
    _BASE + "biografer.aspx?cityid=31&theatreid=9a8463fe-ce5d-404b-ab6e-0f42a9a2762f": Venue(
        name="Trönöbio", city="Trönödal", address="Lertagsvägen 2"
    ),
    _BASE + "biografer.aspx?cityid=202&theatreid=175b7dda-690f-4546-a589-70900b209bcf": Venue(
        name="Timrå Söråkers Folkets Hus", city="Söråker", address="Folkets Husvägen 4"
    ),
    _BASE + "biografer.aspx?cityid=255&theatreid=c402f2f9-e459-4e1c-afc7-67fad52ef2de": Venue(
        name="Tranemo Bio Tranan", city="Tranemo", address="Medborgarplatsen"
    ),
    _BASE + "biografer.aspx?cityid=256&theatreid=be5d2e80-9445-4312-af1f-0a57f9008081": Venue(
        name="Hebeteatern", city="Trollhättan", address="Kungsgatan 25"
    ),
    _BASE + "biografer.aspx?cityid=257&theatreid=b72b9334-0935-4777-8796-638221e5217e": Venue(
        name="Röda Kvarn", city="Töreboda", address="Storgatan 19"
    ),
    _BASE + "biografer.aspx?cityid=258&theatreid=c27730e2-5b2e-4f6b-88fe-3663fab0dc04": Venue(
        name="Biostaden Uddevalla", city="Uddevalla", address="Göteborgsvägen 11A"
    ),
    _BASE + "biografer.aspx?cityid=258&theatreid=a2640256-8184-42e5-bd07-1dead6f0033e": Venue(
        name="Ljungskile Bybio", city="Ljungskile", address="Valdemar Svenssons väg 11"
    ),
    _BASE + "biografer.aspx?cityid=76&theatreid=d0978add-44f6-487a-a530-6863e9dac461": Venue(
        name="Folk Bio", city="Norrhult", address="Thorleifs gata 1"
    ),
    _BASE + "biografer.aspx?cityid=76&theatreid=197446bd-a580-491e-8a86-a4cca0584510": Venue(
        name="Fröseke Folkets Hus Bio", city="Fröseke", address="Skolgatan 23"
    ),
    # Two Bioguiden programme records share the same physical cinema.
    _BASE + "biografer.aspx?cityid=37&theatreid=cd62cdad-ab1a-4ae1-a0df-8f4c018664e5": Venue(
        name="Varbergs Teater", city="Varberg", address="Engelbrektsgatan 7"
    ),
    _BASE + "biografer.aspx?cityid=37&theatreid=93a5d081-ee80-4e0d-8cf6-5b1fd61c58f6": Venue(
        name="Varbergs Teater", city="Varberg", address="Engelbrektsgatan 7"
    ),
    _BASE + "biografer.aspx?cityid=57&theatreid=5f7a1c71-813d-410c-b840-08c9687273c1": Venue(
        name="Saga", city="Landsbro", address="Boställevägen 6"
    ),
    _BASE + "biografer.aspx?cityid=77&theatreid=e44b7225-dfd8-4b43-b51a-ff73af6513b8": Venue(
        name="Folkbio", city="Åseda", address="Olofsgatan 17"
    ),
    _BASE + "biografer.aspx?cityid=287&theatreid=c3e460f6-d256-43ac-ac5a-cd45a2db79ff": Venue(
        name="Folksalen", city="Österbymo", address="Mosshultsvägen 3"
    ),
    _BASE + "biografer.aspx?cityid=121&theatreid=06162d84-474a-4f9a-abc5-c7ce7b7a79aa": Venue(
        name="Biografteatern Scala", city="Ystad", address="Stora Östergatan 12"
    ),
    _BASE + "biografer.aspx?cityid=203&theatreid=245ec6fd-d8c0-41f7-8298-4d8fede2596c": Venue(
        name="Folkets Hus Bio", city="Ånge", address="Centraltorget 20"
    ),
    _BASE + "biografer.aspx?cityid=203&theatreid=a5723aac-921e-41a9-ae40-a00e59ccb2a1": Venue(
        name="Forum Bio", city="Ljungaverk", address="Folkets Husvägen 1"
    ),
    _BASE + "biografer.aspx?cityid=289&theatreid=2ea0c7b7-4858-4104-a050-fe20c89b6c9a": Venue(
        name="Saga Bio", city="Ödeshög", address="Stråtomtagatan 6"
    ),
    _BASE + "biografer.aspx?cityid=125&theatreid=06a71dd1-a2de-4a86-a113-feb79aa4f240": Venue(
        name="Sibbhults Folkets Hus", city="Sibbhult", address="Möllegatan 3"
    ),
}
_START = re.compile(r"\b\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\b")


def parse() -> Iterator[Screening | Venue | Film]:
    session = _http.session()
    films: set[str] = set()
    for url, venue in _SITES.items():
        response = session.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        selected = soup.select_one("#SearchTheatreDropDown option[selected]")
        query = parse_qs(urlsplit(url).query)
        expected = f"{query['cityid'][0]}|{query['theatreid'][0]}"
        programme = soup.select_one("#SearchResultDetails")
        cinema = soup.select_one("#biografinfo h2")
        if cinema is None or not selected or selected.get("value") != expected or programme is None:
            raise ValueError(f"Bioguiden: missing cinema programme at {url}")
        # Rows use either the source's full/short cinema name, our canonical name, or an auditorium.
        cinema_name = cinema.get_text(" ", strip=True)
        cinema_names = {cinema_name, cinema_name.split(",")[0], venue.name}
        yield venue
        screenings: dict[Screening, Screening] = {}

        for block in programme.select(".resultat"):
            title = block.select_one("h3")
            details = block.select_one("a[href*='filmfokus.aspx']")
            content = block.select_one(".contentCol")
            if title is None or details is None or content is None:
                raise ValueError(f"Bioguiden: unreadable film at {url}")
            title = title.get_text(" ", strip=True)
            runtime = block.select_one("li.second")
            minutes = re.search(r"\b(\d+)\s+min\b", runtime.get_text(" ", strip=True)) if runtime else None
            rating = block.select_one("li.third")
            poster = block.select_one(".imgCol img[src]")
            rows = block.select("[id=biografrepertoire] > ul > li")
            if not title or not rows:
                raise ValueError(f"Bioguiden: missing film title or screenings at {url}")
            # Synopsis and screenings share a column; remove the programme panel before reading the prose.
            panel = content.select_one("[id$='_RepertoirePanel']")
            if panel is not None:
                panel.extract()
            film = _films.make(
                _SOURCE,
                title,
                url=urljoin(_BASE, details["href"]),
                overview=" ".join(content.get_text(" ", strip=True).split()),
                runtime=int(minutes[1]) or None if minutes else None,
                age_rating=rating.get_text(" ", strip=True) if rating else "",
                poster_url=(
                    urljoin(_BASE, poster["src"]) if poster and poster["src"] != "img/bild_saknas_150x90.gif" else ""
                ),
            )
            if film.key not in films:
                films.add(film.key)
                yield _films.register(film, session=session)

            for row in rows:
                # Price popups and booking buttons are not part of the date/time text.
                row_text = " ".join(row.find_all(string=True, recursive=False))
                start = _START.search(row_text)
                if start is None:
                    raise ValueError(f"Bioguiden: unreadable screening of {title} at {url}")
                day, clock = start[0].split()
                screen = row_text[start.end() :].strip()
                booking = row.select_one("a[href]")
                ticket_url = urljoin(_BASE, booking["href"]) if booking else url
                if urlsplit(ticket_url).path == "/redirect.aspx":
                    ticket_url = parse_qs(urlsplit(ticket_url).query)["url"][0]
                screening = Screening(
                    tmdb_id=_tmdb(film.title, runtime=film.runtime),
                    title=film.title,
                    film_key=film.key,
                    date=date.fromisoformat(day),
                    time=time.fromisoformat(clock),
                    ticket_url=ticket_url,
                    cinema_name=venue.name,
                    city=venue.city,
                    screen=screen,
                )
                # Duplicate film records can publish one show twice, with and without online booking.
                key = replace(screening, ticket_url="")
                if key not in screenings or screenings[key].ticket_url == url:
                    screenings[key] = screening
        # Aspen names one hall after the cinema. Keep it when the programme also names other halls.
        has_auditoriums = any(s.screen not in cinema_names for s in screenings.values())
        for screening in screenings.values():
            yield screening if has_auditoriums else replace(screening, screen="")

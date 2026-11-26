"""Group source Movie records into films, using only the records' own metadata.

A work title names one film unless the evidence splits it:

1. Listing titles are reduced to work titles: screening qualifiers ("Premiär:", "(Dolby Atmos)",
   "– Extended version", language labels) describe an event, not the work shown.
2. Records sharing a work title form a block. Strong evidence ties records together (a shared
   director, a reused synopsis) and splits them apart (years, directors, or runtimes that
   cannot belong to one work). A block divides only along such a contradiction; a record that
   could belong to several works stays apart rather than guess.
3. Works with different titles join when a distributor's synopsis is reused nearly verbatim,
   or when a truncated title names exactly one longer one and evidence confirms it.

Shared showtimes are not evidence: listings attach several films to one session.
"""

import re
import unicodedata
from collections import defaultdict
from itertools import combinations

# Screening qualifiers: they describe an event, not the work shown.
_QUALIFIERS = [
    r"^(?:extravisning|förhandsvisning|premiär|galapremiär|sneak preview|festival|klassiker|filmklubb"
    r"|cinemateket|unga cinemateket|bio|dagbio|knattebio|barnbio|familjebio|frukostbio|eftermiddagsfilm"
    r"|seniorbio|filmfeber|höstlovsfilm|påsklovsfilm|sportlovsbio|jullovsbio|lovbio|julbio|favorit i repris"
    r"|met|met live in hd|national theatre|nt live|royal opera house|royal ballet|bolshoi ballet"
    r"|sing[- ]?along|party[- ]?along|live på bio|sverigepremiär)\s*(?:\(\d+\))?\s*[:!\-–—]?\s*",
    r"\s*[(\[](?:sv\.?|eng\.?|svenskt|engelskt|svensk|engelsk|orig\.?|originalspråk)?\s*"
    r"(?:tal|txt|text|textad|otextad|dubbad|dubbat|version)[^)\]]*[)\]]\s*$",
    r"\s*[·•|]\s*(?:engelska|svenska|engelskt tal|svenskt tal|eng|sv|originalversion|dubbad)\s*$",
    r"\s*[-–—,]\s*(?:live på bio|favorit i repris|extended(?: edition| version|cut)?|director'?s cut|klassiker"
    r"|(?:svensk|engelsk) (?:text|tal)|textad|otextad|dubbad|bioupplevelsen|cinema experience|julbordsspecial"
    r"|complete version)\s*!?$",
    # A year names the work's production year; it is read as a fact, not kept in the title.
    r"\s*\((?:19|20)\d\d\)\s*$",
    r"\s*\((?:extended(?: edition| version)?|director'?s cut|klassiker|live på bio|bio|dolby atmos|imax|3d|2d|4dx"
    r"|screen ?x|70 ?mm|35 ?mm)\)\s*$",
    # A trailing town names where it is shown, not what is shown.
    r"\s+[-–—]\s*(?:oskarshamn|stockholm|göteborg|malmö)\s*$",
    r"\s*[:\-–—]\s*bioupplevelsen\s*$",
    r"\s*!$",
]
_ARTICLES = r"^(?:the|a|an|en|ett|den|det|le|la|les|el|der|die|das)\s+"
_TITLE_YEAR = re.compile(r"\(((?:19|20)\d\d)\)\s*$")
_SHINGLE = 5
# Synopses with fewer shingles say too little to compare.
_MIN_PLOT = 15
# Share of the shorter synopsis that must recur for it to identify a work.
_SAME_PLOT = 0.2
_BRIDGE_PLOT = 0.5
# Shared passages needed before comparing two works, and how many works a passage may appear in.
_BRIDGE_SHINGLES = 10
_BOILERPLATE = 3


def fold(text: str) -> str:
    """Casefolded word tokens; diacritics folded except å, ä and ö; '&' and 'and' as 'och'."""
    # Apostrophes split words; listings use several characters for them.
    text = re.sub("[\u2019\u00b4]", "'", unicodedata.normalize("NFKC", text).casefold().replace("&", " och "))
    kept = []
    for char in unicodedata.normalize("NFD", text):
        if unicodedata.combining(char) and kept and kept[-1] in "aou" and char in "\u0308\u030a":
            kept[-1] = unicodedata.normalize("NFC", kept[-1] + char)
        elif not unicodedata.combining(char):
            kept.append(char)
    return " ".join("och" if word == "and" else word for word in re.findall(r"\w+", "".join(kept)))


def work_title(title: str) -> str:
    """A listing title without screening qualifiers."""
    previous, title = None, title.strip()
    while previous != title:
        previous = title
        for pattern in _QUALIFIERS:
            title = re.sub(pattern, "", title, flags=re.IGNORECASE).strip()
    return title


def title_keys(movie: dict) -> set[str]:
    """Folded titles a record can be found by, with and without a leading article."""
    found = set()
    for field in ("name", "alternateName"):
        value = movie.get(field)
        for raw in value if isinstance(value, list) else [value]:
            for variant in {raw, work_title(raw)} if raw else ():
                if folded := fold(variant):
                    found |= {folded, re.sub(_ARTICLES, "", folded)}
    # Editions of a marathon are one event, however it is spelled.
    return {re.sub(r"\bmarathon\b", "maraton", key) for key in found} - {""}


def _people(movie: dict, role: str) -> set[str]:
    found = movie.get(role) or []
    names = set()
    for person in found if isinstance(found, list) else [found]:
        name = person.get("name") if isinstance(person, dict) else person
        # "A och B", "A, B" and "A & B" each list several people.
        names |= {folded for part in re.split(r",|\boch\b|&|\band\b", name or "") if (folded := fold(part))}
    return names


def _facts(movie: dict) -> dict:
    published = (movie.get("datePublished") or "")[:4]
    stated = _TITLE_YEAR.search(movie.get("name") or "")
    duration = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", movie.get("duration") or "")
    words = fold(movie.get("description") or "").split()
    plot = {tuple(words[i : i + _SHINGLE]) for i in range(len(words) - _SHINGLE + 1)}
    return {
        "year": int(stated[1]) if stated else int(published) if published.isdigit() and len(published) == 4 else None,
        "runtime": (int(duration[1] or 0) * 60 + int(duration[2] or 0)) or None if duration else None,
        # Transliterations vary ("Koreeda", "Kore-eda"); surnames still agree.
        "directors": {name.split()[-1] for name in _people(movie, "director")},
        "plot": plot if len(plot) >= _MIN_PLOT else set(),
    }


def _close(a: int, b: int) -> bool:
    """Runtimes of one work: listings round, add trailers, or count a programme."""
    return abs(a - b) <= max(5, min(a, b) * 0.08)


def _overlap(a: set, b: set) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def _relation(a: dict, b: dict) -> str:
    """'same' when strong evidence agrees, 'different' when it contradicts, else 'unknown'."""
    if a["year"] and b["year"] and abs(a["year"] - b["year"]) > 1:
        return "different"
    if a["directors"] and b["directors"]:
        return "same" if a["directors"] & b["directors"] else "different"
    # Distributors' synopses are reused verbatim; different synopses prove nothing.
    if _overlap(a["plot"], b["plot"]) >= _SAME_PLOT:
        return "same"
    runtimes = a["runtime"], b["runtime"]
    # Editions differ by far more than listings of one cut.
    if all(runtimes) and abs(runtimes[0] - runtimes[1]) > max(15, min(runtimes) * 0.25):
        return "different"
    return "unknown"


class _Union:
    def __init__(self, items):
        self.parent = {item: item for item in items}

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a, b)] = min(a, b)

    def groups(self):
        found = defaultdict(list)
        for item in self.parent:
            found[self.find(item)].append(item)
        return [sorted(group) for group in found.values()]


def _split(block: list[str], info: dict) -> list[list[str]]:
    """Divide a title block into works along contradictions only."""
    relations = {}
    for a, b in combinations(block, 2):
        relations[a, b] = relations[b, a] = _relation(info[a], info[b])
    cores = _Union(block)
    for (a, b), found in relations.items():
        if found == "same":
            cores.join(a, b)
    groups = [set(group) for group in cores.groups()]

    def contradicts(left, right):
        return any(relations[a, b] == "different" for a in left for b in right)

    if not any(contradicts(left, right) for left, right in combinations(groups, 2)):
        return [block]
    works = []
    for group in sorted(groups, key=lambda group: (-len(group), sorted(group))):
        fits = [work for work in works if not contradicts(group, work)]
        if len(fits) == 1:
            fits[0] |= group
        else:
            # Compatible with several works, or none: keep apart rather than guess.
            works.append(set(group))
    return [sorted(work) for work in works]


def _typical_runtime(work: list[str], info: dict) -> int | None:
    """Median runtime; one listing's outlier (a programme with shorts, a typo) doesn't move it."""
    runtimes = sorted(info[key]["runtime"] for key in work if info[key]["runtime"])
    return runtimes[len(runtimes) // 2] if runtimes else None


def _compatible(left: list[str], right: list[str], info: dict) -> bool:
    if any(_relation(info[a], info[b]) == "different" for a in left for b in right):
        return False
    runtimes = _typical_runtime(left, info), _typical_runtime(right, info)
    return None in runtimes or _close(*runtimes)


def _synopsis_bridges(works: list[list[str]], info: dict) -> list[tuple[int, int]]:
    """Works with different titles whose synopses are the same distributor text."""
    owners = defaultdict(set)
    for index, work in enumerate(works):
        for key in work:
            for shingle in info[key]["plot"]:
                owners[shingle].add(index)
    shared = defaultdict(int)
    for found in owners.values():
        # Passages in many works are boilerplate: release notes, cast lists, festival blurbs.
        if 1 < len(found) <= _BOILERPLATE:
            for pair in combinations(sorted(found), 2):
                shared[pair] += 1
    bridges = []
    for (a, b), count in sorted(shared.items()):
        if count < _BRIDGE_SHINGLES or not _compatible(works[a], works[b], info):
            continue
        if max(_overlap(info[x]["plot"], info[y]["plot"]) for x in works[a] for y in works[b]) >= _BRIDGE_PLOT:
            bridges.append((a, b))
    return bridges


def _prefix_bridges(works: list[list[str]], info: dict, titles: dict, movies: dict) -> list[tuple[int, int]]:
    """A truncated title ("Pavarotti", "Ebenezer") joins the one longer title it starts.

    Sequels extend their original's title too, so a director, the synopsis, or the synopsis
    naming the longer title must confirm, and typical runtimes must agree.
    """
    work_titles = [{title for key in work for title in titles[key]} for work in works]
    holders = defaultdict(set)
    for index, found in enumerate(work_titles):
        for title in found:
            holders[title].add(index)
    bridges = []
    for index, found in enumerate(work_titles):
        candidates = {
            other
            for short in found
            if len(short) >= 4
            for title, owners in holders.items()
            if title.startswith(short + " ")
            for other in owners - {index}
        }
        if len(candidates) != 1:
            continue
        (other,) = candidates
        if not _compatible(works[index], works[other], info):
            continue
        named = {title for title in work_titles[other] if len(title) > 15}
        mentions = any(title in fold(movies[x].get("description") or "") for x in works[index] for title in named)
        if mentions or any(_relation(info[x], info[y]) == "same" for x in works[index] for y in works[other]):
            bridges.append((index, other))
    return bridges


def groups(movies: dict[str, dict]) -> list[list[str]]:
    """Keys of `movies` grouped by film."""
    info = {key: _facts(movie) for key, movie in movies.items()}
    titles = {key: title_keys(movie) for key, movie in movies.items()}
    blocks = _Union(movies)
    by_title = defaultdict(list)
    for key in sorted(movies):
        for title in titles[key]:
            by_title[title].append(key)
    for keys in by_title.values():
        for key in keys[1:]:
            blocks.join(keys[0], key)
    works = [work for block in blocks.groups() for work in _split(block, info)]
    joined = _Union(range(len(works)))
    for a, b in _synopsis_bridges(works, info) + _prefix_bridges(works, info, titles, movies):
        joined.join(a, b)
    return sorted(sorted(key for index in group for key in works[index]) for group in joined.groups())

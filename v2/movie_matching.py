"""Group source movies using the v1 reconciler's source-evidence rules."""

import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from itertools import combinations

# Strip programme labels, not subtitles or sequel names.
_LABELS = (
    r"^(?:(?:extravisning(?:\s*\(\d+\))?|premiär|höstlovsfilm|påsklovsfilm|favorit i repris)[!:]?\s+)+",
    r"^filmfeber:\s*",
    r"(?:\s+\(live på bio\)|\s*:\s*bioupplevelsen|\s+cinema experience)$",
    r"\s*\((?:sv\.?|eng)\s*(?:tal|txt|text)\)\s*$",
    r"\s+förfilm\s+.*$",
    r",\s*version:.*$",
    r"\s+(eng|sv\.?)\s+(tal|txt)\.?\s*$",
)


def words(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())


def title_key(title: str) -> str:
    for label in _LABELS:
        title = re.sub(label, "", title, flags=re.IGNORECASE)
    return " ".join(words(title))


def credit_names(movie: dict, role: str) -> set[str]:
    people = movie.get(role, [])
    return {" ".join(words(person["name"])) for person in (people if isinstance(people, list) else [people])} - {""}


def groups(movies: dict[str, dict], slots: dict[str, set[tuple[str, str]]]) -> list[list[str]]:
    """Use only evidence in the source graphs; never match on a title alone."""
    titles = {}
    plots = {}
    years = {}
    runtimes = {}
    directors = {}
    actors = {}
    identities = {}
    for key, movie in movies.items():
        titles[key] = {title_key(movie[field]) for field in ("name", "alternateName") if movie.get(field)} - {""}
        same_as = movie.get("sameAs", [])
        identities[key] = {
            url.rstrip("/")
            for url in [movie.get("url", ""), *(same_as if isinstance(same_as, list) else [same_as])]
            if url
        }
        plots[key] = words(movie.get("description", ""))
        year = movie.get("datePublished", "")[:4]
        years[key] = int(year) if len(year) == 4 and year.isascii() and year.isdigit() else None
        duration = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", movie.get("duration", ""))
        runtimes[key] = int(duration[1] or 0) * 60 + int(duration[2] or 0) if duration else 0
        directors[key] = credit_names(movie, "director")
        actors[key] = credit_names(movie, "actor")

    def compatible(a, b, programme):
        ya, yb = years[a], years[b]
        if ya and yb and abs(ya - yb) > 1:
            return False
        ra, rb = runtimes[a], runtimes[b]
        return not (ra and rb) or abs(ra - rb) <= (min(ra, rb) / 4 if programme else 2)

    def match(a, b, programme):
        if not compatible(a, b, programme):
            return False
        if programme and identities[a] & identities[b]:
            return True
        shared_director = directors[a] & directors[b]
        if not titles[a] & titles[b]:
            return False
        if programme and shared_director and len(actors[a] & actors[b]) >= 2:
            return True
        shorter, longer = sorted((plots[a], plots[b]), key=lambda plot: len(" ".join(plot)))
        alignment = SequenceMatcher(None, shorter, longer, autojunk=False)
        common = alignment.find_longest_match()
        if (
            (common.size >= 20 or (not programme and common.size >= 15 and common.size == len(shorter)))
            and len(" ".join(shorter[common.a : common.a + common.size])) >= 100
            and (
                common.size * 2 >= len(shorter)
                or sum(m.size for m in alignment.get_matching_blocks()) * 10 >= len(shorter) * 9
                or (common.size >= 25 and runtimes[a] and runtimes[b] and compatible(a, b, False))
            )
        ):
            return True
        return not programme and bool(
            slots[a] & slots[b]
            or ((shared_director or (years[a] and years[a] == years[b])) and runtimes[a] and runtimes[b])
        )

    units = {key: [key] for key in sorted(movies)}
    while True:
        previous_count = len(units)
        # Confirm plot or credit matches before weaker evidence, then reconsider title aliases.
        for programme in (True, False):
            by_title = defaultdict(set)
            for unit, keys in units.items():
                for key in keys:
                    for title in titles[key]:
                        by_title["title", title].add(unit)
                    for identity in identities[key]:
                        by_title["url", identity].add(unit)
            pairs = {pair for matching in by_title.values() for pair in combinations(sorted(matching), 2)}
            edges = defaultdict(set)
            for left, right in sorted(pairs):
                if any(
                    match(a, b, programme)
                    for a in units[left]
                    for b in units[right]
                    if titles[a] & titles[b] or identities[a] & identities[b]
                ):
                    edges[left].add(right)
                    edges[right].add(left)
            visited = set()
            for start in edges:
                if start in visited:
                    continue
                component, pending = set(), [start]
                while pending:
                    item = pending.pop()
                    if item not in component:
                        component.add(item)
                        pending.extend(edges[item] - component)
                visited.update(component)
                keys = sorted(key for unit in component for key in units[unit])
                # Reject a chain if it would combine contradictory years or runtimes.
                if not all(
                    compatible(a, b, programme)
                    for left, right in combinations(sorted(component), 2)
                    for a in units[left]
                    for b in units[right]
                ):
                    continue
                for unit in component:
                    del units[unit]
                units[keys[0]] = keys
        if len(units) == previous_count:
            return [units[key] for key in sorted(units)]

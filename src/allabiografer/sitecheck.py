"""Check a rendered site before it is deployed.

- every page ever published resolves, to a page or a redirect;
- a redirect leads to a page, never to a missing page or another redirect;
- the sitemap lists pages only;
- every internal link, in HTML and Markdown, leads somewhere.

Exits non-zero listing what is wrong.
"""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .graph import DATA, Graph
from .pipeline import open_store, published
from .render import published as published_paths

REFRESH = re.compile(r'http-equiv="refresh" content="0; url=([^"]+)"')


def _file(www: Path, path: str) -> Path:
    path = unquote(path)
    return www / path.strip("/") / "index.html" if path.endswith("/") else www / path.lstrip("/")


def _redirect(page: Path) -> str | None:
    found = REFRESH.search(page.read_text(encoding="utf-8", errors="replace")[:4000])
    return unquote(found[1]) if found else None


def problems(www: Path, paths: set[str]) -> list[str]:
    """What is wrong with the site in `www`, given every path ever published."""
    found = [f"published page missing: {path}" for path in sorted(paths) if not _file(www, path).is_file()]
    for page in sorted(www.rglob("index.html")):
        if (target := _redirect(page)) is None:
            continue
        landing = _file(www, target)
        where = "/" + page.parent.relative_to(www).as_posix() + "/"
        if not landing.is_file():
            found.append(f"redirect to a missing page: {where} → {target}")
        elif _redirect(landing) is not None:
            found.append(f"redirect to a redirect: {where} → {target}")
    sitemap = (www / "sitemap.xml").read_text(encoding="utf-8")
    for url in re.findall(r"<loc>([^<]+)</loc>", sitemap):
        page = _file(www, urlsplit(url).path)
        if not page.is_file() or _redirect(page) is not None:
            found.append(f"sitemap lists no page: {url}")
    links = set()
    for page in www.rglob("index.html"):
        if _redirect(page) is None:
            links |= set(re.findall(r'(?:href|src)="(/[^"#?]*)', page.read_text(encoding="utf-8", errors="replace")))
    for page in www.rglob("index.md"):
        links |= set(re.findall(r"\]\((/[^)#?\s]*)", page.read_text(encoding="utf-8", errors="replace")))
    found += [f"broken link: {link}" for link in sorted(links) if not _file(www, link).exists()]
    return found


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("--data", type=Path, default=DATA)
    cli.add_argument("--production", action="store_true", help="Read the published pages from the production R2 store")
    args = cli.parse_args()
    graph = Graph(args.data.resolve(), open_store(args.data.resolve(), production=args.production))
    found = problems(args.data / "www", published_paths(graph, published(graph)))
    for problem in found[:200]:
        print(problem, file=sys.stderr)
    if found:
        sys.exit(f"{len(found)} problem(s) with the site")
    print("The site is sound")

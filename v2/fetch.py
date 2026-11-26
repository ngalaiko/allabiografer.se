"""Capture cinema schedules selected from the registry."""

import argparse
from collections import defaultdict
from dataclasses import asdict
from importlib import import_module
from pathlib import Path
from time import time

from parse import _http

from .schedule import DATA, SELECTION, Route, checked, routes
from .schema import write

SINGLE = {
    "bioaspen_se": "aspen",
    "biofagelbla_se": "bio-fagel-bla",
    "biorio_se": "bio-rio",
    "capitolbio_se": "capitol",
    "fhbracke_se": "bracke-bio",
    "hallundafolketshus_se": "hallunda-folkets-hus",
    "hypnostheatre_com": "hypnos-theatre",
    "kiviksbio_se": "kiviks-bio",
    "kulturiskovde_se": "biograf-odeon-skovde",
    "osbyborgen_se": "bio-borgen-osby",
    "palladiumbio_se": "filmhuset-palladium-arvika",
    "riobiotomelilla_se": "riobiografen-tomelilla",
    "roxy_bio": "roxy-bio-kristianstad",
    "soderkopingsbio_se": "soderkopings-bio",
    "wp_theatre": "capitol-goteborg",
}


def capture(data: Path, selected: list[Route]) -> Path:
    groups = defaultdict(list)
    for route in selected:
        groups[route.adapter].append(route)
    job = data / "fetch" / str(int(time()))
    job.mkdir(parents=True)
    for adapter, group in groups.items():
        fetch_pages = import_module(f".source.{adapter}.fetch", __package__).fetch_pages
        inputs = job / "sources" / adapter
        inputs.mkdir(parents=True)
        selectors = {route.venue_id for route in group}
        with _http.session() as session:
            if adapter in SINGLE:
                checked(selectors, {SINGLE[adapter]})
                fetch_pages(session, inputs)
            elif adapter == "nortic_se":
                # Nortic exposes a single feed; parse applies the venue selection.
                fetch_pages(session, inputs)
            else:
                fetch_pages(session, inputs, selectors=selectors)
        write(inputs / SELECTION, [asdict(route) for route in group])
    return job


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("cinema", nargs="*", help="Cinema ID (MovieTheater filename stem)")
    cli.add_argument("--all", action="store_true", help="Capture every registered cinema")
    cli.add_argument("--data", type=Path, default=DATA)
    args = cli.parse_args()
    if args.all == bool(args.cinema):
        cli.error("provide cinema IDs or --all")
    data = args.data.resolve()
    try:
        available = routes(data)
        checked(set(args.cinema), available)
    except ValueError as error:
        cli.error(str(error))
    selected = list(available.values()) if args.all else [available[cinema] for cinema in dict.fromkeys(args.cinema)]
    print(capture(data, selected))


if __name__ == "__main__":
    main()

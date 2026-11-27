"""Each adapter reads its saved pages into exactly the rows saved with them.

A failure means a reader changed what it makes of a site. If the change is intended,
`nix run .#fixture -- update <adapter>` records the new rows; review them in the diff.
"""

import json
from pathlib import Path

import pytest

from allabiografer import fixtures

ADAPTERS = sorted(
    path.name
    for path in (Path(fixtures.__file__).parent / "sources").iterdir()
    if path.is_dir() and not path.name.startswith("_")
)


def test_every_adapter_has_a_fixture():
    assert sorted(path.name for path in fixtures.ROOT.iterdir() if path.is_dir()) == ADAPTERS


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_adapter_reads_its_saved_pages(adapter, tmp_path):
    day = fixtures.unpack(adapter, tmp_path)

    rows = fixtures.snapshot(adapter, tmp_path, day)

    assert rows, "a fixture lists screenings"
    if rows != fixtures.saved(adapter)["rows"]:
        diff = "\n".join(fixtures.diff(adapter)[:80])
        pytest.fail(f"{adapter} reads its pages differently:\n{diff}", pytrace=False)


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_every_screening_names_the_files_it_was_read_from(adapter, tmp_path):
    fixtures.unpack(adapter, tmp_path)
    files = {path.name for path in tmp_path.iterdir()}

    for row in fixtures.saved(adapter)["rows"]:
        assert row["capture"] in files, json.dumps(row, ensure_ascii=False)
        assert set(row["listing"]) <= files, json.dumps(row, ensure_ascii=False)

"""Year inference for yearless screening dates."""

import pytest

from parse._util import infer_year

pytestmark = pytest.mark.usefixtures("parser_clock")


def test_fixture_months_use_2026():
    assert infer_year(9) == 2026
    assert infer_year(10) == 2026


@pytest.mark.parametrize(
    ("parser_clock", "month", "expected"),
    [
        ("2026-09-30T12:00:00+02:00", 9, 2026),
        ("2026-09-30T12:00:00+02:00", 10, 2026),
        ("2026-10-01T00:00:00+02:00", 9, 2026),
        ("2026-10-01T00:00:00+02:00", 8, 2027),
        ("2026-12-31T12:00:00+01:00", 1, 2027),
        ("2027-01-01T00:00:00+01:00", 1, 2027),
        ("2026-09-30T22:00:00+00:00", 9, 2026),
        ("2026-12-31T23:00:00+00:00", 12, 2026),
        ("2027-01-15T12:00:00+01:00", 11, 2027),
    ],
    indirect=["parser_clock"],
)
def test_infer_year(parser_clock, month, expected):
    assert infer_year(month) == expected

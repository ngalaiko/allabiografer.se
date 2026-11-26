"""Date inference for saved regional programmes without explicit years."""


def year_from_capture(today, month):
    # Match v1's rollover rule, but anchor it to the capture rather than the replay clock.
    if month == (today.month - 2) % 12 + 1:
        return today.year - (today.month == 1)
    return today.year + (month < today.month)

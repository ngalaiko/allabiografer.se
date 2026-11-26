"""Date inference for saved regional programmes without explicit years."""


def year_from_capture(today, month):
    # A month just past belongs to this year (late listings); earlier months roll to next year.
    # Anchored to the capture day, not the replay clock.
    if month == (today.month - 2) % 12 + 1:
        return today.year - (today.month == 1)
    return today.year + (month < today.month)

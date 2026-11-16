from datetime import date

import pytest

from app.core.periods import period_for


@pytest.mark.parametrize(
    ("d", "payday", "start", "end"),
    [
        (date(2026, 10, 7), 25, date(2026, 9, 25), date(2026, 10, 24)),
        (date(2026, 10, 25), 25, date(2026, 10, 25), date(2026, 11, 24)),
        (date(2026, 10, 1), 1, date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 1, 10), 25, date(2025, 12, 25), date(2026, 1, 24)),
        # 31일 수입일: 2월은 말일로 보정
        (date(2026, 2, 28), 31, date(2026, 2, 28), date(2026, 3, 30)),
        (date(2026, 2, 27), 31, date(2026, 1, 31), date(2026, 2, 27)),
    ],
)
def test_period_for(d, payday, start, end):
    p = period_for(d, payday)
    assert (p.start, p.end) == (start, end)


def test_date_for_day_crosses_month():
    p = period_for(date(2026, 10, 7), 25)  # 9/25 ~ 10/24
    assert p.date_for_day(27) == date(2026, 9, 27)
    assert p.date_for_day(5) == date(2026, 10, 5)
    assert p.date_for_day(25) == date(2026, 9, 25)

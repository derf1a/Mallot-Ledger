"""가계부 기간 계산: 한 달은 '수입일'부터 다음 달 수입일 전날까지로 고정한다.

예) 수입일 25일 → 2026-09-25 ~ 2026-10-24 가 한 기간.
수입일이 그 달에 없으면(31일 등) 그 달 말일로 맞춘다.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta


def _clamp(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # 포함

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end

    def date_for_day(self, day: int) -> date:
        """기간 안에서 '매월 day일'에 해당하는 날짜."""
        y, m = self.start.year, self.start.month
        candidate = _clamp(y, m, day)
        if candidate < self.start:
            y, m = _shift_month(y, m, 1)
            candidate = _clamp(y, m, day)
        return candidate

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def period_for(d: date, payday: int) -> Period:
    start = _clamp(d.year, d.month, payday)
    if d < start:
        y, m = _shift_month(d.year, d.month, -1)
        start = _clamp(y, m, payday)
    ny, nm = _shift_month(start.year, start.month, 1)
    end = _clamp(ny, nm, payday) - timedelta(days=1)
    return Period(start, end)

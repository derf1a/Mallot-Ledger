"""사실 문장에 쓰는 숫자 표기 — 사실을 만드는 모듈(facts·fixed·tax)이 같이 쓴다."""


def won(n: float) -> str:
    return f"{round(n):,}원"


def share(part: float, whole: float) -> str:
    return f"{part / whole * 100:.0f}%" if whole else "0%"


def change(now: float, before: float) -> str:
    if not before:
        return "비교 불가"
    return f"{(now - before) / before * 100:+.0f}%"

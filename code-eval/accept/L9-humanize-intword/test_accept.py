"""L9 隐藏验收：intword() 的进位必须用整数比较（来自上游真实回归测试）。"""

import humanize


UNITS = [
    "thousand",
    "million",
    "billion",
    "trillion",
    "quadrillion",
    "quintillion",
    "sextillion",
    "septillion",
    "octillion",
    "nonillion",
    "decillion",
]


def test_intword_rounding_rollover():
    """Rounding up to the next power must carry to the next unit."""
    for i, exponent in enumerate(range(6, 34, 3), start=1):
        value = 10**exponent - 1
        assert humanize.intword(value) == f"1.0 {UNITS[i]}"
        assert humanize.intword(value, "%.0f") == f"1 {UNITS[i]}"

    for exponent in range(6, 34, 3):
        rendered = humanize.intword(10**exponent - 1)
        mantissa = float(rendered.split(" ", 1)[0])
        assert mantissa < 1000

    assert humanize.intword(10**36) == "1000.0 decillion"
    assert humanize.intword(2 * 10**100) == "2.0 googol"

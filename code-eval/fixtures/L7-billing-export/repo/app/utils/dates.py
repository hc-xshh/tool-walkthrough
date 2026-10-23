"""日期：只认 YYYY-MM-DD。"""

from datetime import date


def month_of(iso_date):
    return iso_date[:7]


def parse_day(iso_date):
    return date.fromisoformat(iso_date)

"""CSV 数据源：按行产出清洗后的字典。"""

import csv


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            yield {
                (k or "").strip(): (v or "").strip()
                for k, v in row.items()
            }

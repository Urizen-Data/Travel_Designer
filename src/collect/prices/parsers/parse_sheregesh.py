"""Парсер: Шерегеш (gesh.ru/sheregesh/skipass/).

Формат на странице: «... 1 день взрослый 3100Р ...». Берём цену «взрослый, 1 день».
"""
from __future__ import annotations

import re

RESORT_ID = "R004"
NAME = "Шерегеш"
URL = "https://gesh.ru/sheregesh/skipass/"


def extract(html: str) -> dict | None:
    m = re.search(r'1\s*день\s*взрослый\s*([\d\s]{3,6})\s*(?:Р|₽|руб)', html, re.IGNORECASE)
    if not m:
        return None
    price = int(re.sub(r'\s', '', m.group(1)))
    return {"min": price, "max": price}

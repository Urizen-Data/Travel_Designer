"""Парсер: Кукисвумчорр (kukisvumchorr.ru/prices).

Формат на странице: «Цены на ски-пассы ... 1 день 2 000 ₽». Берём «1 день».
"""
from __future__ import annotations

import re

RESORT_ID = "R014"
NAME = "Кукисвумчорр"
URL = "https://kukisvumchorr.ru/prices"


def extract(html: str) -> dict | None:
    m = re.search(r'1\s*день\s*([\d\s]{3,7})\s*(?:₽|руб|\bР\b)', html, re.IGNORECASE)
    if not m:
        return None
    price = int(re.sub(r'\s', '', m.group(1)))
    return {"min": price, "max": price}

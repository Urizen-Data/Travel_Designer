"""Парсер: Гора Белая (gorabelaya.ru/services/zimniy-sezon/ski-pass/).

Формат: «Абонемент "Дневной" (все трассы), один день 2 200₽ 2 400₽»
(будни / выходные). Берём первое вхождение «один день» с двумя ценами.
"""
from __future__ import annotations

import re

RESORT_ID = "R021"
NAME = "Гора Белая"
URL = "https://www.gorabelaya.ru/services/zimniy-sezon/ski-pass/"


def extract(html: str) -> dict | None:
    m = re.search(r'один\s*день\s*([\d\s]{3,6})\s*₽\s*([\d\s]{3,6})\s*₽', html, re.IGNORECASE)
    if not m:
        return None
    mn = int(re.sub(r'\s', '', m.group(1)))
    mx = int(re.sub(r'\s', '', m.group(2)))
    return {"min": min(mn, mx), "max": max(mn, mx)}

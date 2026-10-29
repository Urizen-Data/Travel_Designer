"""Общий краулер цен на ски-пассы («первый проход»).

Пробует URL из реестра sites.SITES, находит страницу цен и извлекает грубую
оценку (числа с «₽/руб» в контексте «день/взрослый/ски-пасс»).

ВНИМАНИЕ: это оценка, а не точный тариф. Для точного тарифа «взрослый, 1 день»
нужны отдельные парсеры на сайт (структура у всех разная). Точные значения —
в sites.VERIFIED.

Запуск:  python src/collect/prices/scrape_prices.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from src.collect.prices.sites import SITES  # noqa: E402

OUT = PROJECT_ROOT / "data" / "collected" / "prices_scrape.json"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def fetch(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace"), r.url


def clean(html: str) -> str:
    t = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r'<style[^>]*>.*?</style>', ' ', t, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r'<[^>]+>', ' ', t)
    return re.sub(r'\s+', ' ', t)


def find_price_links(html: str, base: str) -> list[str]:
    out = []
    for href, text in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE):
        t = re.sub(r'<[^>]+>', '', text).strip()
        if re.search(r'ски-?пасс|скипасс|skipass|тариф|цен|прайс|price|tarif', href + ' ' + t, re.IGNORECASE):
            url = href if href.startswith('http') else base.rstrip('/') + ('' if href.startswith('/') else '/') + href
            out.append(url)
    return out


def adult_day_prices(text: str) -> list[int]:
    """Грубая оценка: числа с ₽/руб в контексте 'день/взрослый/ски-пасс'."""
    out = []
    for m in re.finditer(r'(?:1\s*день|взрослый|ски-?пасс|будни|выходные)', text, re.IGNORECASE):
        seg = text[max(0, m.start() - 70):m.start() + 200]
        for n in re.findall(r'([\d\s]{3,6})\s*(?:₽|руб|\bр\b)', seg, re.IGNORECASE):
            n2 = re.sub(r'\s', '', n)
            if n2.isdigit() and 300 <= int(n2) <= 25000:
                out.append(int(n2))
    return sorted(set(out))


def main() -> None:
    results = {}
    for rid, name, urls in SITES:
        got = None
        for url in urls:
            try:
                html, final = fetch(url)
                base = urllib.parse.urlparse(final).scheme + "://" + urllib.parse.urlparse(final).netloc
                txt = clean(html)
                nums = adult_day_prices(txt)
                plinks = find_price_links(html, base)
                target = final
                if not nums and plinks:
                    target = plinks[0]
                    html2, _ = fetch(target)
                    txt = clean(html2)
                    nums = adult_day_prices(txt)
                if nums:
                    got = {"min": min(nums), "max": max(nums), "url": target}
                    break
            except Exception:
                got = None
        results[rid] = {"name": name, **(got or {"error": "not found"})}
        time.sleep(0.3)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for rid, r in results.items():
        if "min" in r:
            print(f"{rid} {r['name']:<20} {r['min']:>6}..{r['max']:<6} ₽  {r['url']}")
        else:
            print(f"{rid} {r['name']:<20} НЕ НАЙДЕНО")
    print(f"\nСохранено: {OUT}")


if __name__ == "__main__":
    main()

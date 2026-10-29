#!/usr/bin/env python3
"""Влить курорты из data/raw/resorts_manual.json в data/raw/resort_seed.csv.

Идемпотентно: новые курорты дописываются в конец seed, существующие (по name_ru)
не дублируются. Запускается как шаг пайплайна перед apply_coordinates/geocode.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.collect.manual_inputs import merge_resorts_into_seed  # noqa: E402


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    added = merge_resorts_into_seed()
    print(f"merge_resorts: добавлено курортов в seed: {added}", flush=True)


if __name__ == "__main__":
    main()

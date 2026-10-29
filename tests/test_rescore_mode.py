"""Проверки режима rescore (локальный пересчёт рейтинга и пресетов)."""
import csv
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_pipeline import LOAD, MODES, NETWORK_SCRIPTS, RATING_RESCORE  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _snapshot_scores() -> list[tuple]:
    rows = _read_csv(PROJECT_ROOT / "data" / "mart" / "resort_scores.csv")
    return [
        (r["resort_id"], r["name_ru"], float(r["popularity_score"]), int(r["rank"]))
        for r in rows
    ]


def _snapshot_presets() -> list[tuple]:
    rows = _read_csv(PROJECT_ROOT / "data" / "mart" / "resort_preset_components.csv")
    return [
        (r["preset_id"], r["resort_id"], r["component"],
         float(r["scenario_score"]), int(r["scenario_rank"]))
        for r in rows
    ]


class TestRescoreMode(unittest.TestCase):
    def test_rescore_chain_has_no_network_scripts(self):
        steps = {s[0] for s in RATING_RESCORE}
        self.assertTrue(
            steps.isdisjoint(NETWORK_SCRIPTS),
            f"в rescore есть сетевые скрипты: {steps & NETWORK_SCRIPTS}",
        )
        # rescore полностью локальный; загрузка добавляется отдельно (см. MODES).
        self.assertNotIn(LOAD[0], steps)
        # MODES["rescore"] завершается загрузкой (все витрины — по FK-взаимосвязи).
        load_step = MODES["rescore"][-1]
        self.assertEqual(load_step, LOAD)

    def test_rescore_is_idempotent(self):
        before_scores = _snapshot_scores()
        before_presets = _snapshot_presets()

        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            [sys.executable, "run_pipeline.py", "--mode", "rescore", "--no-load"],
            cwd=str(PROJECT_ROOT), env=env,
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(
            result.returncode, 0,
            f"rescore --no-load упал:\n{result.stdout}\n{result.stderr}",
        )

        after_scores = _snapshot_scores()
        after_presets = _snapshot_presets()

        self.assertEqual(len(before_scores), len(after_scores), "resort_scores: число строк изменилось")
        for a, b in zip(before_scores, after_scores):
            self.assertEqual(a[0], b[0], "resort_id изменился")
            self.assertEqual(a[1], b[1], "name_ru изменился")
            self.assertAlmostEqual(a[2], b[2], places=6, msg=f"popularity_score {a[0]}")
            self.assertEqual(a[3], b[3], f"rank {a[0]}")

        self.assertEqual(len(before_presets), len(after_presets), "presets: число строк изменилось")
        for a, b in zip(before_presets, after_presets):
            self.assertEqual(a[0], b[0], "preset_id изменился")
            self.assertEqual(a[1], b[1], "resort_id изменился")
            self.assertEqual(a[2], b[2], "component изменился")
            self.assertAlmostEqual(a[3], b[3], places=6, msg=f"scenario_score {a[0]}/{a[1]}")
            self.assertEqual(a[4], b[4], f"scenario_rank {a[0]}/{a[1]}")

    def test_base_preset_matches_popularity(self):
        scores = {r["resort_id"]: r for r in _read_csv(PROJECT_ROOT / "data" / "mart" / "resort_scores.csv")}
        rows = [
            r for r in _read_csv(PROJECT_ROOT / "data" / "mart" / "resort_preset_components.csv")
            if r["preset_id"] == "base" and r["component"] == "regional"
        ]
        self.assertEqual(len(rows), 32)
        for r in rows:
            rid = r["resort_id"]
            self.assertAlmostEqual(
                float(r["scenario_score"]),
                float(scores[rid]["popularity_score"]),
                places=6,
                msg=rid,
            )


if __name__ == "__main__":
    unittest.main()

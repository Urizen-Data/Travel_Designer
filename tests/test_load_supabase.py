"""Проверки load_supabase: пайплайн не трогает view и не дропает таблицы."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOAD_SUPABASE = PROJECT_ROOT / "src" / "load" / "load_supabase.py"

FORBIDDEN = [
    "DROP VIEW",
    "CREATE VIEW",
    "pg_get_viewdef",
    "pg_views",
    "views.json",
]


class TestLoadSupabaseNoViews(unittest.TestCase):
    def test_no_view_or_drop_operations(self):
        source = LOAD_SUPABASE.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, source, f"в load_supabase.py найдено '{token}'")


if __name__ == "__main__":
    unittest.main()

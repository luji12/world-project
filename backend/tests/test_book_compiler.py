import tempfile
import unittest
from pathlib import Path

from book_compiler import compile_book
from story_ledger import StoryLedger


class BookCompilerTests(unittest.TestCase):
    def test_compiles_only_approved_chapters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            world_dir = Path(temp_dir) / "world"
            ledger = StoryLedger(world_dir)
            ledger.add_chapter_revision(1, "第一章正文。" * 80)
            approved = ledger.add_chapter_revision(2, "第二章正文。" * 80)
            ledger.approve_chapter(2, approved["revision_no"])

            result = compile_book(world_dir, "测试长篇")

            markdown = Path(result["markdown"]).read_text(encoding="utf-8")
            self.assertEqual(result["chapters"], 1)
            self.assertIn("第2章", markdown)
            self.assertNotIn("第1章", markdown)

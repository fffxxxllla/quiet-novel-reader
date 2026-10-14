import tempfile
import unittest
from pathlib import Path

from library import Bookshelf, canonical_book_url


class BookshelfTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.shelf = Bookshelf(self.root / "config")

    def tearDown(self):
        self.directory.cleanup()

    def test_local_copy_survives_deleted_source_and_duplicate_import(self):
        original = self.root / "长街.txt"
        original.write_text("第1章 雨夜\n窗外下起了雨。", encoding="utf-8")
        entry = self.shelf.archive_file(original)
        duplicate = self.root / "长街的副本.txt"
        duplicate.write_bytes(original.read_bytes())
        self.assertEqual(self.shelf.archive_file(duplicate)["id"], entry["id"])
        original.unlink()
        self.assertIn("窗外下起了雨", Path(entry["path"]).read_text(encoding="utf-8"))
        self.assertEqual([book["title"] for book in self.shelf.entries()], ["长街"])

    def test_progress_and_rename_are_independent_and_persist(self):
        a = self.shelf.remember_web("http://www.kudushu.org/html/1/100/1.html", "第一本书")
        b = self.shelf.remember_web("https://www.kudushu.org/html/1/200/1.html", "第二本书")
        self.shelf.save_progress(a["id"], {"kind": "web", "scroll": 152, "chapter": {"title": "第2章", "text": "甲"}})
        self.shelf.save_progress(b["id"], {"kind": "web", "scroll": 68, "chapter": {"title": "第3章", "text": "乙"}})
        self.shelf.rename(a["id"], "我改的书名")
        a2 = self.shelf.remember_web("https://www.kudushu.org/html/1/100/2.html", "网站上的名称")
        self.assertEqual(a2["title"], "我改的书名")
        restored = Bookshelf(self.root / "config")
        self.assertEqual(len(restored.entries()), 2)
        self.assertEqual(restored.progress(a["id"])["scroll"], 152)
        self.assertEqual(restored.progress(b["id"])["scroll"], 68)
        self.assertEqual(restored.progress(a["id"])["chapter"]["text"], "甲")

    def test_removing_book_keeps_copy_and_does_not_reappear_on_autosave(self):
        entry = self.shelf.remember_web("https://example.com/books/1/2.html", "书名")
        self.shelf.remove(entry["id"])
        self.shelf.save_progress(entry["id"], {"kind": "web", "chapter": {"text": "缓存正文"}})
        self.shelf.remember_web("https://example.com/books/1/3.html", reveal=False)
        self.assertEqual(self.shelf.entries(), [])
        self.assertEqual(self.shelf.progress(entry["id"])["chapter"]["text"], "缓存正文")
        self.shelf.remember_web("https://example.com/books/1/3.html")
        self.assertEqual(len(self.shelf.entries()), 1)

    def test_query_book_ids_remain_distinct(self):
        self.assertEqual(canonical_book_url("http://example.com/read?book=1&chapter=2"),
                         canonical_book_url("https://example.com/read?book=1&chapter=3"))
        self.assertNotEqual(canonical_book_url("https://example.com/read?book=1&chapter=2"),
                            canonical_book_url("https://example.com/read?book=2&chapter=2"))


if __name__ == "__main__":
    unittest.main()

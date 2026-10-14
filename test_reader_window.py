"""Regression checks for pointer routing and persisted reading appearance."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QFont, QFontDatabase, QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtTest import QTest

from app import ReaderWindow, SettingsDialog, load_settings, save_settings
from bookshelf_ui import BookshelfDialog


class ReaderWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.platform = patch.dict(os.environ, {"QT_QPA_PLATFORM": "windows" if sys.platform == "win32" else "offscreen"})
        cls.platform.start()
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.platform.stop()

    def setUp(self):
        self.config = tempfile.TemporaryDirectory(prefix=".reader-test-", dir=Path(__file__).parent)
        self.environment = patch.dict(os.environ, {"QNR_CONFIG_DIR": self.config.name})
        self.environment.start()
        settings = load_settings()
        settings["shortcuts"]["global_close"] = ""
        settings["shortcuts"]["global_toggle_top"] = ""
        save_settings(settings)
        self.window = ReaderWindow()
        self.window.setGeometry(300, 200, 590, 430)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.environment.stop()
        self.config.cleanup()

    def drag(self, widget, position, delta, modifiers=Qt.NoModifier):
        start = widget.mapToGlobal(position)
        end = start + delta
        for kind, global_position, button, buttons in (
            (QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton),
            (QEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton),
            (QEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton),
        ):
            local_position = widget.mapFromGlobal(global_position)
            event = QMouseEvent(kind, QPointF(local_position), QPointF(global_position), button, buttons, modifiers)
            self.app.sendEvent(widget, event)
            self.app.processEvents()

    def test_edges_and_corners_resize_after_dragging_text(self):
        viewport = self.window.reader.viewport()
        original = self.window.geometry()
        self.drag(viewport, viewport.rect().center(), QPoint(35, 25))
        self.assertEqual(self.window.geometry(), original.translated(35, 25))
        cases = (
            (QPoint(5, 210), QPoint(-30, 0), QRect(270, 200, 620, 430)),
            (QPoint(585, 210), QPoint(30, 0), QRect(300, 200, 620, 430)),
            (QPoint(290, 5), QPoint(0, -20), QRect(300, 180, 590, 450)),
            (QPoint(290, 425), QPoint(0, 20), QRect(300, 200, 590, 450)),
            (QPoint(5, 5), QPoint(-30, -20), QRect(270, 180, 620, 450)),
            (QPoint(585, 5), QPoint(30, -20), QRect(300, 180, 620, 450)),
            (QPoint(5, 425), QPoint(-30, 20), QRect(270, 200, 620, 450)),
            (QPoint(585, 425), QPoint(30, 20), QRect(300, 200, 620, 450)),
        )
        for position, delta, expected in cases:
            with self.subTest(position=position):
                self.window.setGeometry(original)
                self.app.processEvents()
                self.drag(self.window, position, delta)
                self.assertEqual(self.window.geometry(), expected)

    def test_resize_zone_inside_viewport_does_not_move_window(self):
        viewport = self.window.reader.viewport()
        self.drag(viewport, QPoint(0, viewport.height() // 2), QPoint(-40, 0))
        self.assertEqual(self.window.geometry(), QRect(260, 200, 630, 430))

    def test_corner_resize_respects_minimum_and_keeps_opposite_corner(self):
        original = self.window.geometry()
        self.drag(self.window, QPoint(5, 5), QPoint(1000, 1000))
        self.assertEqual(self.window.size(), self.window.minimumSize())
        self.assertEqual(self.window.geometry().bottomRight(), original.bottomRight())

    def test_shift_drag_can_select_text_without_moving(self):
        self.window.set_chapter("测试章节", "这是用于测试文字选择的一段小说正文。" * 100)
        self.app.processEvents()
        original = self.window.geometry()
        self.drag(self.window.reader.viewport(), QPoint(50, 60), QPoint(160, 40), Qt.ShiftModifier)
        self.assertEqual(self.window.geometry(), original)
        self.assertTrue(self.window.reader.textCursor().hasSelection())

    def test_font_and_spacing_apply_to_new_chapters_and_survive_restart(self):
        family = next(name for name in QFontDatabase.families() if name != self.window.reader.font().family())
        dialog = SettingsDialog(self.window.settings)
        dialog.font_family.setCurrentFont(QFont(family))
        dialog.font_size.setValue(24)
        dialog.line_spacing.setValue(1.85)
        dialog.save()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        save_settings(dialog.result_settings)
        self.window.settings = dialog.result_settings
        self.window.set_chapter("新章节", "正文第一段。\n正文第二段。")
        self.assertEqual(self.window.reader.font().family(), family)
        self.assertEqual(self.window.reader.font().pointSize(), 24)
        block = self.window.reader.document().begin()
        while block.isValid():
            self.assertEqual(block.blockFormat().lineHeight(), 185)
            block = block.next()
        restored = ReaderWindow()
        try:
            self.assertEqual(restored.settings["font_family"], family)
            self.assertEqual(restored.settings["line_spacing"], 1.85)
            self.assertEqual(restored.reader.font().family(), family)
            self.assertEqual(restored.reader.document().begin().blockFormat().lineHeight(), 185)
        finally:
            restored.close()

    def test_old_settings_receive_default_font_and_spacing(self):
        legacy = load_settings()
        del legacy["font_family"]
        del legacy["line_spacing"]
        save_settings(legacy)
        restored = load_settings()
        self.assertEqual(restored["font_family"], "Microsoft YaHei")
        self.assertEqual(restored["line_spacing"], 1.45)

    def test_switching_books_restores_separate_progress_without_original_files(self):
        a = Path(self.config.name) / "第一本书.txt"
        b = Path(self.config.name) / "第二本书.txt"
        text = "第1章 开始\n" + ''.join(f"第{i}段，窗外下起了雨。\n" for i in range(100))
        text += "第2章 继续\n" + ''.join(f"第{i}段，他翻开了一本书。\n" for i in range(100))
        a.write_text(text, encoding="utf-8")
        b.write_text(text + "不同的结局。", encoding="utf-8")
        self.window.open_local_book(a)
        QTest.qWait(150)
        a_id = self.window.current_book_id
        self.window.next_chapter()
        self.window.scroll(170)
        self.window.open_local_book(b)
        QTest.qWait(150)
        b_id = self.window.current_book_id
        self.window.scroll(80)
        a.unlink()
        b.unlink()
        self.assertTrue(self.window.open_shelf_book(a_id))
        QTest.qWait(150)
        self.assertEqual(self.window.current_book_title, "第一本书")
        self.assertEqual(self.window.local_index, 1)
        self.assertEqual(self.window.reader.verticalScrollBar().value(), 170)
        self.assertTrue(self.window.open_shelf_book(b_id))
        QTest.qWait(150)
        self.assertEqual(self.window.reader.verticalScrollBar().value(), 80)

    def test_old_web_record_migrates_and_shelf_opens_with_one_click(self):
        self.window._saved_session = {
            "kind": "web", "chapter": {"title": "第142章", "text": "缓存小说正文。" * 80,
            "url": "http://www.kudushu.org/html/1078/1078672/144441642.html"}, "scroll": 50,
        }
        self.window.restore_progress()
        QTest.qWait(150)
        book_id = self.window.current_book_id
        self.assertEqual(len(self.window.bookshelf.entries()), 1)
        self.assertIn("缓存小说正文", self.window.bookshelf.progress(book_id)["chapter"]["text"])
        dialog = BookshelfDialog(self.window.bookshelf)
        dialog.show()
        self.app.processEvents()
        rect = dialog.list.visualItemRect(dialog.list.item(0))
        QTest.mouseClick(dialog.list.viewport(), Qt.LeftButton, pos=rect.center())
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.book_id, book_id)
        dialog.close()


if __name__ == "__main__":
    unittest.main()

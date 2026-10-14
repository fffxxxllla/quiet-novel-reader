"""Offline checks run by both the source and the frozen Windows application."""

import json
import os
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView


def run_checks(app, report_path: Path) -> int:
    from app import ReaderWindow, load_settings, save_settings
    from bookshelf_ui import BookshelfDialog
    from extractor import extract_page

    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get("QNR_CONFIG_DIR")
    result = {"ok": False, "checks": []}
    window = web = None
    with tempfile.TemporaryDirectory(prefix="reader-check-", dir=report_path.parent) as temporary:
        os.environ["QNR_CONFIG_DIR"] = temporary
        try:
            settings = load_settings()
            settings["shortcuts"]["global_close"] = ""
            settings["shortcuts"]["global_toggle_top"] = ""
            settings["line_spacing"] = 1.8
            save_settings(settings)
            window = ReaderWindow()
            window.show()
            app.processEvents()
            source = Path(temporary) / "应用测试书.txt"
            source.write_text("第1章 开始\n" + "书页外是一场安静的雨。\n" * 100, encoding="utf-8")
            window.open_local_book(source)
            book_id = window.current_book_id
            source.unlink()
            assert window.open_shelf_book(book_id)
            result["checks"].append("managed local book survives deleted source")
            dialog = BookshelfDialog(window.bookshelf)
            assert dialog.list.count() == 1
            assert "应用测试书" in dialog.list.item(0).text()
            dialog.choose(dialog.list.item(0))
            assert dialog.book_id == book_id
            result["checks"].append("bookshelf displays title and opens selection")
            assert window.reader.document().begin().blockFormat().lineHeight() == 180
            result["checks"].append("saved reading appearance applies")
            dialog.close()
            web = QWebEngineView()
            def parsed(html):
                try:
                    chapter = extract_page(html, "https://example.com/book/1/1.html")
                    assert chapter.kind == "chapter"
                    assert "安静的雨" in chapter.text
                    result["checks"].append("bundled WebEngine renders HTML and text extraction works")
                    result["ok"] = True
                except Exception:
                    result["error"] = traceback.format_exc()
                app.quit()
            def loaded(success):
                if success:
                    web.page().toHtml(parsed)
                else:
                    result["error"] = "WebEngine could not render local HTML"
                    app.quit()
            web.loadFinished.connect(loaded)
            web.setHtml("<html><h1>第1章 开始</h1><article>" + ''.join(f"<p>第{i}段：窗外是一场安静的雨，读者翻开了手里的旧书，故事就这样开始了。</p>" for i in range(8)) + "</article></html>")
            QTimer.singleShot(30000, app.quit)
            app.exec()
            if not result["ok"] and "error" not in result:
                result["error"] = "WebEngine check timed out"
        except Exception:
            result["error"] = traceback.format_exc()
        finally:
            if web is not None:
                web.close()
                web.deleteLater()
            if window is not None:
                window.close()
            app.processEvents()
            if previous is None:
                os.environ.pop("QNR_CONFIG_DIR", None)
            else:
                os.environ["QNR_CONFIG_DIR"] = previous
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1

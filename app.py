"""Minimal floating novel reader for Windows."""

from __future__ import annotations

import json
import os
import sys
import ctypes
import argparse
import hashlib
from ctypes import wintypes
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QEvent, QPoint, QRect, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QShortcut, QTextBlockFormat, QTextCursor
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QDialog, QDoubleSpinBox, QFileDialog, QFontComboBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMenu, QMessageBox, QPushButton,
    QScrollBar, QSlider, QTextEdit, QVBoxLayout, QWidget, QKeySequenceEdit,
)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from extractor import Chapter, PageInfo, chapters_from_epub, chapters_from_txt, extract_page
from global_hotkey import GlobalCloseHotkey, GlobalHotkey, TOP_HOTKEY_ID, windows_hotkey
from library import Bookshelf
from bookshelf_ui import BookshelfDialog


APP_NAME = "静读"
APP_VERSION = "1.1.0"
DEFAULT_KEYS = {
    "next_page": "PgDown", "previous_page": "PgUp",
    "scroll_down": "Down", "scroll_up": "Up",
    "next_chapter": "Alt+Right", "previous_chapter": "Alt+Left",
    "global_close": "Ctrl+Alt+Q",
    "global_toggle_top": "Ctrl+Alt+T",
    "bookshelf": "Ctrl+B",
}
KEY_LABELS = {
    "next_page": "下一页", "previous_page": "上一页",
    "scroll_down": "向下滑动", "scroll_up": "向上滑动",
    "next_chapter": "下一章", "previous_chapter": "上一章",
    "bookshelf": "打开书架",
}


def settings_path() -> Path:
    override = os.environ.get("QNR_CONFIG_DIR")
    root = Path(override) if override else Path(os.environ.get("APPDATA", str(Path.home()))) / "QuietNovelReader"
    return root / "settings.json"


def session_path() -> Path:
    return settings_path().with_name("session.json")


def load_settings() -> dict:
    result = {
        "opacity": 78, "background": "#1d2330", "text_color": "#f5f0e7",
        "font_family": "Microsoft YaHei", "font_size": 16, "line_spacing": 1.45,
        "always_on_top": False, "shortcuts": DEFAULT_KEYS.copy(),
    }
    try:
        saved = json.loads(settings_path().read_text(encoding="utf-8"))
        for key in ("opacity", "background", "text_color", "font_family", "font_size", "line_spacing", "always_on_top"):
            if key in saved:
                result[key] = saved[key]
        if isinstance(saved.get("shortcuts"), dict):
            result["shortcuts"].update(saved["shortcuts"])
    except (OSError, ValueError, TypeError):
        pass
    return result


def save_settings(data: dict) -> None:
    target = settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def load_session() -> dict:
    try:
        data = json.loads(session_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_session(data: dict) -> None:
    target = session_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


def set_native_topmost(window: QWidget, enabled: bool) -> bool:
    """Change Windows z-order without recreating the translucent Qt window."""
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = (
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    )
    user32.SetWindowPos.restype = wintypes.BOOL
    insert_after = wintypes.HWND(-1 if enabled else -2)
    flags = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
    return bool(user32.SetWindowPos(wintypes.HWND(int(window.winId())), insert_after, 0, 0, 0, 0, flags))


class ChapterPicker(QDialog):
    def __init__(self, chapters: list[tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("选择章节")
        self.resize(480, 560)
        self.chapters = chapters
        self.selected_url = ""
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索章节")
        self.list = QListWidget()
        layout.addWidget(self.search)
        layout.addWidget(self.list)
        self.search.textChanged.connect(self.populate)
        self.list.itemDoubleClicked.connect(lambda _: self.choose())
        select = QPushButton("打开所选章节")
        select.clicked.connect(self.choose)
        layout.addWidget(select)
        self.populate()

    def populate(self) -> None:
        phrase = self.search.text().strip().lower()
        self.list.clear()
        for title, url in self.chapters:
            if phrase in title.lower():
                self.list.addItem(title)
                self.list.item(self.list.count() - 1).setData(Qt.UserRole, url)
        if self.list.count():
            self.list.setCurrentRow(0)

    def choose(self) -> None:
        item = self.list.currentItem()
        if item:
            self.selected_url = item.data(Qt.UserRole)
            self.accept()


class BrowserImport(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("导入小说网址")
        self.resize(1050, 760)
        self.result: PageInfo | None = None
        self.chapters: list[tuple[str, str]] = []
        self._auto_extract = False
        self._background_callback = None
        self._index_title = ""
        self._index_url = ""
        profile_path = settings_path().parent / "browser"
        profile_path.mkdir(parents=True, exist_ok=True)
        self.profile = QWebEngineProfile("QuietNovelReader", QApplication.instance())
        self.profile.setPersistentStoragePath(str(profile_path / "storage"))
        self.profile.setCachePath(str(profile_path / "cache"))
        self.profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.address = QLineEdit()
        self.address.setPlaceholderText("输入小说目录或具体章节网址")
        go = QPushButton("打开")
        go.clicked.connect(self.navigate)
        external = QPushButton("系统浏览器")
        external.setToolTip("在默认浏览器打开当前网址")
        external.clicked.connect(self.open_external)
        self.address.returnPressed.connect(self.navigate)
        top.addWidget(self.address, 1)
        top.addWidget(go)
        top.addWidget(external)
        layout.addLayout(top)
        self.web = QWebEngineView()
        self.web.setPage(QWebEnginePage(self.profile, self.web))
        self.web.settings().setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        self.web.settings().setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        self.web.urlChanged.connect(self._url_changed)
        self.web.loadFinished.connect(self._load_finished)
        layout.addWidget(self.web, 3)
        book_row = QHBoxLayout()
        book_row.addWidget(QLabel("书名"))
        self.book_name = QLineEdit()
        self.book_name.setPlaceholderText("自动识别，可修改；保存后显示在书架中")
        book_row.addWidget(self.book_name, 1)
        layout.addLayout(book_row)
        bottom = QHBoxLayout()
        self.selector = QLineEdit()
        self.selector.setPlaceholderText("可选：正文 CSS 选择器，如 #content")
        extract = QPushButton("提取当前页")
        extract.clicked.connect(self.extract_now)
        paste = QPushButton("剪贴板提取")
        paste.setToolTip("系统浏览器可正常阅读时，复制章节正文后在这里提取")
        paste.clicked.connect(self.extract_clipboard)
        self.confirm = QPushButton("确认阅读")
        self.confirm.setEnabled(False)
        self.confirm.clicked.connect(self.confirm_reading)
        bottom.addWidget(self.selector, 1)
        bottom.addWidget(extract)
        bottom.addWidget(paste)
        bottom.addWidget(self.confirm)
        layout.addLayout(bottom)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("正文预览会显示在这里。目录页会弹出章节选择。")
        self.preview.setMaximumHeight(145)
        layout.addWidget(self.preview, 1)

    def start(self, url: str = "") -> None:
        self.result = None
        self.chapters = []
        self._index_title = ""
        self._index_url = ""
        self.book_name.clear()
        self.selector.clear()
        self.confirm.setEnabled(False)
        self.preview.clear()
        self.show()
        self.raise_()
        if url:
            self.address.setText(url)
            self.navigate()
        elif not self.web.url().isValid():
            self.address.setText("https://www.kudushu.org/")
            self.navigate()

    def _url_changed(self, url: QUrl) -> None:
        self.address.setText(url.toString())
        self.result = None
        self.confirm.setEnabled(False)
        self.preview.clear()

    def navigate(self) -> None:
        url = self.address.text().strip().rstrip("，,。.)）")
        if url and not urlparse(url).scheme:
            url = "https://" + url
        if urlparse(url).scheme not in {"http", "https"}:
            QMessageBox.warning(self, APP_NAME, "请输入 http 或 https 网址。")
            return
        self.result = None
        self.confirm.setEnabled(False)
        self.web.setUrl(QUrl(url))

    def open_external(self) -> None:
        url = self.web.url() if self.web.url().isValid() else QUrl(self.address.text().strip())
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)

    def _load_finished(self, success: bool) -> None:
        if not self._auto_extract:
            return
        self._auto_extract = False
        if not success:
            self._deliver(PageInfo("error", url=self.web.url().toString(), message="网页加载失败；请检查网络和网址。"))
            return
        self.extract_now()

    def extract_now(self) -> None:
        self.web.page().toHtml(self._parse_html)

    def extract_clipboard(self) -> None:
        clipboard = QApplication.clipboard().mimeData()
        if clipboard is None:
            self.preview.setPlainText("剪贴板为空。")
            return
        url = self.address.text().strip().rstrip("，,。.)）")
        if urlparse(url).scheme not in {"http", "https"}:
            url = "https://local.example/"
        if clipboard.hasHtml():
            try:
                info = extract_page(clipboard.html(), url, self.selector.text().strip() or None)
            except ValueError as exc:
                self.preview.setPlainText(str(exc))
                return
            if info.kind == "chapter":
                self._deliver(info)
                return
            if info.kind in {"index", "verification"}:
                self.preview.setPlainText("请在系统浏览器中打开具体章节，只选中正文后复制。")
                return
        if clipboard.hasText():
            text = clipboard.text().replace("\r\n", "\n").replace("\r", "\n")
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            if lines and len("".join(lines)) >= 60 and "Just a moment" not in text:
                title = lines[0] if len(lines[0]) <= 45 and ("章" in lines[0] or "节" in lines[0]) else "网页正文"
                body = lines[1:] if title != "网页正文" else lines
                self._deliver(PageInfo("chapter", title, "\n\n".join(body), url))
                return
        self.preview.setPlainText("剪贴板里没有足够的正文。请在系统浏览器中选中章节文字、复制后重试。")

    def _parse_html(self, html: str) -> None:
        try:
            info = extract_page(html, self.web.url().toString(), self.selector.text().strip() or None)
        except ValueError as exc:
            info = PageInfo("error", message=str(exc))
        self._deliver(info)

    def _deliver(self, info: PageInfo) -> None:
        if self._background_callback is not None:
            callback = self._background_callback
            self._background_callback = None
            callback(info)
            return
        if info.kind == "index":
            self._index_title = info.book_title or info.title
            self._index_url = info.book_url or info.url
            self.book_name.setText(self._index_title)
            self.chapters = info.chapters
            self.preview.setPlainText(f"识别到目录：{len(info.chapters)} 章。请选择要阅读的章节。")
            picker = ChapterPicker(info.chapters, self)
            if picker.exec() == QDialog.Accepted:
                self.load_chapter(picker.selected_url)
            return
        if info.kind != "chapter":
            self.preview.setPlainText(info.message)
            self.confirm.setEnabled(False)
            return
        self.result = info
        if not self.book_name.text().strip():
            self.book_name.setText(info.book_title or self._index_title)
        if self._index_url and not info.book_title:
            info.book_title = self._index_title
            info.book_url = self._index_url
        self.preview.setPlainText(f"{info.title}\n\n{info.text[:900]}")
        self.confirm.setEnabled(True)

    def confirm_reading(self) -> None:
        if self.result is not None:
            self.result.book_title = self.book_name.text().strip() or self.result.book_title
            self.accept()

    def load_chapter(self, url: str, callback=None) -> None:
        self._background_callback = callback
        self._auto_extract = True
        self.web.setUrl(QUrl(url))


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("阅读设置")
        self.setMinimumWidth(420)
        self.result_settings = dict(settings)
        self.result_settings["shortcuts"] = settings["shortcuts"].copy()
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(15, 100)
        self.opacity.setValue(int(settings["opacity"]))
        self.opacity_label = QLabel(f'{self.opacity.value()}%')
        self.opacity.valueChanged.connect(lambda value: self.opacity_label.setText(f"{value}%"))
        row = QHBoxLayout()
        row.addWidget(self.opacity, 1)
        row.addWidget(self.opacity_label)
        form.addRow("背景不透明度", row)
        self.font_family = QFontComboBox()
        self.font_family.setCurrentFont(QFont(settings["font_family"]))
        form.addRow("字体", self.font_family)
        self.font_size = QSlider(Qt.Horizontal)
        self.font_size.setRange(12, 40)
        self.font_size.setValue(int(settings["font_size"]))
        self.font_label = QLabel(str(self.font_size.value()))
        self.font_size.valueChanged.connect(lambda value: self.font_label.setText(str(value)))
        row = QHBoxLayout()
        row.addWidget(self.font_size, 1)
        row.addWidget(self.font_label)
        form.addRow("字号", row)
        self.line_spacing = QDoubleSpinBox()
        self.line_spacing.setRange(1.0, 3.0)
        self.line_spacing.setSingleStep(0.05)
        self.line_spacing.setDecimals(2)
        self.line_spacing.setSuffix(" 倍")
        self.line_spacing.setValue(float(settings["line_spacing"]))
        form.addRow("行间距", self.line_spacing)
        self.bg_button = QPushButton(settings["background"])
        self.bg_button.clicked.connect(lambda: self.choose_color("background", self.bg_button))
        form.addRow("背景颜色", self.bg_button)
        self.text_button = QPushButton(settings["text_color"])
        self.text_button.clicked.connect(lambda: self.choose_color("text_color", self.text_button))
        form.addRow("文字颜色", self.text_button)
        layout.addLayout(form)
        layout.addWidget(QLabel("阅读快捷键（阅读窗有焦点时生效）"))
        self.key_edits: dict[str, QKeySequenceEdit] = {}
        key_form = QFormLayout()
        for name, label in KEY_LABELS.items():
            edit = QKeySequenceEdit(QKeySequence(settings["shortcuts"].get(name, "")))
            edit.setClearButtonEnabled(True)
            self.key_edits[name] = edit
            key_form.addRow(label, edit)
        layout.addLayout(key_form)
        layout.addWidget(QLabel("全局快捷键（切换到其他窗口时也生效）"))
        global_form = QFormLayout()
        self.global_key_edit = QKeySequenceEdit(QKeySequence(settings["shortcuts"].get("global_close", "")))
        self.global_key_edit.setClearButtonEnabled(True)
        global_form.addRow("快速关闭阅读器", self.global_key_edit)
        self.global_top_edit = QKeySequenceEdit(QKeySequence(settings["shortcuts"].get("global_toggle_top", "")))
        self.global_top_edit.setClearButtonEnabled(True)
        global_form.addRow("切换窗口置顶", self.global_top_edit)
        layout.addLayout(global_form)
        buttons = QHBoxLayout()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        apply = QPushButton("保存")
        apply.clicked.connect(self.save)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        layout.addLayout(buttons)

    def choose_color(self, key: str, button: QPushButton) -> None:
        color = QColorDialog.getColor(QColor(self.result_settings[key]), self, "选择颜色")
        if color.isValid():
            self.result_settings[key] = color.name()
            button.setText(color.name())

    def save(self) -> None:
        shortcuts = {
            name: edit.keySequence().toString(QKeySequence.PortableText)
            for name, edit in self.key_edits.items()
        }
        shortcuts["global_close"] = self.global_key_edit.keySequence().toString(QKeySequence.PortableText)
        shortcuts["global_toggle_top"] = self.global_top_edit.keySequence().toString(QKeySequence.PortableText)
        active = [value for value in shortcuts.values() if value]
        if len(active) != len(set(active)):
            QMessageBox.warning(self, APP_NAME, "快捷键不能重复。")
            return
        for name in ("global_close", "global_toggle_top"):
            if not shortcuts[name]:
                continue
            try:
                windows_hotkey(shortcuts[name])
            except ValueError as exc:
                QMessageBox.warning(self, APP_NAME, str(exc))
                return
        self.result_settings["opacity"] = self.opacity.value()
        self.result_settings["font_family"] = self.font_family.currentFont().family()
        self.result_settings["font_size"] = self.font_size.value()
        self.result_settings["line_spacing"] = self.line_spacing.value()
        self.result_settings["shortcuts"] = shortcuts
        self.accept()


class ReaderWindow(QWidget):
    def __init__(self, force_normal: bool = False):
        super().__init__()
        self.settings = load_settings()
        if force_normal:
            self.settings["always_on_top"] = False
            save_settings(self.settings)
        self.local_chapters: list[Chapter] = []
        self.bookshelf = Bookshelf(settings_path().parent)
        self.current_book_id = ""
        self.current_book_title = ""
        self._restore_generation = 0
        self._pending_restore_state: dict | None = None
        self.local_index = 0
        self.current_file = ""
        self.current_remote: PageInfo | None = None
        self.web_index: list[tuple[str, str]] = []
        self.remote_loading = False
        self._restoring_session = False
        self._saved_session = load_session()
        self._session_timer = QTimer(self)
        self._session_timer.setSingleShot(True)
        self._session_timer.setInterval(800)
        self._session_timer.timeout.connect(self.save_progress)
        self.global_hotkey = GlobalCloseHotkey(self.quit_reader)
        self.top_hotkey = GlobalHotkey(self.toggle_top_shortcut, TOP_HOTKEY_ID)
        self._drag_start_global: QPoint | None = None
        self._drag_start_window: QPoint | None = None
        self._resize_edges = Qt.Edges()
        self._resize_start_geometry: QRect | None = None
        self.browser: BrowserImport | None = None
        self.shortcuts: list[QShortcut] = []
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(280, 150)
        self.resize(590, 430)
        self.restore_geometry(self._saved_session)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(17, 15, 17, 15)
        self.reader = QTextEdit()
        self.reader.setReadOnly(True)
        self.reader.setContextMenuPolicy(Qt.NoContextMenu)
        self.reader.setFrameStyle(0)
        self.reader.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.reader.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.reader.setMouseTracking(True)
        self.reader.viewport().setMouseTracking(True)
        self.reader.installEventFilter(self)
        self.reader.viewport().installEventFilter(self)
        self.reader.setPlainText("右键打开书架、导入 TXT / EPUB，或输入小说网址。\n\nCtrl+B 打开书架。")
        layout.addWidget(self.reader)
        self.apply_style()
        self.reader.verticalScrollBar().valueChanged.connect(self.schedule_progress_save)
        self.install_shortcuts()
        errors = []
        for name, hotkey in (("global_close", self.global_hotkey), ("global_toggle_top", self.top_hotkey)):
            success, error = hotkey.register(self.settings["shortcuts"].get(name, ""))
            if not success:
                errors.append(error)
        if errors:
            QTimer.singleShot(0, lambda: QMessageBox.warning(self, APP_NAME, "\n".join(errors)))
        QTimer.singleShot(0, self.apply_topmost)
        QTimer.singleShot(0, self.restore_progress)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.settings["background"])
        color.setAlpha(round(255 * int(self.settings["opacity"]) / 100))
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)

    def apply_style(self) -> None:
        old_scroll = self.reader.verticalScrollBar().value()
        self.reader.setStyleSheet(
            f"QTextEdit {{ background: transparent; border: none; color: {self.settings['text_color']}; }}"
            "QTextEdit QAbstractScrollArea { background: transparent; }"
        )
        self.reader.viewport().setAutoFillBackground(False)
        font = QFont(self.settings["font_family"], int(self.settings["font_size"]))
        self.reader.setFont(font)
        cursor = self.reader.textCursor()
        cursor.select(QTextCursor.Document)
        block = QTextBlockFormat()
        block.setLineHeight(round(float(self.settings["line_spacing"]) * 100), QTextBlockFormat.ProportionalHeight.value)
        cursor.setBlockFormat(block)
        cursor.clearSelection()
        cursor.movePosition(QTextCursor.Start)
        self.reader.setTextCursor(cursor)
        self.reader.verticalScrollBar().setValue(old_scroll)
        self.update()

    def install_shortcuts(self) -> None:
        for shortcut in self.shortcuts:
            shortcut.setParent(None)
            shortcut.deleteLater()
        self.shortcuts.clear()
        functions = {
            "next_page": self.next_page, "previous_page": self.previous_page,
            "scroll_down": lambda: self.scroll(95), "scroll_up": lambda: self.scroll(-95),
            "next_chapter": self.next_chapter, "previous_chapter": self.previous_chapter,
            "bookshelf": self.show_bookshelf,
        }
        for name, handler in functions.items():
            sequence = self.settings["shortcuts"].get(name)
            if sequence:
                shortcut = QShortcut(QKeySequence(sequence), self)
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.activated.connect(handler)
                self.shortcuts.append(shortcut)
        close = QShortcut(QKeySequence("Ctrl+Q"), self)
        close.activated.connect(self.quit_reader)
        self.shortcuts.append(close)

    def show_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        if self.settings["always_on_top"]:
            menu.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        menu.addAction("书架", self.show_bookshelf)
        menu.addSeparator()
        menu.addAction("导入 TXT / EPUB", self.open_file)
        menu.addAction("输入小说网址", self.open_web)
        menu.addSeparator()
        menu.addAction("章节目录", self.show_chapters)
        menu.addAction("上一章", self.previous_chapter)
        menu.addAction("下一章", self.next_chapter)
        menu.addSeparator()
        menu.addAction("阅读设置", self.open_settings)
        top_action = QAction("窗口置顶", menu)
        top_action.setCheckable(True)
        top_action.setChecked(bool(self.settings["always_on_top"]))
        top_action.triggered.connect(self.toggle_top)
        menu.addAction(top_action)
        menu.addAction("关闭", self.quit_reader)
        menu.exec(self.reader.viewport().mapToGlobal(position))

    def open_settings(self) -> None:
        old_keys = {
            name: self.settings["shortcuts"].get(name, "")
            for name in ("global_close", "global_toggle_top")
        }
        self.global_hotkey.unregister()
        self.top_hotkey.unregister()
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            updated = dialog.result_settings
            errors = []
            for name, hotkey in (("global_close", self.global_hotkey), ("global_toggle_top", self.top_hotkey)):
                success, error = hotkey.register(updated["shortcuts"].get(name, ""))
                if not success:
                    updated["shortcuts"][name] = old_keys[name]
                    hotkey.register(old_keys[name])
                    errors.append(error)
            if errors:
                QMessageBox.warning(self, APP_NAME, "\n".join(errors))
            self.settings = updated
            save_settings(self.settings)
            self.apply_style()
            self.install_shortcuts()
            self.schedule_progress_save()
        else:
            self.global_hotkey.register(old_keys["global_close"])
            self.top_hotkey.register(old_keys["global_toggle_top"])

    def toggle_top(self, value: bool) -> None:
        if set_native_topmost(self, value):
            self.settings["always_on_top"] = value
            save_settings(self.settings)
        else:
            QMessageBox.warning(self, APP_NAME, "无法切换窗口置顶状态。")

    def toggle_top_shortcut(self) -> None:
        self.toggle_top(not bool(self.settings["always_on_top"]))

    def apply_topmost(self) -> None:
        if self.settings["always_on_top"]:
            set_native_topmost(self, True)

    def open_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "导入小说", "", "小说文件 (*.txt *.epub)")
        if not name:
            return
        try:
            self.open_local_book(Path(name))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, f"导入失败：{exc}")

    def open_local_book(self, path: Path) -> None:
        chapters = chapters_from_epub(path) if path.suffix.lower() == ".epub" else chapters_from_txt(path)
        if not chapters:
            raise ValueError("文件中没有可阅读的内容。")
        self.save_progress()
        entry = self.bookshelf.archive_file(path)
        state = self.bookshelf.progress(entry["id"]) or {"kind": "file", "path": entry["path"]}
        state.update(book_id=entry["id"], book_title=entry["title"], path=entry["path"])
        if not self.restore_state(state, chapters):
            raise ValueError("无法打开这本书的阅读记录。")

    def show_bookshelf(self) -> None:
        self.save_progress()
        dialog = BookshelfDialog(self.bookshelf, self)
        if dialog.exec() != QDialog.Accepted:
            return
        if dialog.request == "file":
            self.open_file()
        elif dialog.request == "web":
            self.open_web()
        elif dialog.book_id:
            self.open_shelf_book(dialog.book_id)

    def open_shelf_book(self, book_id: str) -> bool:
        entry = self.bookshelf.get(book_id)
        if entry is None:
            return False
        self.save_progress()
        state = self.bookshelf.progress(book_id)
        if not state and entry["kind"] == "file":
            state = {"kind": "file", "path": entry["path"]}
        state.update(book_id=book_id, book_title=entry["title"])
        if not self.restore_state(state):
            QMessageBox.warning(self, APP_NAME, "这本书暂时无法打开。请重新导入原书或添加网址。")
            return False
        return True

    def cancel_remote_loading(self) -> None:
        self.remote_loading = False
        if self.browser is not None:
            self.browser._background_callback = None
            self.browser._auto_extract = False
            self.browser.web.stop()

    def open_web(self, url: str = "") -> None:
        self.cancel_remote_loading()
        if self.browser is None:
            self.browser = BrowserImport(self)
            self.browser.accepted.connect(self.accept_browser_result)
        self.browser.start(url)

    def accept_browser_result(self) -> None:
        if self.browser is None or self.browser.result is None:
            return
        self.save_progress()
        self._restore_generation += 1
        self._restoring_session = False
        self._pending_restore_state = None
        self.local_chapters = []
        self.current_file = ""
        self.current_book_id = ""
        self.web_index = self.browser.chapters.copy()
        self.show_remote(self.browser.result)

    def show_remote(self, info: PageInfo) -> None:
        if info.kind != "chapter":
            if self.browser:
                self.browser.start()
                self.browser.preview.setPlainText(info.message)
            return
        entry = self.bookshelf.remember_web(info.url, info.book_title, info.book_url, reveal=not self.current_book_id)
        if self.current_book_id and self.current_book_id != entry["id"]:
            self.save_progress()
        self.current_book_id = entry["id"]
        self.current_book_title = entry["title"]
        self.local_chapters = []
        self.current_remote = info
        self.current_file = ""
        self.set_chapter(info.title, info.text)
        self.schedule_progress_save()

    def remote_loaded(self, info: PageInfo) -> None:
        self.remote_loading = False
        entry = self.bookshelf.get(self.current_book_id)
        if entry and entry["kind"] == "web":
            info.book_title = info.book_title or entry["title"]
            info.book_url = entry["book_url"]
        self.show_remote(info)

    def set_chapter(self, title: str, text: str) -> None:
        self.reader.setPlainText(f"{title}\n\n{text}")
        self.apply_style()
        self.reader.verticalScrollBar().setValue(0)
        self.schedule_progress_save()

    def show_chapters(self) -> None:
        if self.local_chapters:
            entries = [(chapter.title, str(i)) for i, chapter in enumerate(self.local_chapters)]
            picker = ChapterPicker(entries, self)
            if picker.exec() == QDialog.Accepted:
                self.local_index = int(picker.selected_url)
                chapter = self.local_chapters[self.local_index]
                self.set_chapter(chapter.title, chapter.text)
        elif self.web_index:
            picker = ChapterPicker(self.web_index, self)
            if picker.exec() == QDialog.Accepted:
                self.load_remote(picker.selected_url)
        else:
            QMessageBox.information(self, APP_NAME, "当前没有章节目录。")

    def scroll(self, distance: int) -> None:
        bar: QScrollBar = self.reader.verticalScrollBar()
        bar.setValue(bar.value() + distance)

    def next_page(self) -> None:
        bar = self.reader.verticalScrollBar()
        if bar.value() >= bar.maximum():
            self.next_chapter()
        else:
            self.scroll(max(80, bar.pageStep() - 35))

    def previous_page(self) -> None:
        bar = self.reader.verticalScrollBar()
        if bar.value() <= bar.minimum():
            self.previous_chapter()
        else:
            self.scroll(-max(80, bar.pageStep() - 35))

    def _remote_neighbor(self, step: int) -> str:
        if self.current_remote is None:
            return ""
        current_url = self.current_remote.url
        for index, (_, url) in enumerate(self.web_index):
            if url == current_url:
                neighbor = index + step
                return self.web_index[neighbor][1] if 0 <= neighbor < len(self.web_index) else ""
        return self.current_remote.next_url if step > 0 else self.current_remote.prev_url

    def next_chapter(self) -> None:
        if self.local_chapters:
            if self.local_index + 1 < len(self.local_chapters):
                self.local_index += 1
                chapter = self.local_chapters[self.local_index]
                self.set_chapter(chapter.title, chapter.text)
        else:
            target = self._remote_neighbor(1)
            if target:
                self.load_remote(target)

    def previous_chapter(self) -> None:
        if self.local_chapters:
            if self.local_index > 0:
                self.local_index -= 1
                chapter = self.local_chapters[self.local_index]
                self.set_chapter(chapter.title, chapter.text)
        else:
            target = self._remote_neighbor(-1)
            if target:
                self.load_remote(target)

    def load_remote(self, url: str) -> None:
        if self.browser is None:
            self.browser = BrowserImport(self)
            self.browser.accepted.connect(self.accept_browser_result)
        if not self.remote_loading:
            self.remote_loading = True
            expected_book = self.current_book_id
            def deliver(info: PageInfo) -> None:
                if self.current_book_id == expected_book:
                    self.remote_loaded(info)
            self.browser.load_chapter(url, deliver)

    def restore_geometry(self, session: dict) -> None:
        values = session.get("geometry")
        if not isinstance(values, list) or len(values) != 4 or not all(isinstance(value, int) for value in values):
            return
        rectangle = QRect(*values)
        if rectangle.width() < 280 or rectangle.height() < 150:
            return
        if any(screen.availableGeometry().intersects(rectangle) for screen in QApplication.screens()):
            self.setGeometry(rectangle)

    def restore_progress(self) -> None:
        self.restore_state(self._saved_session)

    def restore_state(self, session: dict, chapters: list[Chapter] | None = None) -> bool:
        previous_restoring = self._restoring_session
        previous_pending = self._pending_restore_state
        previous_generation = self._restore_generation
        self._restore_generation += 1
        generation = self._restore_generation
        self._restoring_session = True
        try:
            entry = self.bookshelf.get(session.get("book_id", ""))
            if session.get("kind") == "file":
                path = Path(entry["path"] if entry else session["path"])
                if chapters is None:
                    chapters = chapters_from_epub(path) if path.suffix.lower() == ".epub" else chapters_from_txt(path)
                if not chapters:
                    raise ValueError("书籍为空")
                local_index = max(0, min(int(session.get("chapter_index", 0)), len(chapters) - 1))
                if entry is None:
                    entry = self.bookshelf.archive_file(path, session.get("book_title", ""), reveal=False)
                self.cancel_remote_loading()
                self.local_chapters = chapters
                self.local_index = local_index
                self.current_file = entry["path"]
                self.current_remote = None
                self.web_index = []
                chapter = chapters[self.local_index]
                self.set_chapter(chapter.title, chapter.text)
            elif session.get("kind") == "web":
                saved = session.get("chapter", {})
                if not isinstance(saved, dict) or not saved.get("text"):
                    raise ValueError("网页章节记录不完整")
                if entry is None:
                    entry = self.bookshelf.remember_web(str(saved.get("url", "")),
                        session.get("book_title") or saved.get("book_title", ""), saved.get("book_url", ""), reveal=False)
                self.cancel_remote_loading()
                self.local_chapters = []
                self.current_file = ""
                self.current_remote = PageInfo(
                    "chapter", str(saved.get("title", "网页章节")), str(saved["text"]),
                    str(saved.get("url", "")), str(saved.get("prev_url", "")),
                    str(saved.get("next_url", "")),
                    book_title=entry["title"], book_url=entry["book_url"],
                )
                self.web_index = [tuple(item) for item in session.get("web_index", []) if isinstance(item, list) and len(item) == 2]
                self.set_chapter(self.current_remote.title, self.current_remote.text)
            else:
                self._restoring_session = previous_restoring
                self._pending_restore_state = previous_pending
                self._restore_generation = previous_generation
                return False
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            self._restoring_session = previous_restoring
            self._pending_restore_state = previous_pending
            self._restore_generation = previous_generation
            return False
        self.current_book_id = entry["id"]
        self.current_book_title = entry["title"]
        self._pending_restore_state = {**session, "book_id": entry["id"], "book_title": entry["title"]}
        if self.current_file:
            self._pending_restore_state["path"] = self.current_file

        def position_reader() -> None:
            if generation != self._restore_generation:
                return
            bar = self.reader.verticalScrollBar()
            old_max = int(session.get("scroll_max", 0))
            old_value = int(session.get("scroll", 0))
            target = old_value if old_max == bar.maximum() else round(bar.maximum() * old_value / max(1, old_max))
            bar.setValue(max(bar.minimum(), min(target, bar.maximum())))
            self._restoring_session = False
            self._pending_restore_state = None
            self.save_progress()

        QTimer.singleShot(100, position_reader)
        return True

    def schedule_progress_save(self) -> None:
        if not self._restoring_session and (self.current_file or self.current_remote is not None):
            self._session_timer.start()

    def save_progress(self) -> None:
        bar = self.reader.verticalScrollBar()
        rectangle = self.geometry()
        state = {
            "scroll": bar.value(),
            "scroll_max": bar.maximum(),
            "geometry": [rectangle.x(), rectangle.y(), rectangle.width(), rectangle.height()],
        }
        if self._restoring_session and self._pending_restore_state is not None:
            state = {**self._pending_restore_state, "geometry": state["geometry"]}
        elif self.current_file and self.local_chapters:
            state.update(kind="file", path=self.current_file, chapter_index=self.local_index)
            state["chapter_title"] = self.local_chapters[self.local_index].title
        elif self.current_remote is not None:
            state.update(kind="web", chapter=asdict(self.current_remote), web_index=self.web_index)
        else:
            return
        entry = self.bookshelf.get(self.current_book_id)
        if entry:
            state.update(book_id=entry["id"], book_title=entry["title"])
        try:
            save_session(state)
            if entry:
                self.bookshelf.save_progress(entry["id"], state)
        except OSError:
            pass

    def quit_reader(self) -> None:
        if self.browser is not None:
            self.browser.close()
        self.close()
        QApplication.instance().quit()

    def closeEvent(self, event) -> None:
        self._session_timer.stop()
        self.save_progress()
        self._restore_generation += 1
        self.global_hotkey.unregister()
        self.top_hotkey.unregister()
        super().closeEvent(event)

    def resize_edges_at(self, position: QPoint) -> Qt.Edges:
        # Include the inside of the reading area's border in the resize zone.
        margin = 18
        edges = Qt.Edges()
        if position.x() < margin:
            edges |= Qt.LeftEdge
        elif position.x() >= self.width() - margin:
            edges |= Qt.RightEdge
        if position.y() < margin:
            edges |= Qt.TopEdge
        elif position.y() >= self.height() - margin:
            edges |= Qt.BottomEdge
        return edges

    def update_resize_cursor(self, position: QPoint) -> None:
        edges = self._resize_edges if self._resize_start_geometry is not None else self.resize_edges_at(position)
        if edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            shape = Qt.SizeFDiagCursor
        elif edges in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            shape = Qt.SizeBDiagCursor
        elif edges & (Qt.LeftEdge | Qt.RightEdge):
            shape = Qt.SizeHorCursor
        elif edges & (Qt.TopEdge | Qt.BottomEdge):
            shape = Qt.SizeVerCursor
        else:
            shape = Qt.ArrowCursor
        self.setCursor(shape)
        self.reader.setCursor(shape)
        self.reader.viewport().setCursor(shape if edges else Qt.IBeamCursor)

    def begin_pointer_drag(self, position: QPoint, global_position: QPoint, modifiers) -> bool:
        edges = self.resize_edges_at(position)
        if not edges and modifiers & Qt.ShiftModifier:
            return False
        self._drag_start_global = global_position
        self._drag_start_window = self.pos()
        self._resize_edges = edges
        self._resize_start_geometry = self.geometry() if edges else None
        self.update_resize_cursor(position)
        return True

    def move_pointer_drag(self, global_position: QPoint) -> bool:
        if self._drag_start_global is None:
            return False
        delta = global_position - self._drag_start_global
        rectangle = self._resize_start_geometry
        if rectangle is None:
            self.move(self._drag_start_window + delta)
            return True
        x, y, width, height = rectangle.getRect()
        if self._resize_edges & Qt.LeftEdge:
            width = max(self.minimumWidth(), min(self.maximumWidth(), rectangle.width() - delta.x()))
            x = rectangle.x() + rectangle.width() - width
        elif self._resize_edges & Qt.RightEdge:
            width = max(self.minimumWidth(), min(self.maximumWidth(), rectangle.width() + delta.x()))
        if self._resize_edges & Qt.TopEdge:
            height = max(self.minimumHeight(), min(self.maximumHeight(), rectangle.height() - delta.y()))
            y = rectangle.y() + rectangle.height() - height
        elif self._resize_edges & Qt.BottomEdge:
            height = max(self.minimumHeight(), min(self.maximumHeight(), rectangle.height() + delta.y()))
        self.setGeometry(x, y, width, height)
        return True

    def end_pointer_drag(self, position: QPoint) -> bool:
        active = self._drag_start_global is not None
        self._drag_start_global = None
        self._drag_start_window = None
        self._resize_edges = Qt.Edges()
        self._resize_start_geometry = None
        self.update_resize_cursor(position)
        if active:
            self.schedule_progress_save()
        return active

    def eventFilter(self, watched, event) -> bool:
        if watched is self.reader or watched is self.reader.viewport():
            if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.RightButton:
                self.show_menu(watched.mapTo(self.reader.viewport(), event.position().toPoint()))
                return True
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                if self.begin_pointer_drag(watched.mapTo(self, event.position().toPoint()), event.globalPosition().toPoint(), event.modifiers()):
                    return True
            elif event.type() == QEvent.MouseMove:
                if self.move_pointer_drag(event.globalPosition().toPoint()):
                    return True
                self.update_resize_cursor(watched.mapTo(self, event.position().toPoint()))
            elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                if self.end_pointer_drag(watched.mapTo(self, event.position().toPoint())):
                    return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.begin_pointer_drag(event.position().toPoint(), event.globalPosition().toPoint(), event.modifiers()):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.move_pointer_drag(event.globalPosition().toPoint()):
            event.accept()
            return
        self.update_resize_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.end_pointer_drag(event.position().toPoint()):
            event.accept()
            return
        super().mouseReleaseEvent(event)


def main() -> None:
    parser = argparse.ArgumentParser(description="静读小说阅读器")
    parser.add_argument("--no-top", action="store_true")
    parser.add_argument("--bookshelf", action="store_true")
    parser.add_argument("--self-check", metavar="REPORT")
    arguments, qt_arguments = parser.parse_known_args()
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("QuietNovelReader.JingDu.1")
    app = QApplication([sys.argv[0], *qt_arguments])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("assets") / "reader.ico")))
    if arguments.self_check:
        from self_check import run_checks
        sys.exit(run_checks(app, Path(arguments.self_check)))
    name = "QuietNovelReader-" + hashlib.sha256(str(settings_path().resolve()).casefold().encode()).hexdigest()[:20]
    socket = QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(300):
        socket.write(b"bookshelf" if arguments.bookshelf else b"activate")
        socket.flush()
        socket.waitForBytesWritten(300)
        return
    QLocalServer.removeServer(name)
    server = QLocalServer()
    if not server.listen(name):
        QMessageBox.warning(None, APP_NAME, "阅读器已在启动，请稍后再试。")
        return
    window = ReaderWindow(force_normal=arguments.no_top)
    def activate_existing() -> None:
        connection = server.nextPendingConnection()
        if connection is None:
            return
        if not connection.bytesAvailable():
            connection.waitForReadyRead(300)
        command = bytes(connection.readAll())
        connection.disconnectFromServer()
        connection.deleteLater()
        target = app.activeModalWidget() or window
        target.showNormal()
        target.raise_()
        target.activateWindow()
        if command == b"bookshelf" and target is window:
            QTimer.singleShot(0, window.show_bookshelf)
    server.newConnection.connect(activate_existing)
    window.show()
    if arguments.bookshelf or not window._saved_session:
        QTimer.singleShot(200, window.show_bookshelf)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""A quiet, searchable list of books; a single click resumes reading."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QVBoxLayout,
)

from library import Bookshelf


class BookshelfDialog(QDialog):
    def __init__(self, bookshelf: Bookshelf, parent=None):
        super().__init__(parent)
        self.bookshelf = bookshelf
        self.book_id = ""
        self.request = ""
        self.setWindowTitle("书架 · 静读")
        self.resize(520, 560)
        self.setMinimumSize(360, 320)
        self.setStyleSheet("""
            QDialog { background: #f6f4ef; color: #25362f; }
            QLineEdit, QListWidget { background: #fffefa; color: #25362f; border: 1px solid #dddcd4; border-radius: 7px; }
            QLineEdit { padding: 8px; }
            QListWidget { padding: 5px; outline: none; }
            QListWidget::item { padding: 13px 10px; border-bottom: 1px solid #efeee7; }
            QListWidget::item:hover { background: #e9efe8; }
            QListWidget::item:selected { background: #dce8dc; color: #25362f; }
            QPushButton { padding: 7px 13px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        heading = QLabel("我的书架")
        heading.setFont(QFont("Microsoft YaHei", 19, QFont.Medium))
        layout.addWidget(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索书名")
        self.search.textChanged.connect(self.populate)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setSpacing(2)
        self.list.setWordWrap(True)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        self.list.itemClicked.connect(self.choose)
        self.list.itemActivated.connect(self.choose)
        layout.addWidget(self.list, 1)
        self.empty = QLabel("书架还没有书。\n导入一本书，或添加小说网址。")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color: #727970; padding: 14px;")
        layout.addWidget(self.empty)
        hint = QLabel("点击书名继续阅读 · 右键可重命名或移出书架")
        hint.setStyleSheet("color: #727970; font-size: 11px;")
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        for text, request in (("导入 TXT / EPUB", "file"), ("添加网址", "web")):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, request=request: self.import_request(request))
            buttons.addWidget(button)
        buttons.addStretch()
        close = QPushButton("返回阅读")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.populate()

    def populate(self) -> None:
        self.list.clear()
        phrase = self.search.text().strip().casefold()
        for book in self.bookshelf.entries():
            if phrase not in book["title"].casefold():
                continue
            source = "本地书籍" if book["kind"] == "file" else "网页小说"
            chapter = book.get("chapter_title", "尚未开始阅读")
            item = QListWidgetItem(f"{book['title']}\n{source}  ·  {chapter}")
            item.setData(Qt.UserRole, book["id"])
            item.setForeground(QColor("#25362f"))
            item.setToolTip(book["title"] + "\n" + chapter)
            self.list.addItem(item)
        self.empty.setVisible(self.list.count() == 0)
        self.empty.setText("没有找到这本书。" if phrase else "书架还没有书。\n导入一本书，或添加小说网址。")

    def choose(self, item) -> None:
        self.book_id = item.data(Qt.UserRole)
        self.accept()

    def import_request(self, request: str) -> None:
        self.request = request
        self.accept()

    def context_menu(self, position) -> None:
        item = self.list.itemAt(position)
        if item is None:
            return
        book_id = item.data(Qt.UserRole)
        book = self.bookshelf.get(book_id)
        menu = QMenu(self)
        rename = menu.addAction("重命名")
        remove = menu.addAction("移出书架")
        remove.setToolTip("仅移出列表，已保存的书籍和阅读记录保留。")
        chosen = menu.exec(self.list.viewport().mapToGlobal(position))
        if chosen == rename:
            title, accepted = QInputDialog.getText(self, "重命名", "书名", text=book["title"])
            if accepted and title.strip():
                self.bookshelf.rename(book_id, title)
        elif chosen == remove:
            self.bookshelf.remove(book_id)
        self.populate()

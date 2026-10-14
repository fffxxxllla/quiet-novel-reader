"""A persistent bookshelf with managed local copies and per-book progress."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonical_book_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path
    parts = path.strip("/").split("/")
    if len(parts) >= 3 and re.search(r"\.(?:s?html?|xhtml)$", parts[-1], re.I):
        path = path.rsplit("/", 1)[0] + "/"
    query = [(key, value) for key, value in parse_qsl(parsed.query) if key.lower() not in {
        "chapter", "chapterid", "chapter_id", "cid", "page", "utm_source", "utm_medium", "utm_campaign",
    }]
    # HTTP/HTTPS versions of the same site share their bookshelf entry.
    return urlunsplit(("https", parsed.netloc.lower(), path, urlencode(sorted(query)), ""))


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class Bookshelf:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.index_path = self.root / "library.json"
        stored = _read_json(self.index_path, {})
        rows = stored.get("books", []) if isinstance(stored, dict) else []
        self.books: dict[str, dict] = {
            row["id"]: row for row in rows if isinstance(row, dict)
            and re.fullmatch(r"(?:file|web)-[0-9a-f]{24}", str(row.get("id", "")))
        } if isinstance(rows, list) else {}

    def _save(self) -> None:
        _write_json(self.index_path, {"version": 1, "books": list(self.books.values())})

    def entries(self) -> list[dict]:
        return sorted((dict(book) for book in self.books.values() if not book.get("hidden")),
                      key=lambda book: book.get("last_read", 0), reverse=True)

    def get(self, book_id: str) -> dict | None:
        book = self.books.get(book_id)
        return dict(book) if book else None

    def archive_file(self, source: Path, title: str = "", reveal: bool = True) -> dict:
        source = Path(source).resolve()
        digest = hashlib.sha256(source.suffix.lower().encode())
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        book_id = "file-" + digest.hexdigest()[:24]
        destination = self.root / "books" / book_id / ("source" + source.suffix.lower())
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".tmp")
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
        book = self.books.get(book_id)
        if book is None:
            book = {"id": book_id, "kind": "file", "title": title or source.stem,
                    "path": str(destination), "source_path": str(source), "last_read": time.time()}
            self.books[book_id] = book
        if reveal:
            book["hidden"] = False
        self._save()
        return dict(book)

    def remember_web(self, url: str, title: str = "", book_url: str = "", reveal: bool = True) -> dict:
        key = canonical_book_url(book_url or url)
        book_id = "web-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        book = self.books.get(book_id)
        if book is None:
            book = {"id": book_id, "kind": "web", "title": title or f"网页小说 · {urlsplit(url).netloc}",
                    "book_url": key, "last_read": time.time()}
            self.books[book_id] = book
        elif title and not book.get("custom_title"):
            book["title"] = title
        if reveal:
            book["hidden"] = False
        self._save()
        return dict(book)

    def progress(self, book_id: str) -> dict:
        if book_id not in self.books:
            return {}
        state = _read_json(self.root / "books" / book_id / "progress.json", {})
        return state if isinstance(state, dict) else {}

    def save_progress(self, book_id: str, state: dict) -> None:
        book = self.books.get(book_id)
        if book is None:
            return
        state = {**state, "book_id": book_id, "book_title": book["title"]}
        _write_json(self.root / "books" / book_id / "progress.json", state)
        book["last_read"] = time.time()
        book["chapter_title"] = state.get("chapter_title") or state.get("chapter", {}).get("title", "")
        self._save()

    def rename(self, book_id: str, title: str) -> None:
        if book_id in self.books and title.strip():
            self.books[book_id].update(title=title.strip(), custom_title=True)
            self._save()

    def remove(self, book_id: str) -> None:
        if book_id in self.books:
            self.books[book_id]["hidden"] = True
            self._save()

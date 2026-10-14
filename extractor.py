"""Extract chapter text and navigation from local files or rendered web pages."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup, NavigableString, Tag

from library import canonical_book_url


CHAPTER_RE = re.compile(r"^\s*(第[0-9零一二三四五六七八九十百千万两]+[章节回卷部篇][^\n]{0,55})\s*$")
NOISE_RE = re.compile(
    r"^(?:苦读书推荐各位书友阅读|如果您中途有事离开|如果你喜欢|如果您喜欢|"
    r"加入书签|推荐本书|返回书页|上一页|下一页|上一章|下一章|"
    r"请按\s*CTRL\+D|最新网址[：:]|本章未完|手机用户请)",
    re.I,
)
BLOCK_TAGS = {"p", "div", "section", "article", "h1", "h2", "h3", "li", "blockquote"}
PREFERRED_SELECTORS = (
    "#content", "#chaptercontent", "#chapterContent", "#htmlContent",
    "#readContent", ".chapter-content", ".read-content", ".readContent",
    ".content", ".article-content", "article", "main",
)


@dataclass
class Chapter:
    title: str
    text: str
    url: str = ""


@dataclass
class PageInfo:
    kind: str
    title: str = ""
    text: str = ""
    url: str = ""
    prev_url: str = ""
    next_url: str = ""
    chapters: list[tuple[str, str]] = field(default_factory=list)
    message: str = ""
    book_title: str = ""
    book_url: str = ""


def _node_text(node: Tag) -> str:
    pieces: list[str] = []

    def visit(item: Tag | NavigableString) -> None:
        if isinstance(item, NavigableString):
            pieces.append(str(item))
            return
        if not isinstance(item, Tag) or item.name in {"script", "style", "noscript", "svg", "nav", "footer"}:
            return
        if item.name == "br":
            pieces.append("\n")
            return
        if item.name in BLOCK_TAGS:
            pieces.append("\n")
        for child in item.children:
            visit(child)
        if item.name in BLOCK_TAGS:
            pieces.append("\n")

    visit(node)
    return "".join(pieces)


def _clean_lines(raw: str, kudushu: bool = False) -> str:
    raw = raw.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for part in raw.split("\n"):
        line = re.sub(r"[ \t]+", " ", part).strip()
        if not line:
            continue
        if kudushu:
            line = re.sub(r"^\(?苦读书\s+www\.kudushu\.org\)?\s*", "", line, flags=re.I)
            line = re.sub(r"\s*苦读书\s+www\.kudushu\.org\s*$", "", line, flags=re.I)
            line = line.strip()
            if not line or NOISE_RE.search(line):
                continue
        if lines and line == lines[-1]:
            continue
        lines.append(line)
    return "\n\n".join(lines)


def _title(soup: BeautifulSoup) -> str:
    heading = soup.find("h1")
    if heading:
        result = heading.get_text(" ", strip=True)
        if result:
            return result
    if soup.title:
        return re.split(r"[-_|｜]", soup.title.get_text(" ", strip=True))[0].strip()
    return "未命名章节"


def _book_details(soup: BeautifulSoup, url: str) -> tuple[str, str]:
    name = soup.select_one('meta[property="og:novel:book_name"], meta[name="og:novel:book_name"]')
    book_title = str(name.get("content", "")).strip() if name else ""
    book_url = canonical_book_url(url)
    ignored = {"上一章", "下一章", "上一页", "下一页", "目录", "返回目录", "章节目录", "返回书页", "首页"}
    for anchor in soup.find_all("a", href=True):
        target = urljoin(url, anchor["href"])
        label = anchor.get_text(" ", strip=True)
        if (canonical_book_url(target) == book_url and label and label not in ignored
                and not CHAPTER_RE.match(label) and len(label) <= 80):
            book_title = book_title or label
            break
    if not book_title and soup.title:
        pieces = re.split(r"[_|｜-]", soup.title.get_text(" ", strip=True))
        if len(pieces) >= 3:
            candidate = pieces[-2].strip()
            if candidate and not CHAPTER_RE.match(candidate) and candidate not in ignored:
                book_title = candidate
    return book_title, book_url


def _chapter_links(soup: BeautifulSoup, url: str) -> list[tuple[str, str]]:
    parsed = urlparse(url)
    is_kudushu = parsed.hostname and parsed.hostname.endswith("kudushu.org")
    root = parsed.path.rsplit("/", 1)[0] + "/"
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        label = anchor.get_text(" ", strip=True)
        if not CHAPTER_RE.match(label):
            continue
        target = urljoin(url, anchor["href"])
        target_parsed = urlparse(target)
        if target_parsed.hostname != parsed.hostname or target == url or target in seen:
            continue
        if is_kudushu and (not target_parsed.path.startswith(root) or not target_parsed.path.endswith(".html")):
            continue
        seen.add(target)
        links.append((label, target))
    return links


def _navigation(soup: BeautifulSoup, url: str) -> tuple[str, str]:
    host = urlparse(url).hostname
    previous = next_one = ""
    for anchor in soup.find_all("a", href=True):
        label = re.sub(r"\s+", "", anchor.get_text(" ", strip=True))
        target = urljoin(url, anchor["href"])
        parsed = urlparse(target)
        if parsed.hostname != host or target == url or parsed.path.endswith("/index.html"):
            continue
        if label in {"上一页", "上一章", "上一节"} and not previous:
            previous = target
        elif label in {"下一页", "下一章", "下一节"} and not next_one:
            next_one = target
    return previous, next_one


def _candidate_nodes(soup: BeautifulSoup, selector: str | None) -> list[Tag]:
    if selector:
        try:
            return list(soup.select(selector))
        except Exception as exc:
            raise ValueError(f"CSS 选择器无效：{exc}") from exc
    nodes: list[Tag] = []
    for css in PREFERRED_SELECTORS:
        nodes.extend(soup.select(css))
    nodes.extend(soup.find_all(["div", "section", "article"], limit=200))
    unique: list[Tag] = []
    ids: set[int] = set()
    for node in nodes:
        if id(node) not in ids:
            ids.add(id(node))
            unique.append(node)
    return unique


def extract_page(html: str, url: str, selector: str | None = None) -> PageInfo:
    """Return a chapter or table of contents from browser-rendered HTML."""
    if not urlparse(url).scheme in {"http", "https"}:
        return PageInfo("error", url=url, message="只支持 http 或 https 网址。")
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and "Just a moment" in soup.title.get_text():
        return PageInfo("verification", url=url, message="网站要求浏览器验证。完成验证后重试；如果反复出现，可用“系统浏览器”检查该网站是否允许内嵌浏览器访问。")
    if soup.select_one("#cf-challenge-running, .cf-browser-verification"):
        return PageInfo("verification", url=url, message="网站要求浏览器验证。完成验证后重试；如果反复出现，可用“系统浏览器”检查该网站是否允许内嵌浏览器访问。")

    parsed = urlparse(url)
    kudushu = bool(parsed.hostname and parsed.hostname.endswith("kudushu.org"))
    if kudushu and parsed.path in {"", "/"}:
        return PageInfo("error", url=url, message="这是网站首页。请在浏览器里打开一本书的目录或具体章节。")
    chapter_links = _chapter_links(soup, url)
    title = _title(soup)
    book_title, book_url = _book_details(soup, url)
    best_text = ""
    if selector:
        selected = _candidate_nodes(soup, selector)
        selected_ids = {id(node) for node in selected}
        roots = [node for node in selected if not any(id(parent) in selected_ids for parent in node.parents)]
        best_text = _clean_lines("\n\n".join(_node_text(node) for node in roots), kudushu)
    else:
        best_score = float("-inf")
        for node in _candidate_nodes(soup, None):
            text = _clean_lines(_node_text(node), kudushu)
            if len(text) < 50:
                continue
            link_length = sum(len(a.get_text(" ", strip=True)) for a in node.find_all("a"))
            long_lines = sum(1 for line in text.split("\n\n") if len(line) >= 45)
            score = min(len(text), 20000) + long_lines * 45 - link_length * 4
            if node.name == "article" or node.get("id", "").lower() in {"content", "chaptercontent", "htmlcontent"}:
                score += 180
            if score > best_score:
                best_score, best_text = score, text

    if selector and not best_text:
        return PageInfo("error", title, url=url, message="这个选择器没有找到足够的正文；请检查后重试。")
    paragraphs = best_text.split("\n\n") if best_text else []
    long_paragraphs = sum(1 for line in paragraphs if len(line) >= 45)
    if not selector and len(chapter_links) >= 3 and long_paragraphs < 3:
        return PageInfo("index", title, url=url, chapters=chapter_links, book_title=book_title or title, book_url=book_url)
    if len(best_text) < 60 or (long_paragraphs == 0 and len(paragraphs) < 3):
        if chapter_links:
            return PageInfo("index", title, url=url, chapters=chapter_links, book_title=book_title or title, book_url=book_url)
        return PageInfo("error", title, url=url, message="没有识别到章节正文。请打开具体章节，或手动填写正文 CSS 选择器。")
    previous, next_one = _navigation(soup, url)
    return PageInfo("chapter", title, best_text, url, previous, next_one, book_title=book_title, book_url=book_url)


def chapters_from_txt(path: Path) -> list[Chapter]:
    data = path.read_bytes()
    decoded = ""
    encodings = ("utf-16", "utf-8-sig", "gb18030") if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            decoded = data.decode(encoding)
            break
        except UnicodeError:
            continue
    if not decoded:
        raise ValueError("无法识别文本编码；请另存为 UTF-8 后重试。")
    decoded = decoded.replace("\r\n", "\n").replace("\r", "\n")
    lines = decoded.split("\n")
    starts = [(i, line.strip()) for i, line in enumerate(lines) if CHAPTER_RE.match(line.strip())]
    if not starts:
        return [Chapter(path.stem, _clean_lines(decoded))]
    chapters: list[Chapter] = []
    if starts[0][0] > 0:
        preface = _clean_lines("\n".join(lines[: starts[0][0]]))
        if preface:
            chapters.append(Chapter("序言", preface))
    for index, (start, title) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
        body = _clean_lines("\n".join(lines[start + 1 : end]))
        if body:
            chapters.append(Chapter(title, body))
    return chapters


def chapters_from_epub(path: Path) -> list[Chapter]:
    """Read EPUB spine order without executing or displaying book HTML."""
    with zipfile.ZipFile(path) as book:
        container = ElementTree.fromstring(book.read("META-INF/container.xml"))
        rootfile = container.find(".//{*}rootfile")
        if rootfile is None:
            raise ValueError("EPUB 缺少内容目录。")
        opf_path = rootfile.attrib["full-path"]
        opf = ElementTree.fromstring(book.read(opf_path))
        base = Path(opf_path).parent
        manifest = {
            item.attrib["id"]: item.attrib
            for item in opf.findall(".//{*}manifest/{*}item")
        }
        chapters: list[Chapter] = []
        for reference in opf.findall(".//{*}spine/{*}itemref"):
            item = manifest.get(reference.attrib.get("idref", ""))
            if not item or "html" not in item.get("media-type", ""):
                continue
            name = str((base / item["href"]).as_posix())
            try:
                html = book.read(name)
            except KeyError:
                continue
            soup = BeautifulSoup(html, "html.parser")
            body = soup.body or soup
            text = _clean_lines(_node_text(body))
            if len(text) < 30:
                continue
            heading = body.find(["h1", "h2", "h3"])
            title = heading.get_text(" ", strip=True) if heading else f"第 {len(chapters) + 1} 节"
            chapters.append(Chapter(title, text))
    if not chapters:
        raise ValueError("EPUB 中没有找到可阅读的文字章节。")
    return chapters

import tempfile
import unittest
import zipfile
from pathlib import Path

from extractor import chapters_from_epub, chapters_from_txt, extract_page


class ExtractorTests(unittest.TestCase):
    def test_kudushu_chapter_removes_site_text_and_keeps_navigation(self):
        html = """
        <html><head><title>第一章 雨夜-苦读书</title></head><body>
          <a href="index.html">上一页</a><h1>第一章 雨夜</h1>
          <div id="content">苦读书推荐各位书友阅读：这本书<br>
            (苦读书 www.kudushu.org) 风吹过长街，路灯下的水迹映着窗。<br><br>
            她翻开桌上的旧书，听见楼下有人轻轻敲门，便起身走向楼梯。<br><br>
            门外的人撑着伞，袖口湿了一大片。他说，今晚还有一封信要送来。苦读书 www.kudushu.org
          </div><a href="2.html">下一页</a>
          <p>如果您中途有事离开，请按 CTRL+D 键保存当前页面至收藏夹。</p>
        </body></html>"""
        info = extract_page(html, "https://www.kudushu.org/html/1/2/1.html")
        self.assertEqual(info.kind, "chapter")
        self.assertEqual(info.next_url, "https://www.kudushu.org/html/1/2/2.html")
        self.assertFalse(info.prev_url)
        self.assertIn("她翻开桌上的旧书", info.text)
        self.assertNotIn("苦读书", info.text)

    def test_directory_is_not_mistaken_for_chapter(self):
        anchors = "".join(f'<a href="{i}.html">第{i}章 标题</a>' for i in range(1, 6))
        html = f"<html><h1>书名</h1><div id='content'>{anchors}</div></html>"
        info = extract_page(html, "https://www.kudushu.org/html/1/2/index.html")
        self.assertEqual(info.kind, "index")
        self.assertEqual(len(info.chapters), 5)

    def test_verification_page_is_reported(self):
        info = extract_page("<title>Just a moment...</title>", "https://www.kudushu.org/x")
        self.assertEqual(info.kind, "verification")

    def test_web_book_name_is_extracted_for_bookshelf(self):
        html = '<meta property="og:novel:book_name" content="长街">'
        html += '<h1>第1章 雨夜</h1><article>' + ''.join(f'<p>第{i}段：窗外下起了雨，她翻开手中的书，故事就这样开始了。</p>' for i in range(6)) + '</article>'
        info = extract_page(html, "https://www.kudushu.org/html/1/100/2.html")
        self.assertEqual(info.kind, "chapter")
        self.assertEqual(info.book_title, "长街")
        self.assertEqual(info.book_url, "https://www.kudushu.org/html/1/100/")

    def test_manual_selector_collects_all_matching_paragraphs(self):
        html = """<html><h1>一章</h1><div class="article">
        <p>第一段写下了足够多的内容，确保我们能识别这是一段小说正文而非页面导航。</p>
        <p>第二段紧接着展开情节，这段文字应该和前一段一起进入阅读窗口。</p>
        <p>第三段结束这一节，读者可以在预览里检查所有段落是否齐全。</p>
        </div></html>"""
        info = extract_page(html, "https://example.org/book/1", ".article p")
        self.assertEqual(info.kind, "chapter")
        self.assertIn("第一段", info.text)
        self.assertIn("第三段", info.text)

    def test_txt_and_epub_import(self):
        with tempfile.TemporaryDirectory() as directory:
            txt = Path(directory) / "novel.txt"
            txt.write_text("第1章 开始\n第一段。\n第二段。\n第2章 继续\n第三段。", encoding="utf-8")
            chapters = chapters_from_txt(txt)
            self.assertEqual([c.title for c in chapters], ["第1章 开始", "第2章 继续"])

            epub = Path(directory) / "novel.epub"
            with zipfile.ZipFile(epub, "w") as book:
                book.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
                book.writestr("OPS/book.opf", '<package><manifest><item id="a" href="1.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="a"/></spine></package>')
                book.writestr("OPS/1.xhtml", '<html><body><h1>开篇</h1><p>这是一段足够长的正文，用来验证按书籍顺序读取章节，而不执行网页脚本。</p></body></html>')
            imported = chapters_from_epub(epub)
            self.assertEqual(imported[0].title, "开篇")
            self.assertIn("这是一段", imported[0].text)


if __name__ == "__main__":
    unittest.main()

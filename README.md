# 静读

一个 Windows 浮动小说阅读器。阅读时窗口只显示章节文字。右键打开书架、导入、目录和设置。

## 运行

直接双击桌面的 **静读** 图标，或在开始菜单搜索“静读”。开始菜单中的“书架”可直接打开书名列表。

独立应用位于 `dist\静读\静读.exe`，无需另装 Python。移动或复制应用时请保留整个 `dist\静读` 文件夹。书架、阅读记录和设置保存在 `%APPDATA%\QuietNovelReader`，与旧版共用；旧版最近一次阅读记录会自动进入书架。

保留的 `run.bat` 已修复，可独立使用：优先打开打包应用，应用尚未构建时运行源码。桌面入口和脚本都以普通窗口启动。

## 下载与安装

下载安装包：https://github.com/fffxxxllla/quiet-novel-reader/releases/tag/v1.1.0 —— 双击安装，按向导完成后从桌面或开始菜单打开，无需另装 Python，也不需要手动保管运行库文件夹。免安装便携版：https://github.com/fffxxxllla/quiet-novel-reader/releases/tag/v1.0.0。支持 64 位 Windows 10（1809 及以上）和 Windows 11。

当前安装包约 **123 MiB**，相比原便携目录约 **561 MiB** 减少约 **78%** 的传输体积。精简后的程序文件约 **436 MiB**，安装时另会生成少量卸载文件。

安装包使用压缩后的程序文件，保留中文和英文网页语言资源，排除了调试资源及其他翻译。安装后的程序仍包含网页引擎，因此传输文件的体积小于安装后的占用。默认安装到当前用户的 `%LOCALAPPDATA%\Programs\QuietNovelReader`，可在向导中更改目录；从 Windows 的“已安装的应用”中卸载，书架和阅读记录会保留在 `%APPDATA%\QuietNovelReader`。

安装包只包含应用程序，个人书架、书籍、浏览器 Cookie 和阅读记录不会包含在分享文件中。

开发环境运行：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

## 使用

- **书架**：右键 →“书架”，或按 Ctrl+B。按最近阅读排序，可搜索书名；单击书名打开并恢复该书的章节和滚动位置。右键书名可以重命名、移出书架。移出仅隐藏列表项，已保存内容和记录保留，重新导入可找回。
- **本地书籍**：右键 →“导入 TXT / EPUB”。TXT 按“第…章”标题自动分章；EPUB 按书内目录顺序显示文字。导入后会自动加入书架并保存本地副本，原文件移动或删除后仍可阅读；相同内容的书不会重复添加。
- **小说网址**：右键 →“输入小说网址”。在临时浏览器中打开书籍目录或具体章节；目录页可选章，章节页点击“提取当前页”，检查预览后点击“确认阅读”。浏览器会把 Cookie 和缓存保存在用户配置目录，供下次打开时继续使用。若网站要求验证，请先在浏览器窗完成验证再提取。若网站持续拒绝内嵌浏览器，可点“系统浏览器”，选中章节正文并复制，再点“剪贴板提取”；这种方式需要逐章手动复制。
- **纠正提取**：如果预览带有菜单、广告或漏掉正文，在导入窗口输入正文的 CSS 选择器（例如 `#content`），再点“提取当前页”。
- **网页书名**：导入窗口中可检查或修改“书名”，确认阅读后加入书架。网页书籍缓存最近阅读的一章和目录；打开书架续读该章不需要联网，继续获取其他章节需要联网。
- **纯文字窗口**：鼠标移到窗口边缘或四角，出现双向箭头后按住左键拖动即可调整大小；在文字区域直接按住鼠标左键拖动窗口。按住 Shift 再拖动可选择文字。背景透明度只影响背景，不影响文字。
- **字体与行间距**：右键 →“阅读设置”可选择电脑已安装的字体、调整字号，以及设置 1.00–3.00 倍行间距。保存后立即应用，下次启动会保留这些设置。
- **续读**：自动保存每本书的章节、滚动位置，并保留窗口尺寸。再次启动时恢复最近阅读的书；切换书籍时先保存当前进度。最近记录位于 `%APPDATA%\QuietNovelReader\session.json`，书架索引为 `library.json`，保存的书籍与各书进度位于 `books` 子目录。
- **快捷键**：默认 PageDown/PageUp 翻页，方向键上下滑动，Alt+左右键切换章节。右键 →“阅读设置”可修改。Ctrl+Q 在阅读窗有焦点时关闭；**Ctrl+Alt+Q 全局关闭阅读器**，**Ctrl+Alt+T 全局切换窗口置顶**，切到其他程序后也可使用，并可在设置里改键。关闭前会保存阅读位置。
- **退出置顶**：右键取消勾选“窗口置顶”，或按 Ctrl+Alt+T。若正在运行的是旧版且鼠标无法操作，先按 Ctrl+Alt+Q 关闭，再从桌面“静读”或 `run.bat` 启动。

## 构建与检查

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File build_app.ps1
powershell -ExecutionPolicy Bypass -File install_shortcuts.ps1
powershell -ExecutionPolicy Bypass -File build_installer.ps1
.venv\Scripts\python.exe packaging\verify_installer.py
.venv\Scripts\python.exe -m unittest -v
& '.\dist\静读\静读.exe' --self-check '.\.build\self-check.json'
```

打包使用 [PyInstaller](https://pyinstaller.org/en/stable/operating-mode.html) 的文件夹形式，包含 Python 与 Qt 网页引擎运行组件；`.build` 保存构建中间文件，`dist\静读` 是交付应用。自检使用临时配置和本地 HTML，不修改实际书架，也不访问小说网站。

安装包使用 [Inno Setup](https://jrsoftware.org/isdl.php) 和 LZMA2 压缩。`build_installer.ps1` 支持 `-CompilerPath` 指定 `ISCC.exe`，会先准备精简内容并执行应用自检，再生成 `releases` 中的安装包。`prepare_installer.py` 只处理 `.build\installer-payload`，原来的便携应用目录可继续使用。

## 网页提取方式

读取浏览器渲染后的 HTML，优先寻找常见的正文容器（如 `#content`），再用文字长度、长段落数量和链接密度挑选正文。苦读书的目录和章节链接按同一书籍路径识别，并清除已见到的站点提示语。每次确认前显示正文预览。

`kudushu.org` 对普通程序请求曾返回 Cloudflare 验证页。阅读器现在会保存浏览器验证 Cookie，但网站仍可能因浏览器或网络环境重复要求验证。导入窗口的“系统浏览器”按钮可用于确认网页是否能在默认浏览器中正常打开。这个工具不会绕过登录、付费或网站访问限制。网页结构变化时可使用手动 CSS 选择器；部分动态或受限制页面可能无法导入。

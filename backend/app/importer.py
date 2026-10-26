from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import io
from pathlib import PurePosixPath
import posixpath
import re
import zipfile

from defusedxml import ElementTree as SafeET

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_EXPANDED_BYTES = 60 * 1024 * 1024
MAX_MEMBER_BYTES = 20 * 1024 * 1024
MAX_ZIP_ENTRIES = 512
MAX_COMPRESSION_RATIO = 200


class BookImportError(ValueError):
    """可安全展示给用户的导入错误。"""


@dataclass(frozen=True)
class ParsedPassage:
    chapter_title: str
    text: str


@dataclass(frozen=True)
class ParsedBook:
    title: str
    author: str
    format: str
    passages: list[ParsedPassage]


def _safe_member_name(name: str) -> str:
    if "\\" in name or "\x00" in name:
        raise BookImportError("EPUB 含不安全路径")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise BookImportError("EPUB 含路径穿越条目")
    return str(path)


def _read_zip(data: bytes) -> tuple[zipfile.ZipFile, dict[str, zipfile.ZipInfo]]:
    if not data.startswith(b"PK"):
        raise BookImportError("EPUB 不是有效的 ZIP/EPUB 文件")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BookImportError("EPUB 压缩包损坏") from exc
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise BookImportError("EPUB 条目数量超限")
    total = 0
    mapping: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        name = _safe_member_name(info.filename)
        if info.flag_bits & 0x1:
            raise BookImportError("不支持加密 EPUB")
        if info.file_size > MAX_MEMBER_BYTES:
            raise BookImportError("EPUB 单个展开文件超限")
        total += info.file_size
        if total > MAX_EXPANDED_BYTES:
            raise BookImportError("EPUB 总展开大小超限")
        if info.file_size > 1024 * 1024:
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > MAX_COMPRESSION_RATIO:
                raise BookImportError("EPUB 压缩比异常，已拒绝导入")
        mapping[name] = info
    return archive, mapping


def _xml(data: bytes):
    try:
        return SafeET.fromstring(data)
    except Exception as exc:
        raise BookImportError("EPUB XML 不安全或无法解析") from exc


def _opf_path(container: bytes) -> str:
    root = _xml(container)
    rootfile = next((node for node in root.iter() if node.tag.endswith("rootfile")), None)
    if rootfile is None or not rootfile.attrib.get("full-path"):
        raise BookImportError("EPUB 缺少 OPF 入口")
    return _safe_member_name(rootfile.attrib["full-path"])


def _chapter_text(data: bytes) -> list[tuple[str, str]]:
    lowered = data.lower()
    if re.search(rb"<\s*(script|iframe|object|embed|svg)\b", lowered):
        raise BookImportError("EPUB 含脚本或嵌入内容，已拒绝导入")
    if re.search(rb"\son[a-z]+\s*=|javascript\s*:", lowered):
        raise BookImportError("EPUB 含可执行 HTML，已拒绝导入")
    try:
        source = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BookImportError("EPUB 章节目前仅接受 UTF-8 XHTML") from exc

    class TextParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.blocks: list[tuple[str, str]] = []
            self.current_tag: str | None = None
            self.buffer: list[str] = []
            self.depth = 0

        def handle_starttag(self, tag: str, attrs):
            if tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"}:
                if self.current_tag:
                    self._flush()
                self.current_tag = tag
                self.buffer = []
                self.depth = 1
            elif self.current_tag:
                self.depth += 1

        def handle_endtag(self, tag: str):
            if not self.current_tag:
                return
            if tag == self.current_tag:
                self._flush()
            else:
                self.depth = max(1, self.depth - 1)

        def handle_data(self, data: str):
            if self.current_tag:
                self.buffer.append(data)

        def _flush(self):
            text = re.sub(r"\s+", " ", "".join(self.buffer)).strip()
            if text and self.current_tag:
                self.blocks.append((self.current_tag, text))
            self.current_tag = None
            self.buffer = []
            self.depth = 0

    parser = TextParser()
    parser.feed(source)
    parser.close()
    return parser.blocks


def parse_epub(data: bytes, fallback_title: str) -> ParsedBook:
    archive, members = _read_zip(data)
    with archive:
        if "mimetype" in members:
            mime = archive.read(members["mimetype"]).strip()
            if mime != b"application/epub+zip":
                raise BookImportError("EPUB MIME 类型不正确")
        if "META-INF/container.xml" not in members:
            raise BookImportError("EPUB 缺少 container.xml")
        opf_name = _opf_path(archive.read(members["META-INF/container.xml"]))
        if opf_name not in members:
            raise BookImportError("EPUB OPF 路径无效")
        opf = _xml(archive.read(members[opf_name]))
        manifest: dict[str, str] = {}
        spine: list[str] = []
        title = ""
        author = ""
        base = posixpath.dirname(opf_name)
        for node in opf.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "title" and not title:
                title = (node.text or "").strip()
            elif tag == "creator" and not author:
                author = (node.text or "").strip()
            elif tag == "item" and node.attrib.get("id") and node.attrib.get("href"):
                href = node.attrib["href"].split("?", 1)[0].split("#", 1)[0]
                media = node.attrib.get("media-type", "")
                if media in {"application/xhtml+xml", "text/html"}:
                    manifest[node.attrib["id"]] = href
            elif tag == "itemref" and node.attrib.get("idref"):
                spine.append(node.attrib["idref"])
        if not spine:
            raise BookImportError("EPUB spine 为空")

        passages: list[ParsedPassage] = []
        for index, item_id in enumerate(spine, start=1):
            href = manifest.get(item_id)
            if not href:
                continue
            if href.startswith("/") or re.match(r"^[a-z]+:", href, re.I):
                raise BookImportError("EPUB spine 引用了外部资源")
            resolved = _safe_member_name(posixpath.normpath(posixpath.join(base, href)))
            if resolved not in members:
                raise BookImportError("EPUB spine 引用了不存在的章节")
            blocks = _chapter_text(archive.read(members[resolved]))
            chapter_title = f"第 {index} 节"
            passage_order = 0
            for tag, text in blocks:
                if tag.startswith("h") and len(tag) == 2:
                    chapter_title = text
                    continue
                passage_order += 1
                passages.append(ParsedPassage(chapter_title, text))
        if not passages:
            raise BookImportError("EPUB 未提取到正文段落")
        return ParsedBook(title or fallback_title, author or "未知作者", "epub", passages)


def parse_txt(data: bytes, fallback_title: str) -> ParsedBook:
    if b"\x00" in data:
        raise BookImportError("TXT 含空字节，可能不是 UTF-8 文本")
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise BookImportError("TXT 必须使用 UTF-8 编码") from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    passages: list[ParsedPassage] = []
    chapter = "正文"
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        # 保留普通单换行，不把标题后的正文误吞为标题，也不丢弃任何一行。
        normalized = "\n".join(re.sub(r"[\t\f\v ]+", " ", line).strip() for line in paragraph_lines).strip()
        if normalized:
            passages.append(ParsedPassage(chapter, normalized))
        paragraph_lines.clear()

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        is_heading = bool(line) and (
            line.startswith("#") or re.match(r"^第[一二三四五六七八九十百千0-9]+[章节卷部](?:\s|$)", line)
        )
        if is_heading:
            flush_paragraph()
            chapter = line.lstrip("#").strip()
        elif not line:
            flush_paragraph()
        else:
            paragraph_lines.append(line)
    flush_paragraph()
    if not passages:
        raise BookImportError("TXT 未提取到正文段落")
    return ParsedBook(fallback_title, "未知作者", "txt", passages)


def parse_book(data: bytes, filename: str) -> ParsedBook:
    if not data:
        raise BookImportError("文件为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise BookImportError("文件超过 20 MiB 限制")
    suffix = PurePosixPath(filename.lower()).suffix
    fallback = PurePosixPath(filename).stem.strip() or "未命名图书"
    if suffix == ".epub":
        return parse_epub(data, fallback)
    if suffix == ".txt":
        return parse_txt(data, fallback)
    raise BookImportError("仅支持 .epub 与 UTF-8 .txt 文件")

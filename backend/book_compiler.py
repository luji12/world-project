"""Compile approved chapter revisions into reader-ready Markdown and HTML."""

from __future__ import annotations

from html import escape
from pathlib import Path

from story_ledger import StoryLedger


READER_CSS = """
:root { color-scheme: light dark; }
body { margin: 0; background: #f4efe5; color: #28211c; font-family: 'Noto Serif SC', 'Source Han Serif SC', Georgia, serif; }
main { max-width: 44rem; margin: 0 auto; padding: clamp(2rem, 8vw, 6rem) 1.5rem; }
h1 { font-size: clamp(2rem, 5vw, 3.5rem); line-height: 1.15; }
h2 { margin-top: 4rem; font-size: 1.5rem; }
h3 { margin-top: 3rem; font-size: 1.2rem; }
p { font-size: 1.125rem; line-height: 2; text-wrap: pretty; }
@media (prefers-color-scheme: dark) { body { background: #151411; color: #eee8dc; } }
""".strip()


def compile_book(world_dir: str | Path, title: str) -> dict[str, str | int]:
    world_path = Path(world_dir)
    chapters = StoryLedger(world_path).approved_chapters()
    if not chapters:
        raise ValueError("还没有已批准的章节，无法编译小说。")

    output_dir = world_path / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "novel.md"
    html_path = output_dir / "novel.html"

    markdown_lines = [f"# {title}", ""]
    html_sections = [f"<h1>{escape(title)}</h1>"]
    for chapter in chapters:
        chapter_title = f"第{chapter['chapter_no']}章"
        markdown_lines.extend([f"## {chapter_title}", "", chapter["content"], ""])
        paragraphs = "".join(f"<p>{escape(paragraph)}</p>" for paragraph in chapter["content"].splitlines() if paragraph.strip())
        html_sections.append(f"<article><h2>{chapter_title}</h2>{paragraphs}</article>")

    markdown_path.write_text("\n".join(markdown_lines), encoding="utf-8")
    html_path.write_text(
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>"
        + escape(title)
        + "</title><style>"
        + READER_CSS
        + "</style></head><body><main>"
        + "\n".join(html_sections)
        + "</main></body></html>",
        encoding="utf-8",
    )
    return {"chapters": len(chapters), "markdown": str(markdown_path), "html": str(html_path)}

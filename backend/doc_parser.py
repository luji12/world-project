import os
import re


def extract_text(file_bytes: bytes, extension: str, filename: str = "unknown") -> str:
    if extension in ['.txt', '.md']:
        try:
            return file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            try:
                return file_bytes.decode('gbk')
            except:
                return file_bytes.decode('utf-8', errors='replace')

    elif extension == '.pdf':
        return _extract_pdf(file_bytes)

    else:
        try:
            return file_bytes.decode('utf-8')
        except:
            return ''


def _extract_pdf(file_bytes: bytes) -> str:
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        text = '\n'.join(text_parts)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {3,}', '  ', text)
        return text.strip()
    except ImportError:
        return ''
    except Exception:
        return ''


def summarize_long_text(text: str, api_key: str, base_url: str, model: str) -> str:
    from agents.base import call_deepseek
    import json

    chunk_size = 15000
    overlap = 500
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap

    summaries = []
    for i, chunk in enumerate(chunks):
        prompt = json.dumps({
            "instruction": f"你是世界设定提取助手。以下是小说/设定的第{i+1}/{len(chunks)}段。请用200字以内提取其中的：世界观信息、角色及其特征、重要地点、势力/组织、关键事件。只提取事实，不要编造。如果本段没有这些信息，返回'无'。",
            "text": chunk,
        }, ensure_ascii=False)

        try:
            result = call_deepseek(
                "你是世界设定提取助手。只提取事实，不编造。输出JSON：{\"summary\": \"...\"}",
                prompt,
                api_key=api_key, base_url=base_url, model=model,
                max_tokens=512, temperature=0.3,
            )
            summary = result.get("summary", "")
            if summary and summary != "无":
                summaries.append(summary)
        except:
            summaries.append(chunk[:500])

    combined = "\n\n---\n\n".join(summaries)
    if len(combined) > 60000:
        combined = combined[:60000]
    return combined

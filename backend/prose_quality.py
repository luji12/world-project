"""Deterministic quality signals used before an LLM editorial pass.

The score is deliberately a warning system, not a claim that software can judge
literary merit. It catches mechanical patterns that make a draft read as AI-made
or under-edited, while preserving the author's intended plot and voice.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


AI_CLICHES = (
    "一切如常",
    "没有异样",
    "不由得",
    "嘴角微微上扬",
    "眼中闪过一丝",
    "心中暗道",
    "与此同时",
    "毫无疑问",
    "可想而知",
)
SENTENCE_SPLIT = re.compile(r"[。！？!?]+")


def review_prose(content: str) -> dict[str, Any]:
    text = content.strip()
    paragraphs = [paragraph.strip() for paragraph in text.splitlines() if paragraph.strip()]
    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT.split(text) if sentence.strip()]
    normalized = [re.sub(r"[\s，、；：‘’“”\"'（）()]+", "", sentence) for sentence in sentences]
    duplicates = {sentence: count for sentence, count in Counter(normalized).items() if len(sentence) > 8 and count > 1}
    cliches = {phrase: text.count(phrase) for phrase in AI_CLICHES if phrase in text}
    punctuation = Counter(character for character in text if character in "。！？!?……")
    avg_sentence_length = round(sum(map(len, sentences)) / len(sentences), 1) if sentences else 0

    flags: list[str] = []
    if len(text) < 400:
        flags.append("篇幅过短，尚不足以形成完整场景。")
    if len(paragraphs) < 3:
        flags.append("段落层次不足，建议检查场景节奏。")
    if cliches:
        flags.append("检测到常见 AI 套话，需在文风审校阶段改写。")
    if duplicates:
        flags.append("存在重复句式或重复表达。")
    if sentences and punctuation.get("。", 0) / len(sentences) > 0.92 and len(sentences) > 8:
        flags.append("句末节奏过于单一，建议调整语气与断句。")

    score = 100 - len(flags) * 12 - sum(max(count - 1, 0) * 4 for count in cliches.values())
    return {
        "score": max(0, score),
        "word_count": len(text),
        "paragraph_count": len(paragraphs),
        "sentence_count": len(sentences),
        "average_sentence_length": avg_sentence_length,
        "cliches": cliches,
        "duplicate_sentences": duplicates,
        "flags": flags,
    }

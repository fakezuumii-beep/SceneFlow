"""Shared helpers for the online text-to-speech worker."""
from __future__ import annotations

import hashlib
import json
import re

LANGUAGES = ['Chinese', 'English']


def split_script(text, limit=80):
    """Split at natural sentence boundaries while preserving every character."""
    sentences = re.findall(r'.+?(?:[。！？!?；;\n]+|(?<=[a-zA-Z])[.](?=\s|$)|$)', text, flags=re.S)
    chunks = []
    for sentence in sentences:
        while len(sentence) > limit:
            lower = limit // 2
            cuts = [sentence.rfind(mark, lower, limit + 1) for mark in ('，', ',', '：', ':', '、', ' ')]
            cut = max(cuts) + 1
            if cut <= lower:
                cut = limit
            chunks.append(sentence[:cut])
            sentence = sentence[cut:]
        if sentence:
            chunks.append(sentence)
    result = []
    pending = ''
    for chunk in chunks:
        chunk = pending + chunk
        pending = ''
        if len(re.sub(r'\s|[，。！？!?；;,:：、]', '', chunk)) < 8:
            pending = chunk
        else:
            result.append(chunk)
    if pending:
        if result and len(result[-1]) + len(pending) <= limit:
            result[-1] += pending
        else:
            result.append(pending)
    if ''.join(result) != text:
        raise ValueError('原稿分段校验失败')
    return result


def signature(text, speaker, language, provider='azure-v1', speed=1.0):
    payload = [text, speaker, language, provider, round(float(speed), 3), 'azure-tts-v1']
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:24]

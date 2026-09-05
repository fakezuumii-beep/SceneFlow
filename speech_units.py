"""Split ASR words at real timestamped phrase boundaries, never estimated timing."""
import re


def phrase_segments(segment, max_seconds=6.0):
    words = segment.get('words') or []
    if not words:
        return [{k: segment[k] for k in ('start', 'end', 'text')}]
    result, pending = [], []

    def flush():
        if not pending:
            return
        start = max(float(segment['start']), float(pending[0]['start']))
        if result:
            start = max(start, result[-1]['end'])
        end = min(float(segment['end']), float(pending[-1]['end']))
        text = ''.join(w['word'] for w in pending)
        if end > start:
            result.append({'start': start, 'end': end, 'text': text})
        elif result:
            result[-1]['text'] += text
        else:
            return
        pending.clear()

    for word in words:
        pending.append(word)
        span = float(word['end']) - float(pending[0]['start'])
        if (span >= .6 and re.search(r'[，,。！？!?；;：:]\s*$', word['word'])) or span >= max_seconds:
            flush()
    flush()
    if not result:
        return [{k: segment[k] for k in ('start', 'end', 'text')}]
    result[0]['start'] = float(segment['start'])
    result[-1]['end'] = float(segment['end'])
    return result

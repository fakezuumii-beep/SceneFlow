"""Build punctuation candidates on real ASR word boundaries."""
import difflib
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


def punctuation_parts(text):
    """Split source text at requested punctuation while preserving every byte."""
    parts=re.findall(r'.+?(?:[，,。；;？！!?]+|$)',str(text),flags=re.S)
    if ''.join(parts)!=str(text):raise ValueError('原稿标点切分失败')
    return [part for part in parts if part]


def _normalized_characters(text):
    return [(index,char.lower()) for index,char in enumerate(str(text)) if re.match(r'[\w\u3400-\u9fff]',char,re.UNICODE)]


def align_script_to_words(text, words, audio_start=0.0, audio_end=None):
    """Map exact script punctuation to observed ASR word timestamps.

    Sequence matching chooses the corresponding recognized word boundary.  No
    timestamp is created by character-rate interpolation.
    """
    parts=punctuation_parts(text)
    usable=[w for w in words if w.get('start') is not None and w.get('end') is not None and float(w['end'])>float(w['start'])]
    if len(parts)<=1 or not usable:
        end=float(audio_end if audio_end is not None else (usable[-1]['end'] if usable else audio_start))
        return [{'start':float(audio_start),'end':end,'text':str(text)}]

    ref=_normalized_characters(text);hyp=[]
    for word_index,word in enumerate(usable):
        hyp.extend((word_index,char) for _,char in _normalized_characters(word.get('word','')))
    if not ref or not hyp:
        end=float(audio_end if audio_end is not None else usable[-1]['end'])
        return [{'start':float(audio_start),'end':end,'text':str(text)}]
    matcher=difflib.SequenceMatcher(None,[c for _,c in ref],[c for _,c in hyp],autojunk=False)
    mappings={}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):mappings[block.a+offset]=block.b+offset
    if not mappings:
        end=float(audio_end if audio_end is not None else usable[-1]['end'])
        return [{'start':float(audio_start),'end':end,'text':str(text)}]

    char_ends=[];cursor=0
    for part in parts:
        cursor+=len(part);char_ends.append(cursor)
    boundaries=[float(audio_start)]
    previous_word=-1
    for source_end in char_ends[:-1]:
        ref_position=sum(1 for original_index,_ in ref if original_index<source_end)-1
        nearest=min(mappings,key=lambda index:abs(index-ref_position))
        hyp_position=mappings[nearest];word_index=hyp[hyp_position][0]
        word_index=max(previous_word+1,min(word_index,len(usable)-2))
        boundaries.append(float(usable[word_index]['end']));previous_word=word_index
    boundaries.append(float(audio_end if audio_end is not None else usable[-1]['end']))
    result=[]
    for part,start,end in zip(parts,boundaries,boundaries[1:]):
        if end<=start:
            if result:result[-1]['text']+=part
            continue
        result.append({'start':round(start,3),'end':round(end,3),'text':part})
    if ''.join(item['text'] for item in result)!=str(text):raise ValueError('原稿对齐未完整保留文字')
    return result

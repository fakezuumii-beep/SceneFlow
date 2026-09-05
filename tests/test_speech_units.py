import unittest
from speech_units import phrase_segments


class SpeechUnitTests(unittest.TestCase):
    def test_long_asr_segment_preserves_words_and_real_boundaries(self):
        words = [{'start':i*1.2,'end':(i+1)*1.2,'word':text}
                 for i,text in enumerate(['每天','刷几十条视频,','看无数观点,','可真让你','讲清楚一件事,','却不知道','从哪里说起。'])]
        source = {'start':0,'end':8.4,'text':''.join(w['word'] for w in words),'words':words}
        result = phrase_segments(source)
        self.assertEqual(''.join(s['text'] for s in result),source['text'])
        self.assertGreater(len(result),1)
        self.assertEqual(result[0]['end'],words[1]['end'])
        self.assertEqual(result[-1]['end'],8.4)
        self.assertTrue(all(s['end']>s['start'] for s in result))

    def test_no_punctuation_splits_only_at_word_timestamps(self):
        words = [{'start':i,'end':i+1,'word':'word '} for i in range(25)]
        result = phrase_segments({'start':0,'end':25,'text':'word '*25,'words':words})
        self.assertEqual([s['end'] for s in result],[6,12,18,24,25])
        self.assertEqual(''.join(s['text'] for s in result),'word '*25)

    def test_missing_word_alignment_keeps_original_segment(self):
        s={'start':1,'end':4,'text':'原始字幕'}
        self.assertEqual(phrase_segments(s),[s])

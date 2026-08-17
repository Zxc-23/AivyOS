"""通知适配与情感标签测试（§12.6/T4.4 + §6.1/T4.5）。"""

import unittest

from aivyos_core.emotion import EMOTION_TAGS, EmotionTagger
from aivyos_core.notification import ConsoleNotifier, NotifierUnavailable, WinToastNotifier, create_notifier

from tests import AivyTestCase


class TestNotification(AivyTestCase):
    def test_console_notifier(self):
        n = ConsoleNotifier()
        entry = n.notify("AivyOS", "测试通知", level="normal")
        self.assertEqual(entry["level"], "normal")
        self.assertFalse(entry["delivered"])

    def test_win_toast_missing_falls_back(self):
        with self.assertRaises(NotifierUnavailable):
            WinToastNotifier()
        n = create_notifier({"notify_backend": "auto"})
        self.assertIsInstance(n, ConsoleNotifier)


class TestEmotionTagger(AivyTestCase):
    def setUp(self):
        self.tagger = EmotionTagger(enabled=True)

    def test_tags_defined(self):
        self.assertEqual(len(EMOTION_TAGS), 14)
        self.assertIn("laughter", EMOTION_TAGS)
        self.assertIn("breath", EMOTION_TAGS)

    def test_parse_strip_roundtrip(self):
        text = "哈哈[laughter]这太有趣了[breath]"
        tags = self.tagger.parse(text)
        self.assertIn("laughter", tags)
        self.assertIn("breath", tags)
        stripped = self.tagger.strip(text)
        self.assertNotIn("[laughter]", stripped)
        self.assertNotIn("[breath]", stripped)

    def test_enrich(self):
        enriched = self.tagger.enrich("回复", ["laughter"])
        self.assertTrue(enriched.startswith("[laughter]"))

    def test_disabled(self):
        t = EmotionTagger(enabled=False)
        self.assertEqual(t.parse("[laughter]x"), [])
        self.assertEqual(t.strip("[laughter]x"), "[laughter]x")

    def test_split(self):
        tags, text = self.tagger.split("好[whisper]")
        self.assertEqual(tags, ["whisper"])
        self.assertEqual(text, "好")


if __name__ == "__main__":
    unittest.main()

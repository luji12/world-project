import unittest

from prose_quality import review_prose


class ProseQualityTests(unittest.TestCase):
    def test_reports_repetition_and_cliches_without_rewriting_content(self):
        text = "一切如常。" * 5 + "\n" + "他没有异样地站在原地。" * 5
        result = review_prose(text)
        self.assertIn("一切如常", result["cliches"])
        self.assertGreaterEqual(len(result["flags"]), 2)


if __name__ == "__main__":
    unittest.main()

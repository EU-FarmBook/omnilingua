import unittest

from app.pipeline.translator_llm import should_retry_translation


class ShouldRetryDegenerateOutputTests(unittest.TestCase):
    def test_repetition_loop_is_flagged(self):
        source = "Empowerment of circular bioeconomy ambassadors."
        translated = "Cumarsúid " + ("ar bheith i bhunáid " * 8).strip()
        self.assertTrue(should_retry_translation(source, translated, "en", "ga"))

    def test_runaway_length_is_flagged(self):
        source = "Strategic directions for the national bioeconomy plan."
        translated = " ".join(f"focal{i} eile{i} nua{i}" for i in range(30))
        self.assertTrue(should_retry_translation(source, translated, "en", "ga"))

    def test_normal_expansion_is_not_flagged(self):
        source = (
            "Estonia is successful in primary biomass production and processing "
            "across several regions."
        )
        translated = (
            "Tá rath ar an Eastóin i dtáirgeadh agus i bpróiseáil bithmhaise "
            "príomhúla ar fud roinnt réigiún éagsúil sa tír le blianta beaga."
        )
        self.assertFalse(should_retry_translation(source, translated, "en", "ga"))

    def test_short_legitimate_translation_is_not_flagged(self):
        self.assertFalse(
            should_retry_translation("Strategic directions", "Treoracha straitéiseacha", "en", "ga")
        )


if __name__ == "__main__":
    unittest.main()

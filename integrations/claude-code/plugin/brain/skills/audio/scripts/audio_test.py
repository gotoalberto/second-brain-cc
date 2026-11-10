"""Tests for audio.py text handling. Run: python3 audio_test.py   (no venv, no torch, no model)"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio as A  # noqa: E402


class ParseUnits(unittest.TestCase):
    def test_plain_paragraphs_are_one_unit_each(self):
        u = A.parse_units("Hola mundo.\n\nAdiós.")
        self.assertEqual([x["text"] for x in u], ["Hola mundo.", "Adiós."])
        self.assertEqual([x["para"] for x in u], [0, 1])
        self.assertFalse(any(x["foreign"] for x in u))

    def test_foreign_word_is_cut_out_with_its_language(self):
        u = A.parse_units("Compró un {en:smartphone} nuevo en {fr:Paris}.")
        self.assertEqual([(x["text"], x["lang"], x["foreign"]) for x in u], [
            ("Compró un", "Spanish", False), ("smartphone", "English", True),
            ("nuevo en", "Spanish", False), ("Paris", "French", True), (".", "Spanish", False)])

    def test_foreign_word_at_paragraph_start(self):
        u = A.parse_units("{en:Bitcoin} sube.")
        self.assertEqual([x["lang"] for x in u], ["English", "Spanish"])

    def test_unknown_code_is_refused(self):
        with self.assertRaises(ValueError):
            A.parse_units("Un {xx:test}.")

    def test_main_language_can_change(self):
        u = A.parse_units("Hello {es:amigo}.", language="English")
        self.assertEqual([x["lang"] for x in u], ["English", "Spanish", "English"])

    def test_whitespace_inside_paragraph_is_collapsed(self):
        self.assertEqual(A.parse_units("Una\nlínea   larga.")[0]["text"], "Una línea larga.")


class ForeignSuspects(unittest.TestCase):
    def test_flags_untagged_english_words(self):
        self.assertEqual(A.foreign_suspects("Abrió el wallet y vio el marketing del show."),
                         ["wallet", "marketing", "show"])

    def test_ignores_tagged_words_and_plain_spanish(self):
        self.assertEqual(A.foreign_suspects("El rey compró un {en:smartphone} muy caro hoy."), [])


class SplitLong(unittest.TestCase):
    def test_short_text_untouched(self):
        self.assertEqual(A.split_long("Corto."), ["Corto."])

    def test_long_text_cut_at_sentences_under_limit(self):
        text = " ".join(f"Frase número {i} con algo de texto." for i in range(40))
        parts = A.split_long(text, limit=120)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= 120 for p in parts))
        self.assertEqual(" ".join(parts), text)


def main():
    """unittest, plus the `RESULT: N passed, M failed` line _bin/run_all_tests.py adds up."""
    result = unittest.main(exit=False).result
    failed = len(result.failures) + len(result.errors)
    print("\nRESULT: %d passed, %d failed" % (result.testsRun - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

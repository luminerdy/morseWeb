import unittest

from morse import morse_to_text, text_to_morse


class MorseConversionTests(unittest.TestCase):
    def test_text_to_morse_basic(self):
        self.assertEqual(text_to_morse("SOS"), "... --- ...")

    def test_morse_to_text_basic(self):
        self.assertEqual(morse_to_text("... --- ..."), "SOS")

    def test_round_trip_alphabet_and_digits(self):
        text = "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG 0123456789"
        self.assertEqual(morse_to_text(text_to_morse(text)), text)

    def test_word_gap_round_trip(self):
        self.assertEqual(morse_to_text(text_to_morse("HI PAPPY")), "HI PAPPY")


if __name__ == "__main__":
    unittest.main()

"""Dependency-free text chunking tests."""
import unittest

from info_hub.content import split_text


class ChunkingTests(unittest.TestCase):
    def test_short_document(self):
        text = "Hello, world!"
        chunks = split_text(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].char_start, 0)
        self.assertEqual(chunks[0].char_end, len(text))
        self.assertEqual(chunks[0].text, text)

    def test_long_document_offsets_and_overlaps(self):
        text = " ".join(f"word{i}" for i in range(1500))
        chunks = split_text(text, max_chars=500, overlap=80)
        self.assertGreater(len(chunks), 10)
        self.assertEqual(chunks[0].char_start, 0)
        self.assertEqual(chunks[-1].char_end, len(text))
        for a, b in zip(chunks, chunks[1:]):
            self.assertLess(b.char_start, a.char_end)
            self.assertGreater(b.char_start, a.char_start)
        for chunk in chunks:
            self.assertEqual(chunk.text, text[chunk.char_start:chunk.char_end])
            self.assertLessEqual(len(chunk.text), 500)

    def test_invalid_configuration(self):
        with self.assertRaises(ValueError):
            split_text("x" * 1000, max_chars=150, overlap=100)


if __name__ == "__main__":
    unittest.main()

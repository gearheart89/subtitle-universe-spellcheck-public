import unittest
from pathlib import Path
from unittest.mock import Mock

from subtitle_cleanup import DictionaryContext, replace_first_word_in_lines
from tests.test_spellcheck import make_tool


class SrtPreservationTests(unittest.TestCase):
    def round_trip(self, raw: bytes, mutate=None) -> bytes:
        tool = make_tool()
        path = Mock(spec=Path)
        path.read_bytes.return_value = raw
        blocks = tool.parse_srt(path)
        if mutate:
            mutate(blocks)
        tool.atomic_write_bytes = Mock()
        tool.write_srt(path, blocks)
        return tool.atomic_write_bytes.call_args.args[1]

    def test_utf8_bom_and_crlf_are_preserved(self):
        raw = (
            b"\xef\xbb\xbf1\r\n00:00:00,000 --> 00:00:01,000\r\n"
            + "Café teh\r\n".encode("utf-8")
        )

        def correct(blocks):
            blocks[0].text_lines = replace_first_word_in_lines(
                blocks[0].text_lines, "teh", "the"
            )

        result = self.round_trip(raw, correct)

        self.assertTrue(result.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(result.decode("utf-8-sig"), (
            "1\r\n00:00:00,000 --> 00:00:01,000\r\nCafé the\r\n"
        ))
        self.assertNotIn(b"\n", result.replace(b"\r\n", b""))

    def test_utf8_without_bom_and_lf_are_preserved(self):
        raw = "1\n00:00:00,000 --> 00:00:01,000\nnaïve text\n".encode("utf-8")
        result = self.round_trip(raw)

        self.assertEqual(result, raw)
        self.assertFalse(result.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", result)

    def test_utf16_little_endian_bom_is_preserved(self):
        text = "1\r\n00:00:00,000 --> 00:00:01,000\r\nRésumé\r\n"
        raw = b"\xff\xfe" + text.encode("utf-16-le")

        result = self.round_trip(raw)

        self.assertEqual(result, raw)

    def test_legacy_windows_1252_is_preserved(self):
        text = "1\r\n00:00:00,000 --> 00:00:01,000\r\nIt’s déjà vu.\r\n"
        raw = text.encode("cp1252")

        result = self.round_trip(raw)

        self.assertEqual(result, raw)

    def test_unrepresentable_legacy_edit_is_rejected_before_write(self):
        tool = make_tool()
        path = Mock(spec=Path)
        path.read_bytes.return_value = (
            "1\r\n00:00:00,000 --> 00:00:01,000\r\nCafé\r\n"
        ).encode("cp1252")
        blocks = tool.parse_srt(path)
        blocks[0].text_lines = ["Café 🚀"]
        tool.atomic_write_bytes = Mock()

        with self.assertRaises(UnicodeEncodeError):
            tool.write_srt(path, blocks)

        tool.atomic_write_bytes.assert_not_called()

    def test_missing_terminal_newline_is_preserved(self):
        raw = b"1\n00:00:00,000 --> 00:00:01,000\nNo final newline"

        self.assertEqual(self.round_trip(raw), raw)

    def test_multiple_terminal_newlines_are_preserved_exactly(self):
        raw = b"1\r\n00:00:00,000 --> 00:00:01,000\r\nText\r\n\r\n"

        self.assertEqual(self.round_trip(raw), raw)

    def test_mixed_newlines_use_predominant_style_and_keep_terminal_sequence(self):
        raw = (
            b"1\r\n00:00:00,000 --> 00:00:01,000\r\nAlpha\r\n\r\n"
            b"2\n00:00:01,000 --> 00:00:02,000\r\nBeta\n"
        )

        def correct(blocks):
            blocks[1].text_lines = ["Corrected"]

        result = self.round_trip(raw, correct)

        self.assertEqual(
            result,
            (
                b"1\r\n00:00:00,000 --> 00:00:01,000\r\nAlpha\r\n\r\n"
                b"2\r\n00:00:01,000 --> 00:00:02,000\r\nCorrected\n"
            ),
        )

    def test_mixed_newline_tie_prefers_crlf(self):
        raw = b"1\r\n00:00:00,000 --> 00:00:01,000\nText"

        self.assertEqual(
            self.round_trip(raw),
            b"1\r\n00:00:00,000 --> 00:00:01,000\r\nText",
        )

    def test_cr_only_newlines_are_preserved(self):
        raw = b"1\r00:00:00,000 --> 00:00:01,000\rText\r\r"

        self.assertEqual(self.round_trip(raw), raw)

    def test_timestamp_without_index_and_tags_are_preserved(self):
        raw = (
            " 00:00:00,000 --> 00:00:01,000  \r\n"
            "<i>Café</i> and <font color=\"yellow\">tea</font>\r\n"
        ).encode("utf-8")

        self.assertEqual(self.round_trip(raw), raw)

    def test_formatting_changes_visible_text_without_changing_tags(self):
        tool = make_tool()
        context = DictionaryContext(
            language="american", base_words={"hello", "world"}
        )

        result = tool.format_text_lines(["<i>HELLO WORLD.</i>"], context)

        self.assertEqual(result, ["<i>Hello world.</i>"])

    def test_text_only_malformed_block_is_not_given_fake_metadata(self):
        raw = b"orphan subtitle text\r\nstill the same block"

        self.assertEqual(self.round_trip(raw), raw)

    def test_mixed_malformed_block_shapes_round_trip_without_fabricated_metadata(self):
        raw = (
            b"1\n00:00:00,000 --> 00:00:01,000\nIndexed\n\n"
            b"00:00:01,000 --> 00:00:02,000\nNo index\n\n"
            b"scene-a\n00:00:02,000 --> 00:00:03,000\nNon-numeric index\n\n"
            b"orphan text\nstill orphan"
        )

        self.assertEqual(self.round_trip(raw), raw)

    def test_index_only_and_empty_text_cues_are_preserved(self):
        raw = (
            b"17\n\n"
            b"18\n00:00:01,000 --> 00:00:02,000\n\n"
            b"19\n00:00:02,000 --> 00:00:03,000\nText"
        )

        self.assertEqual(self.round_trip(raw), raw)

    def test_padded_index_and_timestamp_lines_are_not_rewritten(self):
        raw = (
            b"  7  \n"
            b" 00:00:00,000 --> 00:00:01,000  \n"
            b"Text"
        )

        self.assertEqual(self.round_trip(raw), raw)


if __name__ == "__main__":
    unittest.main()

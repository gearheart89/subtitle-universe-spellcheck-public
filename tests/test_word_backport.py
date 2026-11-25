"""Subtitle-only regressions for shared spelling fixes backported from development."""
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest.mock import patch

from app.subtitle_cleanup import DictionaryContext, SubtitleBlock, WORD_RE, dictionary_key, replace_first_word, replace_first_word_in_lines
from test_spellcheck import make_tool


class SharedWordBackportTests(unittest.TestCase):
    def test_unicode_and_internal_apostrophes_keep_complete_token_and_offsets(self):
        for word in ("harém", "Hürrem's", "O'riley's", "O'riliey’s", "Teal’c's"):
            for text in (word, unicodedata.normalize('NFD', word)):
                with self.subTest(text=text):
                    matches = list(WORD_RE.finditer('! ' + text + '.'))
                    self.assertEqual([(m.group(), m.start(), m.end()) for m in matches], [(text, 2, 2 + len(text))])

    def test_known_words_and_names_accept_possessives_without_accepting_typos(self):
        for layer in ('base_words', 'user_words', 'universe_words', 'user_names', 'universe_names'):
            names = layer.endswith('names')
            words = ('Suli', "O'riley", "O'riliey", 'Hürrem') if names else ('harem', 'fun', "O'riley")
            values = {dictionary_key(w): w for w in words} if names else {dictionary_key(w) for w in words}
            context = DictionaryContext(language='american', **{layer: values})
            for word in words:
                for apostrophe in ("'", '’'):
                    for text in (word + apostrophe + 's', unicodedata.normalize('NFD', word + apostrophe + 's')):
                        self.assertTrue(context.is_known_word(text), (layer, text))
                        block = SubtitleBlock('1', '', [text])
                        self.assertIsNone(make_tool().find_first_unknown_word(block, context, 'episode.srt', 0))
            for unknown in ("hram's", "Nuli's", "harem's's", "O'rilie's"):
                self.assertFalse(context.is_known_word(unknown), (layer, unknown))

    def test_accent_identity_preserves_distinct_words(self):
        context = DictionaryContext(language='american', user_words={dictionary_key('café')})
        self.assertTrue(context.is_known_word(unicodedata.normalize('NFD', 'café')))
        self.assertFalse(context.is_known_word('cafe'))

    def test_authoritative_casing_keeps_full_name_and_possessive(self):
        context = DictionaryContext(language='american', user_names={dictionary_key(n): n for n in ("O'riley", 'Hürrem', 'Suli')})
        tool = make_tool()
        for source, expected in (("O'RILEY'S", "O'riley's"), ('HÜRREM’S', 'Hürrem’s'), ("SULI'S", "Suli's")):
            self.assertEqual(tool.repair_mostly_uppercase_lines([source], context), [expected])
        self.assertEqual(tool.repair_mostly_uppercase_lines(["HE SAID 'SULI'"], context), ["He said 'Suli'"])
        context.user_names['john smith'] = 'John Smith'
        self.assertEqual(tool.restore_multiword_name_casing_in_lines(["'john", "smith'"], context), ["'John", "Smith'"])

    def test_compounds_preserve_separators_and_only_cover_complete_entries(self):
        tool = make_tool()
        context = DictionaryContext(language='american', user_words={'good-natured'})
        for text in ('good-natured', '<i>good-natured</i>'):
            self.assertTrue(tool.phrase_present_in_block('good-natured', SubtitleBlock('1', '', [text])))
            self.assertIsNone(tool.find_first_unknown_word(SubtitleBlock('1', '', [text]), context, 'a.srt', 0))
        for text in ('good natured', 'good-naturedness', 'xgood-natured'):
            self.assertFalse(tool.phrase_present_in_block('good-natured', SubtitleBlock('1', '', [text])))
            self.assertIsNotNone(tool.find_first_unknown_word(SubtitleBlock('1', '', [text]), context, 'a.srt', 0))
        self.assertTrue(tool.phrase_present_in_block('good natured', SubtitleBlock('1', '', ['good', 'natured'])))
        self.assertIsNotNone(tool.find_first_unknown_word(SubtitleBlock('1', '', ['natured']), context, 'a.srt', 0))

    def fixture(self, root, text):
        tool = make_tool()
        tool.dict_dir = root / 'dictionaries'
        tool.base_dir = tool.dict_dir / 'base'
        tool.user_dir = tool.dict_dir / 'user'
        tool.universe_dir = tool.dict_dir / 'universes'
        tool.gui_session_state_path = root / 'gui.gz'
        tool.subtitle_file_formats = {}
        tool.options['capitalization_mode'] = 'source'
        path = root / 'episode.srt'
        path.write_bytes(('1\r\n00:00:01,000 --> 00:00:02,000\r\n' + text + '\r\n').encode())
        return tool, path

    def test_gui_compound_add_reload_and_undo(self):
        for target in ('user', 'universe'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                tool, path = self.fixture(root, 'good-natured. natured.')
                context = DictionaryContext(language='american', universe='Show', base_words={'good'})
                original = path.read_bytes()
                session = tool.start_spellcheck_review([path], root, context)
                self.assertEqual(session.current_issue.word, 'natured')
                next_issue = tool.add_review_dictionary_entry(session, 'good-natured', list_name='words', target=target)
                self.assertEqual(next_issue.word, 'natured')
                self.assertGreater(next_issue.start, len('good-natured'))
                loaded = tool.load_dictionary_context('american', 'Show')
                self.assertIsNone(tool.find_first_unknown_word(SubtitleBlock('1', '', ['good-natured']), loaded, 'a.srt', 0))
                self.assertEqual(tool.undo_review_action(session).start, 5)
                self.assertEqual(path.read_bytes(), original)

    def test_gui_ignore_quoted_word_advances_and_undo_restores_issue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool, path = self.fixture(root, "'Fatih' Fatih. O'riliey's.")
            context = DictionaryContext(language='american')
            session = tool.start_spellcheck_review([path], root, context)
            self.assertEqual(session.current_issue.word, 'Fatih')
            self.assertEqual(tool.ignore_review_word_for_session(session).word, "O'riliey's")
            self.assertEqual(tool.undo_review_action(session).word, 'Fatih')

    def test_cli_ignore_uses_same_quote_key(self):
        tool = make_tool()
        context = DictionaryContext(language='american')
        blocks = [SubtitleBlock('1', '', ["'Fatih'"])]
        with patch('app.subtitle_cleanup.clear_screen'), patch('builtins.print'), patch('builtins.input', return_value='82'):
            tool.prompt_spellcheck_action(Path('episode.srt'), Path('.'), blocks, 0, "Fatih'", context)
        self.assertIsNone(tool.find_first_unknown_word(blocks[0], context, 'episode.srt', 0))
        self.assertFalse(context.is_known_word("O'riliey's", tool.current_session_ignores))

    def test_alias_rules_keep_possessive_suffixes_without_replacing_other_words(self):
        tool = make_tool()
        context = DictionaryContext(language='american', universe_names={'roxelana': 'Roxelana', "o'riley": "O'riley"})
        context.substitutions = {'roxelane': 'Roxelana', "o'riliey": "O'riley"}
        text = "Roxelane’s Roxelane O’riliey's xRoxelane roxelane-extra"
        self.assertEqual(tool.apply_active_substitutions(text, context), "Roxelana’s Roxelana O'riley's xRoxelane roxelane-extra")
        self.assertEqual(tool.apply_substitutions("colour's colour", {'colour': 'color'}), "colour's color")
        self.assertEqual(tool.apply_substitutions("Roxelane's Roxelane’s", {
            'roxelane': 'Roxelana', "roxelane's": 'explicit'}, names=context.name_map), 'explicit Roxelana’s')

    def test_replacements_retain_source_accents_offsets_and_literal_output(self):
        tool = make_tool()
        text = unicodedata.normalize('NFD', 'café')
        self.assertEqual(tool.apply_substitutions(text + ' caféine', {'café': 'coffee'}), 'coffee caféine')
        self.assertEqual(replace_first_word('good-natured', 'natured', r'\new'), r'good-\new')

    def test_paired_single_quotes_are_not_part_of_unknown_word_across_lines(self):
        tool = make_tool()
        context = DictionaryContext(language='american', base_words={'he', 'said', 'damn', 'it', 'all', 'to', 'and', 'stormed', 'off'})
        for opening, closing in (("'", "'"), ('‘', '’'), ('’', '’')):
            for lines in ([f"He said {opening}damn it all to heck{closing} and stormed off!"],
                          [f"He said {opening}damn it all", f"to heck{closing} and stormed off!"]):
                with self.subTest(lines=lines):
                    block = SubtitleBlock('1', '', lines)
                    issue = tool.find_first_unknown_word(block, context, 'episode.srt', 0)
                    self.assertEqual(issue['word'], 'heck')
                    self.assertEqual(lines[issue['line_index']][issue['start']:issue['end']], 'heck')
                    replaced = replace_first_word_in_lines(lines, 'heck', 'heaven')
                    self.assertEqual(replaced, [line.replace('heck', 'heaven') for line in lines])
        self.assertEqual(tool.find_first_unknown_word(SubtitleBlock('1', '', ["heck'"]), context, 'a.srt', 0)['word'], "heck'")

    def test_quote_detection_keeps_internal_apostrophes_and_dropped_g_option(self):
        tool = make_tool()
        for enabled in (False, True):
            context = DictionaryContext(language='american', base_words={'shooting'},
                user_names={"o'riley": "O'riley"}, recognize_dropped_g_apostrophe_forms=enabled)
            for text in ("shootin'", 'shootin’', "'shootin'", '‘shootin’'):
                with self.subTest(enabled=enabled, text=text):
                    issue = tool.find_first_unknown_word(SubtitleBlock('1', '', [text]), context, 'a.srt', 0)
                    self.assertEqual(issue is None, enabled)
            for text in ("O'riley's", "'O'riley's'", '‘O’riley’s’'):
                self.assertIsNone(tool.find_first_unknown_word(SubtitleBlock('1', '', [text]), context, 'a.srt', 0))
            issue = tool.find_first_unknown_word(SubtitleBlock('1', '', ["'Nuli's'"]), context, 'a.srt', 0)
            self.assertEqual(issue['word'], "Nuli's")

    def test_gui_quote_replacement_and_undo_preserve_quotes_tags_and_newlines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool, path = self.fixture(root, "He said '<i>damn it all\r\nto heck</i>' and stormed off!")
            tool.options['adjust_subtitle_line_count'] = False
            context = DictionaryContext(language='american', base_words={'he', 'said', 'damn', 'it', 'all', 'to', 'and', 'stormed', 'off', 'heaven'})
            session = tool.start_spellcheck_review([path], root, context)
            self.assertEqual(session.current_issue.word, 'heck')
            original = list(session.prepared_blocks[0][0].text_lines)
            self.assertIsNone(tool.replace_review_occurrence(session, 'heaven'))
            self.assertEqual(session.prepared_blocks[0][0].text_lines, [line.replace('heck', 'heaven') for line in original])
            self.assertEqual(tool.undo_review_action(session).word, 'heck')
            self.assertEqual(session.prepared_blocks[0][0].text_lines, original)

    def test_scoped_quote_replacement_propagates_across_line_wraps_and_undoes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool, path = self.fixture(root, "'heck'")
            path.write_bytes(b"1\r\n00:00:01,000 --> 00:00:02,000\r\n'heck'\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\n'go to\r\nheck'\r\n")
            tool.options['adjust_subtitle_line_count'] = False
            original = path.read_bytes()
            context = DictionaryContext(language='american', base_words={'go', 'to', 'heaven'})
            session = tool.start_spellcheck_review([path], root, context)
            before = [list(b.text_lines) for b in session.prepared_blocks[0]]
            self.assertIsNone(tool.replace_review_with_scope(session, 'heaven', 'session'))
            self.assertEqual([b.text_lines for b in session.prepared_blocks[0]], [["'heaven'"], ["'go to", "heaven'"]])
            self.assertEqual(tool.undo_review_action(session).word, 'heck')
            self.assertEqual([b.text_lines for b in session.prepared_blocks[0]], before)
            self.assertEqual(path.read_bytes(), original)

    def test_loaded_quote_rules_and_name_aliases_follow_same_formatter_path(self):
        tool = make_tool()
        tool.options['capitalization_mode'] = 'source'
        tool.options['adjust_subtitle_line_count'] = False
        context = DictionaryContext(language='american', universe_names={'roxelana': 'Roxelana'},
            substitutions={'roxelane': 'Roxelana', 'heck': 'heaven'})
        self.assertEqual(tool.format_text_lines(["'go to", "heck' Roxelane’s"], context), ["'go to", "heaven' Roxelana’s"])
        self.assertEqual(tool.apply_substitutions("<i title='heck'>‘heck’</i> O'heck's", {'heck': 'heaven'}),
                         "<i title='heck'>‘heaven’</i> O'heck's")

    def test_name_alias_gui_propagation_and_undo_keep_all_apostrophes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool, path = self.fixture(root, 'Roxelane Roxelane’s.')
            context = DictionaryContext(language='american', user_names={'roxelana': 'Roxelana'})
            session = tool.start_spellcheck_review([path], root, context)
            self.assertIsNone(tool.replace_review_with_scope(session, 'Roxelana', 'session'))
            self.assertEqual(session.prepared_blocks[0][0].text_lines, ['Roxelana Roxelana’s.'])
            self.assertEqual(tool.undo_review_action(session).word, 'Roxelane')
            self.assertEqual(session.prepared_blocks[0][0].text_lines, ['Roxelane Roxelane’s.'])


if __name__ == '__main__':
    unittest.main()

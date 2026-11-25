"""Completed subtitle scans retire checkpoints only after their edits are safe."""
import tempfile
import gzip
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.subtitle_cleanup import DictionaryContext
from app.subtitle_gui import SubtitleSpellcheckGUI
import test_word_backport


class CompletedSubtitleRecoveryTests(unittest.TestCase):
    def fixture(self, root, text='Wrod.'):
        tool, path = test_word_backport.SharedWordBackportTests().fixture(root, text)
        context = DictionaryContext(language='american', base_words={'word'})
        return tool, path, context

    def test_finished_unchanged_scan_retires_checkpoint_and_undo_revives_it(self):
        with tempfile.TemporaryDirectory() as directory:
            tool, path, context = self.fixture(Path(directory))
            session = tool.start_spellcheck_review([path], path.parent, context)
            tool.save_gui_review_session(session)
            self.assertTrue(tool.gui_session_state_path.exists())
            self.assertIsNone(tool.ignore_review_occurrence(session))
            self.assertTrue(session.undo_actions)
            tool.save_gui_review_session(session)
            self.assertFalse(tool.gui_session_state_path.exists())
            self.assertEqual(tool.undo_review_action(session).word, 'Wrod')
            tool.save_gui_review_session(session)
            self.assertTrue(tool.gui_session_state_path.exists())

    def test_finished_unsaved_scan_stays_recoverable_until_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            tool, path, context = self.fixture(Path(directory))
            original = path.read_bytes()
            session = tool.start_spellcheck_review([path], path.parent, context)
            tool.replace_review_occurrence(session, 'word')
            tool.save_gui_review_session(session)
            self.assertTrue(tool.gui_session_state_path.exists())
            self.assertEqual(path.read_bytes(), original)
            tool.commit_spellcheck_review(session, create_backups=False)
            tool.save_gui_review_session(session)
            self.assertFalse(tool.gui_session_state_path.exists())
            self.assertIn(b'word.', path.read_bytes())

    def test_finished_formatting_scan_stays_recoverable_until_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            tool, path, context = self.fixture(Path(directory), 'Hello ,world.')
            session = tool.create_formatting_review([path], path.parent, context)
            tool.resume_formatting_review(session)
            tool.save_gui_review_session(session)
            self.assertTrue(tool.gui_session_state_path.exists())
            tool.commit_spellcheck_review(session, create_backups=False)
            tool.save_gui_review_session(session)
            self.assertFalse(tool.gui_session_state_path.exists())

    def test_source_drift_cannot_retire_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            tool, path, context = self.fixture(Path(directory))
            session = tool.start_spellcheck_review([path], path.parent, context)
            tool.replace_review_occurrence(session, 'word')
            path.write_bytes(b'external change')
            tool.save_gui_review_session(session)
            self.assertTrue(tool.gui_session_state_path.exists())
            with self.assertRaises(RuntimeError):
                tool.commit_spellcheck_review(session, create_backups=False)
            self.assertEqual(path.read_bytes(), b'external change')

    def test_unrepresentable_edit_keeps_checkpoint_without_writing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            tool, path, context = self.fixture(Path(directory))
            original = "1\r\n00:00:01,000 --> 00:00:02,000\r\nCafé\r\n".encode('cp1252')
            path.write_bytes(original)
            context.user_words.add('café')
            session = tool.start_spellcheck_review([path], path.parent, context)
            session.prepared_blocks[0][0].text_lines = ['Café 🚀']
            self.assertTrue(tool.gui_review_needs_recovery(session))
            tool.save_gui_review_session(session)
            journal = tool.gui_session_state_path.read_bytes()
            with self.assertRaises(UnicodeEncodeError):
                tool.commit_spellcheck_review(session, create_backups=False)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(tool.gui_session_state_path.read_bytes(), journal)
            self.assertFalse(tool.retire_completed_gui_review())
            self.assertEqual(tool.gui_session_state_path.read_bytes(), journal)

    def test_old_completed_checkpoint_is_retired_before_startup_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            tool, path, context = self.fixture(Path(directory), 'word.')
            session = tool.start_spellcheck_review([path], path.parent, context)
            # Model a journal written by the older release after completion.
            payload = {'schema_version': 2, 'mode': 'spellcheck', 'files': [str(path)],
                'target': str(path.parent), 'file_index': 1, 'current_issue': None,
                'prepared_blocks': {'0': [tool._review_block_payload(b) for b in session.prepared_blocks[0]]}}
            tool.gui_session_state_path.write_bytes(gzip.compress(json.dumps(payload).encode()))
            gui = SubtitleSpellcheckGUI.__new__(SubtitleSpellcheckGUI)
            gui.tool = tool
            gui.messagebox = Mock()
            gui._offer_gui_recovery()
            gui.messagebox.askyesnocancel.assert_not_called()
            self.assertFalse(tool.gui_session_state_path.exists())

    def test_old_checkpoint_retirement_refuses_unsaved_drift_incomplete_or_invalid_state(self):
        with tempfile.TemporaryDirectory() as directory:
            tool, path, context = self.fixture(Path(directory), 'word.')
            session = tool.start_spellcheck_review([path], path.parent, context)
            payload = {'schema_version': 2, 'mode': 'spellcheck', 'files': [str(path)],
                'target': str(path.parent), 'file_index': 1, 'current_issue': None,
                'prepared_blocks': {'0': [tool._review_block_payload(b) for b in session.prepared_blocks[0]]}}
            original = path.read_bytes()
            for state in ('drift', 'unsaved', 'incomplete', 'missing', 'invalid'):
                with self.subTest(state=state):
                    data = json.loads(json.dumps(payload))
                    path.write_bytes(original)
                    if state == 'drift': path.write_bytes(b'external change')
                    elif state == 'unsaved': data['prepared_blocks']['0'][0]['text_lines'] = ['edited']
                    elif state == 'incomplete': data['file_index'] = 0
                    elif state == 'missing': data['prepared_blocks'] = {}
                    raw = b'not a journal' if state == 'invalid' else gzip.compress(json.dumps(data).encode())
                    tool.gui_session_state_path.write_bytes(raw)
                    self.assertFalse(tool.retire_completed_gui_review())
                    self.assertEqual(tool.gui_session_state_path.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()

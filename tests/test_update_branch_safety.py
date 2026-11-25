"""Wrong-channel releases must never replace a development installation."""
import json
from pathlib import Path
import tempfile
import shutil
import subprocess
import sys
import zipfile
import unittest
from unittest.mock import Mock, patch

from app import subtitle_cleanup as engine
from app.subtitle_gui import SubtitleSpellcheckGUI


class UpdateBranchSafetyTests(unittest.TestCase):
    def tool(self, root):
        tool = engine.SubtitleCleanupTool.__new__(engine.SubtitleCleanupTool)
        tool.script_dir = root
        tool.options = {'check_for_updates_at_startup': True}
        tool.update_check_preference_confirmed = True
        return tool

    def test_development_git_branch_blocks_newer_stable_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'.git').mkdir()
            (root/'.git/HEAD').write_text('ref: refs/heads/Ren\'PY-Support\n', encoding='utf-8')
            tool = self.tool(root)
            opener = Mock(side_effect=AssertionError('network accessed'))
            self.assertIsNone(tool.check_for_update(current_version='0.0.1', opener=opener))
            opener.assert_not_called()
            with patch('builtins.input', side_effect=AssertionError('prompted')), patch('builtins.print'):
                self.assertFalse(tool.check_for_updates_cli())

    def test_exported_and_frozen_branch_identity_blocks_manual_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {'schema_version':1, 'version':engine.SCRIPT_VERSION, 'branch':'Ren\'PY-Support'}
            (root/'release_identity.json').write_text(json.dumps(payload), encoding='utf-8')
            for frozen in (False, True):
                with self.subTest(frozen=frozen), patch.object(engine.sys,'frozen',frozen,create=True), patch.object(engine.sys,'_MEIPASS',str(root),create=True):
                    tool = self.tool(root)
                    self.assertIsNone(tool.check_for_update(opener=Mock(side_effect=AssertionError('network'))))
                    with self.assertRaisesRegex(engine.UpdateError, 'branch'):
                        tool.download_update(Mock(), root/'download.zip')
                    self.assertFalse((root/'download.zip').exists())
                    with self.assertRaisesRegex(engine.UpdateError, 'branch'):
                        tool.prepare_update_installation(Mock(), root/'missing.zip', interface='gui')
                    launcher = Mock(side_effect=AssertionError('updater launched'))
                    with self.assertRaisesRegex(engine.UpdateError, 'branch'):
                        tool.launch_prepared_update(Mock(), process_launcher=launcher)
                    launcher.assert_not_called()

    def test_worktree_git_file_detached_head_and_invalid_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gitdir = root/'metadata'; gitdir.mkdir()
            (root/'.git').write_text('gitdir: metadata\n', encoding='utf-8')
            (gitdir/'HEAD').write_text('ref: refs/heads/development\n', encoding='utf-8')
            self.assertEqual(engine.update_branch(root), 'development')
            (gitdir/'HEAD').write_text('0'*40, encoding='utf-8')
            self.assertNotEqual(engine.update_branch(root), 'main')
            (root/'.git').unlink()
            (root/'release_identity.json').write_text('{broken', encoding='utf-8')
            self.assertNotEqual(engine.update_branch(root), 'main')

    def test_main_git_and_legacy_stable_source_are_eligible_but_candidates_are_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(engine.update_branch(root, version='1.1.2'), 'main')
            self.assertNotEqual(engine.update_branch(root, version='1.1.2-c1'), 'main')
            (root/'.git').mkdir()
            (root/'.git/HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
            self.assertEqual(engine.update_branch(root), 'main')

    def test_missing_or_mismatched_frozen_identity_cannot_enable_stable_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(engine.sys,'frozen',True,create=True), patch.object(engine.sys,'_MEIPASS',str(root),create=True):
                self.assertFalse(self.tool(root).public_updates_allowed())
                (root/'release_identity.json').write_text(json.dumps({
                    'schema_version':1,'version':'0.0.0','branch':'main'}), encoding='utf-8')
                self.assertFalse(self.tool(root).public_updates_allowed())

    def test_gui_development_startup_does_not_ask_or_schedule_stable_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'release_identity.json').write_text(json.dumps({
                'schema_version':1, 'version':engine.SCRIPT_VERSION, 'branch':'development'}), encoding='utf-8')
            gui = SubtitleSpellcheckGUI.__new__(SubtitleSpellcheckGUI)
            gui.tool = self.tool(root)
            gui.tool.update_check_preference_confirmed = False
            gui._offer_gui_recovery = Mock()
            gui.messagebox = Mock()
            gui.root = Mock()
            gui._complete_startup()
            gui._begin_update_check()
            gui.messagebox.askyesno.assert_not_called()
            gui.root.after.assert_not_called()
            gui._offer_gui_recovery.assert_called_once()

    def test_source_archive_keeps_branch_protection_after_git_is_removed(self):
        from tools import build_multiplatform_release as builder
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base/'source'
            for relative in builder.RELEASE_FILES:
                target = source/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(project/relative, target)
            (source/'.git').mkdir()
            (source/'.git/HEAD').write_text('ref: refs/heads/RenPy-development\n', encoding='utf-8')
            archive, _ = builder.build_source_release(project_root=source, output_directory=base/'out')
            extracted = base/'extracted'
            with zipfile.ZipFile(archive) as package:
                metadata = json.loads(package.read(f'{builder.ARCHIVE_PREFIX}-{engine.SCRIPT_VERSION}/release_identity.json'))
                self.assertEqual(metadata['branch'], 'RenPy-development')
                package.extractall(extracted)
            home = extracted/f'{builder.ARCHIVE_PREFIX}-{engine.SCRIPT_VERSION}'
            self.assertFalse((home/'.git').exists())
            code = '''from pathlib import Path
from unittest.mock import Mock
from app.subtitle_cleanup import SubtitleCleanupTool,update_branch
tool=SubtitleCleanupTool.__new__(SubtitleCleanupTool)
tool.script_dir=Path.cwd()
assert update_branch(Path.cwd())=='RenPy-development'
opener=Mock(side_effect=AssertionError('network'))
assert tool.check_for_update(current_version='0.0.0',opener=opener) is None
opener.assert_not_called()
'''
            completed = subprocess.run([sys.executable,'-c',code], cwd=home, capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)

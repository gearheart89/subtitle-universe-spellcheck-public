import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import subtitle_cleanup as engine, subtitle_gui as gui_module


class BrowserSearchTests(unittest.TestCase):
    def test_gui_unexpected_browser_error_preserves_review(self):
        gui=gui_module.SubtitleSpellcheckGUI.__new__(gui_module.SubtitleSpellcheckGUI)
        block=engine.SubtitleBlock('1','',['Search word.'])
        issue=SimpleNamespace(file_number=1,subtitle_index=0,line_index=0,word='word')
        session=SimpleNamespace(prepared_blocks={0:[block]})
        gui.tool=mock.Mock()
        gui.tool.search_subtitle_line_in_google.side_effect=RuntimeError('browser unavailable')
        gui.review_session=session;gui.current_issue=issue
        gui.messagebox=mock.Mock();gui.status_value=mock.Mock()
        gui._search_current_line()
        gui.messagebox.showwarning.assert_called_once()
        self.assertIs(gui.review_session,session)
        self.assertIs(gui.current_issue,issue)
        self.assertEqual(block.text_lines,['Search word.'])

    def test_successful_launch_survives_invalid_console_reporting(self):
        tool=engine.SubtitleCleanupTool.__new__(engine.SubtitleCleanupTool)
        block=engine.SubtitleBlock('1','',['Search this word.'])
        with mock.patch.object(engine.webbrowser,'open',return_value=True) as browser, \
                mock.patch('builtins.print',side_effect=OSError(6,'The handle is invalid')):
            self.assertTrue(tool.search_subtitle_line_in_google(block,'word'))
        browser.assert_called_once()

    def test_gui_uses_real_search_helper_without_console_output_or_false_warning(self):
        gui=gui_module.SubtitleSpellcheckGUI.__new__(gui_module.SubtitleSpellcheckGUI)
        block=engine.SubtitleBlock('1','',['First line.','Second word here.'])
        issue=SimpleNamespace(file_number=1,subtitle_index=0,line_index=1,word='word')
        session=SimpleNamespace(prepared_blocks={0:[block]})
        gui.tool=engine.SubtitleCleanupTool.__new__(engine.SubtitleCleanupTool)
        gui.review_session=session;gui.current_issue=issue
        gui.messagebox=mock.Mock();gui.status_value=mock.Mock()
        with mock.patch.object(engine.webbrowser,'open',return_value=True) as browser, \
                mock.patch('builtins.print',side_effect=OSError(6,'The handle is invalid')) as console:
            gui._search_current_line()
        browser.assert_called_once_with('https://www.google.com/search?q=Second+word+here.',new=2)
        console.assert_not_called()
        gui.messagebox.showwarning.assert_not_called()
        self.assertIn('Opened Google search',gui.status_value.set.call_args.args[0])
        self.assertIs(gui.review_session,session);self.assertIs(gui.current_issue,issue)
        self.assertEqual(block.text_lines,['First line.','Second word here.'])

    def test_real_browser_failures_and_empty_text_still_report_failure(self):
        tool=engine.SubtitleCleanupTool.__new__(engine.SubtitleCleanupTool)
        block=engine.SubtitleBlock('1','',['Search word.'])
        for value in (False,RuntimeError('browser unavailable'),OSError(6,'browser failure')):
            with self.subTest(value=value), mock.patch.object(engine.webbrowser,'open',side_effect=value if isinstance(value,Exception) else None,return_value=False) as browser, \
                    mock.patch('builtins.print',side_effect=OSError(6,'invalid console')):
                self.assertFalse(tool.search_subtitle_line_in_google(block,'word'))
                browser.assert_called_once()
        with mock.patch.object(engine.webbrowser,'open') as browser,mock.patch('builtins.print'):
            self.assertFalse(tool.search_subtitle_line_in_google(engine.SubtitleBlock('1','',['  ']),'word'))
            browser.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Requires the Windows detached-console API')
    def test_real_windows_detached_console_does_not_turn_success_into_failure(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            result=Path(directory)/'result.json'
            script = r'''import ctypes,json,os,sys
from pathlib import Path
from unittest import mock
sys.path.insert(0,sys.argv[1])
from app.subtitle_cleanup import SubtitleCleanupTool,SubtitleBlock
report={'console_attached_before':sys.stdout.isatty(),'detached':bool(ctypes.windll.kernel32.FreeConsole())}
try:
    print('Detached console probe',flush=True)
except OSError as error:
    report['console_winerror']=getattr(error,'winerror',None)
try:
    with mock.patch('app.subtitle_cleanup.webbrowser.open',return_value=True) as browser:
        report['opened']=SubtitleCleanupTool.__new__(SubtitleCleanupTool).search_subtitle_line_in_google(SubtitleBlock('1','',['Search word.']),'word')
        report['requests']=browser.call_count
except Exception as error:
    report['error']=str(error)
Path(sys.argv[2]).write_text(json.dumps(report),encoding='utf-8')
os._exit(0)
'''
            startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
            child=subprocess.run([sys.executable,'-c',script,str(root),str(result)],
                creationflags=subprocess.CREATE_NEW_CONSOLE,startupinfo=startup,timeout=30)
            self.assertEqual(child.returncode,0)
            report=json.loads(result.read_text())
            self.assertTrue(report['console_attached_before'],report)
            self.assertTrue(report['detached'],report)
            self.assertEqual(report.get('console_winerror'),6,report)
            self.assertTrue(report.get('opened'),report)
            self.assertEqual(report.get('requests'),1,report)

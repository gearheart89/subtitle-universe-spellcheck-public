"""Live Tk checks for the shared tooltip column and centered move dialog."""
import unittest
from unittest.mock import Mock, patch

from app import subtitle_gui
from test_spellcheck import make_tool


class SharedGuiGeometryTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from tkinter import ttk
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest('Live Tk display unavailable: ' + str(error))
        self.addCleanup(self.root.destroy)
        self.root.attributes('-alpha', 0.0)
        self.root.geometry('1000x720+130+90')
        self.root.update()
        self.gui = subtitle_gui.SubtitleSpellcheckGUI.__new__(subtitle_gui.SubtitleSpellcheckGUI)
        self.gui.root = self.root
        self.gui.tk, self.gui.ttk = tk, ttk
        self.gui.tool = make_tool()
        self.gui.messagebox = Mock()
        self.gui._attach_tooltip = Mock()

    @staticmethod
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from SharedGuiGeometryTests.descendants(child)

    def test_tooltips_share_actual_horizontal_center_in_every_category_and_theme(self):
        self.gui.options_detail_frame = self.gui.ttk.Frame(self.root)
        self.gui.options_detail_frame.pack(fill='both', expand=True)
        for theme in ('Ocean', 'Dark'):
            self.gui.COLORS = subtitle_gui.resolve_theme(theme)
            for title, keys in subtitle_gui.OPTION_GROUPS:
                with self.subTest(theme=theme, category=title):
                    self.gui._render_option_group(title, keys)
                    self.root.update_idletasks()
                    labels = [widget for widget in self.descendants(self.gui.options_detail_frame)
                              if widget.winfo_class() == 'Label' and widget.cget('text') in {'?', 'Tooltips'}]
                    self.assertEqual(len(labels), len(keys) + 1)
                    centers = [widget.winfo_rootx() + widget.winfo_width() // 2 for widget in labels]
                    self.assertLessEqual(max(centers) - min(centers), 1)

    def test_move_dialog_centers_over_moved_parent_and_cancel_changes_nothing(self):
        self.gui.tool.list_universes = Mock(return_value=['Show'])
        event = {'target': 'user', 'base_language': 'american', 'list': 'words', 'word': 'example'}
        positions = []
        for x, y in ((130, 90), (280, 160)):
            self.root.geometry(f'1000x720+{x}+{y}')
            self.root.update()
            def inspect_and_cancel(window):
                self.root.update_idletasks()
                expected = subtitle_gui.centered_child_position(
                    (self.root.winfo_rootx(), self.root.winfo_rooty(), self.root.winfo_width(), self.root.winfo_height()),
                    (window.winfo_width(), window.winfo_height()),
                    (window.winfo_screenwidth(), window.winfo_screenheight()))
                self.assertEqual((window.winfo_x(), window.winfo_y()), expected)
                positions.append(expected)
                cancel = next(widget for widget in self.descendants(window)
                              if widget.winfo_class() == 'TButton' and widget.cget('text') == 'Cancel')
                cancel.invoke()
            with patch.object(self.root, 'wait_window', side_effect=inspect_and_cancel):
                self.assertIsNone(self.gui._prompt_recent_destination(event))
        self.assertNotEqual(positions[0], positions[1])
        self.gui.tool.log_event.assert_not_called()

    def test_universe_move_confirmation_names_every_entry_and_can_be_declined(self):
        self.gui.tool.list_universes = Mock(return_value=['Show'])
        events = [{'target': 'user', 'base_language': 'american', 'list': 'words', 'word': word}
                  for word in ('firstword', 'secondword')]
        for accept in (False, True):
            self.gui.messagebox.reset_mock()
            self.gui.messagebox.askyesno.return_value = accept
            def submit_then_cancel_if_declined(window):
                buttons = [widget for widget in self.descendants(window) if widget.winfo_class() == 'TButton']
                next(widget for widget in buttons if widget.cget('text') == 'Move').invoke()
                if not accept:
                    self.assertTrue(window.winfo_exists())
                    next(widget for widget in buttons if widget.cget('text') == 'Cancel').invoke()
            with patch.object(self.root, 'wait_window', side_effect=submit_then_cancel_if_declined):
                result = self.gui._prompt_recent_destination(events)
            self.assertEqual(result, ('universe', 'Show', None) if accept else None)
            self.gui.messagebox.askyesno.assert_called_once()
            message = self.gui.messagebox.askyesno.call_args.args[1]
            for value in ('firstword', 'secondword', 'Show'):
                self.assertIn(value, message)
        self.gui.tool.log_event.assert_not_called()


if __name__ == '__main__':
    unittest.main()

import unittest
from pathlib import Path
from unittest.mock import Mock

from app.subtitle_cleanup import DEFAULT_OPTIONS, DictionaryContext, SubtitleCleanupTool


class FormattingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tool = SubtitleCleanupTool()
        self.context = DictionaryContext(language="american")

    def test_capitalization_defaults_to_ask_always(self):
        self.assertEqual(DEFAULT_OPTIONS["capitalization_mode"], "ask_always")

    def test_source_capitalization_preserves_source_case(self):
        self.tool.options["capitalization_mode"] = "source"
        result = self.tool.format_text_lines(
            ["i'M READY, MALP."],
            DictionaryContext(language="american", acronym_set={"MALP"}),
        )
        self.assertEqual(result, ["i'M READY, MALP."])

    def test_subtitle_aware_capitalization_uses_existing_repairs(self):
        self.tool.options["capitalization_mode"] = "subtitle"
        result = self.tool.format_text_lines(["i think i'm ready."], self.context)
        self.assertEqual(result, ["I think I'm ready."])

    def test_all_caps_uppercases_visible_text_without_changing_tags(self):
        self.tool.options["capitalization_mode"] = "all_caps"
        result = self.tool.format_text_lines(
            ["<i>I'm ready, Colonel.</i>"], self.context
        )
        self.assertEqual(result, ["<i>I'M READY, COLONEL.</i>"])

    def test_v023_balances_and_lowercases_standalone_article(self):
        result = self.tool.format_text_lines(
            ["LET'S JUST MAKE AS BIG", "A DENT AS POSSIBLE, OK?"],
            self.context,
        )
        self.assertEqual(result, ["Let's just make as big a dent as possible, OK?"])

    def test_closing_quote_is_not_a_speaker_break(self):
        result = self.tool.format_text_lines(
            ["WE CALL THE OUR", '"GOA\'ULD BUSTERS."'],
            self.context,
        )
        self.assertEqual(result, ['We call the our "Goa\'uld busters."'])

    def test_real_dropped_speaker_break_still_splits(self):
        result = self.tool.format_text_lines(["WE HAVE TO GO.NOW?!"], self.context)
        self.assertEqual(result, ["- We have to go.", "- Now?!"])

    def test_standalone_speaker_label_remains_a_hard_break(self):
        result = self.tool.format_text_lines(
            ["MAN ON RADIO:", "Delta five-point-bravo,", "our ETA is five minutes."],
            self.context,
        )

        self.assertEqual(
            result,
            ["Man on radio:", "Delta five-point-bravo, our ETA is five minutes."],
        )

        dotted_result = self.tool.format_text_lines(
            ["MAN ON P.A.:", "SECURITY TO THE INFIRMARY."],
            self.context,
        )
        self.assertEqual(
            dotted_result,
            ["Man on P.A.:", "Security to the infirmary."],
        )

    def test_dropped_speaker_detection_uses_the_complete_wrapped_cue(self):
        result = self.tool.format_text_lines(
            ["GOOD GUESS", "ON THE GREEN.THANKS."],
            self.context,
        )

        self.assertEqual(result, ["- Good guess on the green.", "- Thanks."])

    def test_dropped_speaker_detection_keeps_wrapped_second_speaker_text(self):
        result = self.tool.format_text_lines(
            ["DID YOU SEE THAT?IT'S COMING", "RIGHT TOWARDS US."],
            self.context,
        )

        self.assertEqual(
            result,
            ["- Did you see that?", "- It's coming right towards us."],
        )

    def test_dropped_speaker_detection_retains_existing_dash(self):
        self.assertEqual(
            self.tool.detect_dropped_speaker_breaks("- Ready.Go."),
            ["- Ready.", "- Go."],
        )

    def test_concatenated_dialogue_is_not_mistaken_for_a_dotted_speaker_label(self):
        result = self.tool.format_text_lines(
            ["I'M SORRY.HAMMOND:", "I'M SORRY, TOO,"],
            self.context,
        )

        self.assertEqual(
            result,
            ["- I'm sorry.", "- Hammond: I'm sorry, too,"],
        )

    def test_universe_names_preserve_authoritative_casing(self):
        context = DictionaryContext(
            language="american",
            universe="Stargate SG-1",
            universe_names={
                "o'neill": "O'Neill",
                "teal'c": "Teal'c",
                "goa'uld": "Goa'uld",
                "tok'ra": "Tok'ra",
                "sg": "SG",
            },
        )

        result = self.tool.format_text_lines(
            ["O'NEILL AND TEAL'C FOUGHT THE GOA'ULD WITH SG-1 AND THE TOK'RA."],
            context,
        )

        self.assertEqual(
            result,
            ["O'Neill and Teal'c fought the", "Goa'uld with SG-1 and the Tok'ra."],
        )

    def test_am_is_contextual_not_a_global_acronym(self):
        result = self.tool.format_text_lines(
            ["I AM READY AT 4:00 AM."],
            self.context,
        )

        self.assertEqual(result, ["I am ready at 4:00 AM."])

    def test_possessive_acronym_preserves_authoritative_casing(self):
        self.context.universe_acronyms.add("SGC")
        self.context.acronym_set.add("SGC")
        result = self.tool.format_text_lines(
            ["THE SGC'S TEAM IS READY."],
            self.context,
        )

        self.assertEqual(result, ["The SGC's team is ready."])

    def test_dotted_normalization_only_changes_recognized_acronyms(self):
        context = DictionaryContext(
            language="american",
            universe_names={"nid": "NID"},
            universe_acronyms={"SGC"},
        )
        context.acronym_set.update(context.universe_acronyms)

        result = self.tool.normalize_dotted_acronyms(
            "Meet at 4:00 a.m., i.e., near the U.S. S.G.C. or N.I.D. office.",
            context,
        )

        self.assertEqual(
            result,
            "Meet at 4:00 a.m., i.e., near the US SGC or NID office.",
        )

    def test_dotted_acronym_normalization_preserves_sentence_punctuation(self):
        context = DictionaryContext(
            language="american",
            universe_names={"gdo": "GDO", "malp": "MALP", "ter": "TER"},
        )
        context.acronym_set.update({"GDO", "MALP", "TER"})

        self.assertEqual(
            self.tool.normalize_dotted_acronyms(
                "PACK THE G.D.O.s. BRING T.E.R.s AND A M.A.L.P.",
                context,
            ),
            "PACK THE GDOs. BRING TERs AND A MALP.",
        )

    def test_dotted_acronym_at_wrapped_line_end_does_not_invent_period(self):
        self.tool.options["adjust_subtitle_line_count"] = False

        result = self.tool.format_text_lines(
            ["directly from the U.S.", "power grid."],
            self.context,
        )

        self.assertEqual(result, ["directly from the US", "power grid."])

    def test_uppercase_repair_preserves_acronym_plural_casing(self):
        context = DictionaryContext(language="american")
        context.acronym_set.update({"GDO", "MALP", "TER"})

        result = self.tool.format_text_lines(
            ["THE MALPS AND GDOS USED TERS."],
            context,
        )

        self.assertEqual(result, ["The MALPs and GDOs used TERs."])

    def test_spellcheck_accepts_acronym_plurals_and_possessives(self):
        context = DictionaryContext(language="american")
        context.acronym_set.update({"GDO", "MALP"})

        self.assertTrue(context.is_known_word("MALPs"))
        self.assertTrue(context.is_known_word("GDO's"))

    def test_explicit_universe_acronyms_restore_casing_and_inflections(self):
        context = DictionaryContext(
            language="american",
            universe="Stargate SG-1",
            universe_acronyms={"MALP", "GDO", "SGC"},
        )
        context.acronym_set.update(context.universe_acronyms)

        result = self.tool.format_text_lines(
            ["Send the malp and gdos to the s.g.c."], context
        )

        self.assertEqual(result, ["Send the MALP and GDOs to the SGC."])

    def test_uppercase_repair_runs_before_dropped_speaker_detection(self):
        order = []
        original_uppercase = self.tool.repair_mostly_uppercase_lines
        original_speaker = self.tool.detect_dropped_speaker_breaks
        self.tool.repair_mostly_uppercase_lines = Mock(
            side_effect=lambda lines, context, force_uppercase=None: (
                order.append("uppercase")
                or original_uppercase(lines, context, force_uppercase)
            )
        )
        self.tool.detect_dropped_speaker_breaks = Mock(
            side_effect=lambda line: (
                order.append("speaker") or original_speaker(line)
            )
        )

        self.tool.format_text_lines(["WE HAVE TO GO.NOW?!"], self.context)

        self.assertLess(order.index("uppercase"), order.index("speaker"))

    def test_bracketed_annotation_does_not_hide_uppercase_dialogue(self):
        context = DictionaryContext(
            language="american",
            universe_names={"o'neill": "O'Neill"},
        )

        result = self.tool.format_text_lines(
            ["[O'NEILL]: I AM READY."],
            context,
        )

        self.assertEqual(result, ["[O'Neill]: I am ready."])

    def test_authoritative_universe_casing_extends_to_common_suffixes(self):
        context = DictionaryContext(
            language="american",
            universe_names={
                "asgard": "Asgard",
                "goa'uld": "Goa'uld",
                "jaffa": "Jaffa",
            },
        )

        result = self.tool.format_text_lines(
            ["THE GOA'ULDS MET THE ASGARDS AND REBEL JAFFAS WHILE DE-GOA'ULDING."],
            context,
        )

        self.assertEqual(
            result,
            ["The Goa'ulds met the Asgards and", "rebel Jaffas while de-Goa'ulding."],
        )

    def test_multiword_names_preserve_phrase_casing(self):
        context = DictionaryContext(
            language="american",
            universe_names={
                "oma desala": "Oma Desala",
                "cordai plains": "Cordai Plains",
                "hebron of paraval": "Hebron of Paraval",
            },
        )

        result = self.tool.repair_mostly_uppercase_lines(
            ["OMA DESALA MET HEBRON OF PARAVAL ON THE CORDAI PLAINS."],
            context,
        )

        self.assertEqual(
            result,
            ["Oma Desala met Hebron of Paraval on the Cordai Plains."],
        )

    def test_multiword_name_components_are_not_known_outside_phrase(self):
        context = DictionaryContext(
            language="american",
            universe_names={"hebron of paraval": "Hebron of Paraval"},
        )

        self.assertFalse(context.is_known_word("Hebron"))
        self.assertFalse(context.is_known_word("Paraval"))

    def test_multiword_name_casing_is_restored_across_line_break(self):
        context = DictionaryContext(
            language="american",
            universe_names={"vala mal doran": "Vala Mal Doran"},
        )

        result = self.tool.format_text_lines(["VALA MAL", "DORAN ARRIVED."], context)

        self.assertEqual(result, ["Vala Mal Doran arrived."])

    def test_mixed_case_substitution_does_not_hide_source_uppercase_line(self):
        context = DictionaryContext(
            language="american",
            universe_names={"teal'c": "Teal'c", "za'tarc": "Za'tarc"},
            substitutions={"teald": "Teal'c", "zatarc": "Za'tarc"},
        )

        result = self.tool.format_text_lines(
            ["TEALD MET ZATARC."],
            context,
        )

        self.assertEqual(result, ["Teal'c met Za'tarc."])

    def test_pronoun_i_stays_uppercase_on_a_wrapped_continuation(self):
        result = self.tool.format_text_lines(
            ["WELL, ANYWAYS,", "I PUT TOGETHER"],
            self.context,
        )

        self.assertEqual(result, ["Well, anyways, I put together"])

    def test_pronoun_i_contraction_stays_uppercase_during_repair(self):
        result = self.tool.format_text_lines(
            ["NO, I'M NOT.YES, YOU ARE"],
            self.context,
        )

        self.assertEqual(result, ["- No, I'm not.", "- Yes, you are"])

    def test_lowercase_pronoun_i_is_repaired_in_mixed_case_dialogue(self):
        self.tool.options["adjust_subtitle_line_count"] = False
        self.tool.options["detect_dropped_speaker_breaks"] = False

        result = self.tool.format_text_lines(
            ['Was that "i told you so," colonel? i\'m sure i’d remember.'],
            self.context,
        )

        self.assertEqual(
            result,
            ['Was that "I told you so," colonel? I\'m sure I’d remember.'],
        )

    def test_pronoun_i_repair_preserves_tags_abbreviations_and_urls(self):
        self.tool.options["adjust_subtitle_line_count"] = False
        self.tool.options["detect_dropped_speaker_breaks"] = False

        result = self.tool.format_text_lines(
            ["<i>i said i'd check i.e. https://example.test/i/help.</i>"],
            self.context,
        )

        self.assertEqual(
            result,
            ["<i>I said I'd check i.e. https://example.test/i/help.</i>"],
        )

    def test_lowercase_pronoun_i_repair_can_be_disabled(self):
        self.tool.options["capitalize_lowercase_pronoun_i"] = False
        self.tool.options["adjust_subtitle_line_count"] = False
        self.tool.options["detect_dropped_speaker_breaks"] = False

        result = self.tool.format_text_lines(["i think i'm ready."], self.context)

        self.assertEqual(result, ["i think i'm ready."])

    def test_dropped_speaker_detection_ignores_ellipses(self):
        self.assertEqual(
            self.tool.detect_dropped_speaker_breaks("I...WANT?"),
            ["I...WANT?"],
        )

    def test_dropped_speaker_detection_ignores_dotted_forms(self):
        self.assertEqual(
            self.tool.detect_dropped_speaker_breaks("OR THE O.S.I. WILL."),
            ["OR THE O.S.I. WILL."],
        )
        self.assertEqual(
            self.tool.detect_dropped_speaker_breaks("Ph.D, astrophysics."),
            ["Ph.D, astrophysics."],
        )
        self.assertEqual(
            self.tool.detect_dropped_speaker_breaks("P.A: INCOMING TRAVELER."),
            ["P.A: INCOMING TRAVELER."],
        )

    def test_uppercase_repair_preserves_unrecognized_dotted_form(self):
        result = self.tool.format_text_lines(
            ["OR THE O.S.I. WILL."],
            self.context,
        )

        self.assertEqual(result, ["Or the O.S.I. will."])

    def test_dropped_speaker_detection_ignores_bare_domain_names(self):
        self.assertEqual(
            self.tool.detect_dropped_speaker_breaks("ON ARCHAEOLOGY.COM, SO..."),
            ["ON ARCHAEOLOGY.COM, SO..."],
        )

    def test_ellipsis_conversion_is_opt_in_and_early(self):
        self.tool.options["convert_double_hyphen_and_three_dots_to_ellipsis"] = True
        result = self.tool.format_text_lines(["WAIT--WHAT... REALLY?"], self.context)
        self.assertEqual(result, ["Wait…what… really?"])

    def test_backup_groups_root_and_immediate_children(self):
        root = Path("C:/Example/Subtitle Project")
        root_subtitle = root / "root.srt"
        firefly_subtitle = root / "Firefly" / "Season 01" / "episode.srt"
        stargate_subtitle = root / "Stargate" / "Season 02" / "episode.SRT"

        groups = self.tool.backup_groups(
            root,
            [root_subtitle, firefly_subtitle, stargate_subtitle],
        )

        self.assertEqual(set(groups), {root, root / "Firefly", root / "Stargate"})
        self.assertEqual(groups[root], [root_subtitle])
        self.assertEqual(groups[root / "Firefly"], [firefly_subtitle])
        self.assertEqual(groups[root / "Stargate"], [stargate_subtitle])


if __name__ == "__main__":
    unittest.main()

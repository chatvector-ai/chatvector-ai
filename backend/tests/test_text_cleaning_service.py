"""Unit tests for the text cleaning and normalization service.

clean_text() uses a "nuclear" flattening approach: ALL line breaks are
converted to spaces, producing a single flat prose string. This maximises
reflow of PDF-extracted fragments while keeping the implementation simple.
"""

import pytest

from services.text_cleaning_service import clean_text


class TestEdgeCases:
    def test_empty_string_returns_empty(self):
        assert clean_text("") == ""

    def test_whitespace_only_returns_empty(self):
        assert clean_text("   \n\n\t  ") == ""

    def test_single_word_unchanged(self):
        assert clean_text("hello") == "hello"


class TestUnicodeNormalization:
    def test_ligatures_are_expanded(self):
        # ﬁ (U+FB01 LATIN SMALL LIGATURE FI) → "fi"
        result = clean_text("ﬁle ﬂow")
        assert result == "file flow"

    def test_non_breaking_space_becomes_regular_space(self):
        # U+00A0 NON-BREAKING SPACE → regular space, then collapsed
        result = clean_text("hello\u00a0world")
        assert result == "hello world"

    def test_fullwidth_digits_normalized(self):
        result = clean_text("\uff11\uff12\uff13")
        assert result == "123"


class TestControlCharacterRemoval:
    def test_null_bytes_removed(self):
        result = clean_text("hel\x00lo")
        assert result == "hello"

    def test_bell_and_backspace_removed(self):
        result = clean_text("te\x07st\x08")
        assert result == "test"

    def test_vertical_tab_and_form_feed_removed(self):
        # \x0b and \x0c are stripped before line-break flattening
        result = clean_text("a\x0bb\x0cc")
        assert result == "abc"

    def test_newlines_become_spaces(self):
        result = clean_text("line one\nline two")
        assert result == "line one line two"

    def test_tabs_become_spaces(self):
        result = clean_text("col1\tcol2")
        assert result == "col1 col2"


class TestSoftHyphenRemoval:
    def test_soft_hyphen_removed(self):
        # U+00AD SOFT HYPHEN should be invisible and removed
        result = clean_text("connec\u00adtion")
        assert result == "connection"

    def test_regular_hyphen_preserved(self):
        result = clean_text("well-known")
        assert result == "well-known"


class TestHyphenatedLineBreaks:
    def test_hyphenated_line_break_rejoined(self):
        # PDF word-wrap artifact: "connec-\ntion" → "connection"
        result = clean_text("connec-\ntion")
        assert result == "connection"

    def test_hyphenated_line_break_with_context(self):
        result = clean_text("This is a connec-\ntion example.")
        assert result == "This is a connection example."

    def test_trailing_hyphen_before_blank_line_not_joined(self):
        # Hyphen before a blank line is NOT a word-break artifact
        result = clean_text("some text-\n\nnext paragraph")
        assert "text-" in result

    def test_standalone_list_hyphen_preserved(self):
        result = clean_text("- first item\n- second item")
        assert "- first item" in result
        assert "- second item" in result


class TestLineBreakFlattening:
    """All line breaks — regardless of type or surrounding punctuation — become spaces."""

    def test_single_newline_becomes_space(self):
        assert clean_text("first\nsecond") == "first second"

    def test_crlf_becomes_space(self):
        assert clean_text("first\r\nsecond") == "first second"

    def test_cr_becomes_space(self):
        assert clean_text("first\rsecond") == "first second"

    def test_multiple_newlines_become_single_space(self):
        assert clean_text("first\n\n\nsecond") == "first second"

    def test_blank_lines_become_single_space(self):
        assert clean_text("para one\n\n\n\npara two") == "para one para two"

    def test_punctuated_lines_also_joined(self):
        # Terminal punctuation does NOT prevent joining in the nuclear approach
        result = clean_text("Sentence one.\nSentence two.")
        assert result == "Sentence one. Sentence two."

    def test_trailing_whitespace_removed(self):
        result = clean_text("hello   \nworld  ")
        assert result == "hello world"

    def test_leading_newlines_stripped(self):
        assert clean_text("\n\nhello") == "hello"

    def test_trailing_newlines_stripped(self):
        assert clean_text("hello\n\n") == "hello"


class TestWhitespaceNormalization:
    def test_multiple_spaces_collapsed(self):
        assert clean_text("hello     world") == "hello world"

    def test_tab_sequence_collapsed_to_space(self):
        assert clean_text("col1\t\t\tcol2") == "col1 col2"

    def test_mixed_spaces_and_tabs_collapsed(self):
        assert clean_text("a\t  \tb") == "a b"

    def test_single_space_untouched(self):
        assert clean_text("hello world") == "hello world"

    def test_surrounding_whitespace_stripped(self):
        assert clean_text("   hello world   ") == "hello world"


class TestBulletRemoval:
    def test_filled_circle_bullet_removed(self):
        result = clean_text("● First item\n● Second item")
        assert "●" not in result
        assert "First item" in result
        assert "Second item" in result

    def test_dot_bullet_removed(self):
        result = clean_text("• Option A\n• Option B")
        assert "•" not in result
        assert "Option A" in result

    def test_small_square_bullet_removed(self):
        result = clean_text("▪ Step one\n▪ Step two")
        assert "▪" not in result
        assert "Step one" in result

    def test_hollow_circle_bullet_removed(self):
        result = clean_text("◦ Sub-item")
        assert "◦" not in result
        assert "Sub-item" in result

    def test_mixed_bullets_all_removed(self):
        result = clean_text("● Item A\n• Item B\n▪ Item C\n◦ Item D")
        for bullet in ("●", "•", "▪", "◦"):
            assert bullet not in result

    def test_regular_text_unaffected_by_bullet_removal(self):
        result = clean_text("No bullets here, just normal text.")
        assert result == "No bullets here, just normal text."


class TestPDFReflowArtifacts:
    """PDF extraction often produces one word or phrase per line; all get merged."""

    def test_word_per_line_fragments_joined(self):
        result = clean_text("users\nto\nhave\nconversational")
        assert result == "users to have conversational"

    def test_uppercase_fragments_joined(self):
        result = clean_text("Users\nTo\nHave\nConversational")
        assert result == "Users To Have Conversational"

    def test_mixed_case_fragments_joined(self):
        result = clean_text("allow\nUsers\nto access\nData")
        assert result == "allow Users to access Data"

    def test_multi_line_prose_fully_joined(self):
        result = clean_text("The quick brown fox\njumps over\nthe lazy dog.")
        assert result == "The quick brown fox jumps over the lazy dog."

    def test_no_newlines_in_output(self):
        raw = "line one\nline two\nline three"
        result = clean_text(raw)
        assert "\n" not in result


class TestRealWorldPatterns:
    def test_pdf_page_with_headers_and_footers(self):
        """Simulates a PDF page dump with header/footer blank-line padding."""
        raw = (
            "\n\n\n"
            "CHAPTER 1\n\n\n\n"
            "Introduction\n\n"
            "This document describes the system archi-\n"
            "tecture and its components.\n\n\n\n\n"
            "Page 1\n"
        )
        result = clean_text(raw)
        assert "architecture" in result   # hyphenated break rejoined
        assert "\n" not in result         # no stray newlines
        assert "CHAPTER 1" in result
        assert "Page 1" in result

    def test_txt_file_with_tabs_and_multiple_spaces(self):
        raw = "Name:\t\tJohn   Doe\nAge:\t\t 30\nCity:   New   York"
        result = clean_text(raw)
        assert result == "Name: John Doe Age: 30 City: New York"

    def test_combined_ligature_and_hyphen_artifact(self):
        """PDF may have both ligatures and hyphenated breaks in the same text."""
        raw = "The ﬁle con-\ntains important infor-\nmation."
        result = clean_text(raw)
        assert result == "The file contains important information."

    def test_unicode_normalization_with_control_chars(self):
        """Control characters embedded among normal unicode text."""
        raw = "Hello\x00 \uff37\uff4f\uff52\uff4c\uff44!"
        result = clean_text(raw)
        assert result == "Hello World!"

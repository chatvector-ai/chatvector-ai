"""Unit tests for the text cleaning and normalization service."""

import pytest

from services.text_cleaning_service import clean_text


class TestEdgeCases:
    def test_empty_string_returns_empty(self):
        assert clean_text("") == ""

    def test_whitespace_only_returns_empty(self):
        assert clean_text("   \n\n\t  ") == ""

    def test_none_like_passthrough_is_not_called(self):
        # Sanity: function is only called with str; empty string is safe
        result = clean_text("")
        assert result == ""


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
        # Fullwidth digit characters normalized to ASCII
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
        result = clean_text("a\x0bb\x0cc")
        assert result == "abc"

    def test_newlines_preserved(self):
        result = clean_text("line one\nline two")
        assert result == "line one\nline two"

    def test_tabs_preserved_within_line(self):
        # Tabs at the start of a line are kept (indented content)
        result = clean_text("header\n\tindented")
        assert result == "header\n\tindented"


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

    def test_hyphenated_line_break_with_leading_space(self):
        # Hyphen at end of line followed by word on next line
        result = clean_text("This is a connec-\ntion example.")
        assert result == "This is a connection example."

    def test_hyphen_at_end_of_line_before_blank_line_preserved(self):
        # A trailing hyphen before a blank line is NOT a word-break artifact
        result = clean_text("some text-\n\nnext paragraph")
        assert "text-" in result

    def test_standalone_hyphen_line_not_joined(self):
        # A line that is just "- item" (list marker) should not be mangled
        result = clean_text("- first item\n- second item")
        assert "- first item" in result
        assert "- second item" in result


class TestLineEndingNormalization:
    def test_windows_crlf_normalized(self):
        result = clean_text("line one\r\nline two")
        assert result == "line one\nline two"

    def test_old_mac_cr_normalized(self):
        result = clean_text("line one\rline two")
        assert result == "line one\nline two"

    def test_mixed_line_endings_normalized(self):
        result = clean_text("a\r\nb\rc\nd")
        assert result == "a\nb\nc\nd"


class TestTrailingWhitespace:
    def test_trailing_spaces_stripped_per_line(self):
        result = clean_text("hello   \nworld  ")
        assert result == "hello\nworld"

    def test_trailing_tab_stripped_per_line(self):
        result = clean_text("line\t")
        assert result == "line"

    def test_multiple_leading_spaces_collapsed(self):
        # Multiple leading spaces are collapsed to one — PDF indentation is
        # a layout artifact and not semantically meaningful for prose documents.
        result = clean_text("header\n    indented line\nfooter")
        lines = result.split("\n")
        assert lines[1] == " indented line"


class TestBlankLineCollapse:
    def test_three_blank_lines_collapsed_to_two(self):
        result = clean_text("para one\n\n\n\npara two")
        assert result == "para one\n\npara two"

    def test_many_blank_lines_collapsed_to_two(self):
        result = clean_text("a\n\n\n\n\n\n\nb")
        assert result == "a\n\nb"

    def test_two_blank_lines_preserved(self):
        result = clean_text("a\n\nb")
        assert result == "a\n\nb"

    def test_single_blank_line_preserved(self):
        result = clean_text("a\n\nb")
        assert result == "a\n\nb"


class TestInlineSpaceCollapse:
    def test_multiple_spaces_collapsed(self):
        result = clean_text("hello     world")
        assert result == "hello world"

    def test_mixed_spaces_and_tabs_collapsed(self):
        result = clean_text("col1\t\t\tcol2")
        assert result == "col1 col2"

    def test_single_space_untouched(self):
        result = clean_text("hello world")
        assert result == "hello world"


class TestFinalStrip:
    def test_leading_newlines_stripped(self):
        result = clean_text("\n\nhello")
        assert result == "hello"

    def test_trailing_newlines_stripped(self):
        result = clean_text("hello\n\n")
        assert result == "hello"

    def test_surrounding_whitespace_stripped(self):
        result = clean_text("   hello world   ")
        assert result == "hello world"


class TestRealWorldPatterns:
    def test_pdf_page_with_header_and_footer_whitespace(self):
        """Simulates a PDF page dump with extra blank lines from header/footer separation."""
        raw = (
            "\n\n\n"
            "CHAPTER 1\n\n\n\n"
            "Introduction\n\n"
            "This document describes the system archi-\n"
            "tecture and its components.\n\n\n\n\n"
            "Page 1\n"
        )
        result = clean_text(raw)
        # Hyphenated break rejoined
        assert "architecture" in result
        # Excess blank lines collapsed
        assert "\n\n\n" not in result
        # Page number line preserved (we don't strip arbitrary lines)
        assert "Page 1" in result

    def test_txt_file_with_inconsistent_whitespace(self):
        """Simulates a TXT dump with tabs and multiple spaces."""
        raw = "Name:\t\tJohn   Doe\nAge:\t\t 30\nCity:   New   York"
        result = clean_text(raw)
        assert result == "Name: John Doe\nAge: 30\nCity: New York"

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

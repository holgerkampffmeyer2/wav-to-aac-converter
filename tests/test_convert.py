#!/usr/bin/env python3
"""Unit tests for convert.py using stdlib unittest."""

import unittest
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from convert import (
    extract_metadata_from_filename,
    extract_handles,
    clean_title_for_search,
    OG_IMAGE_RE,
    BANDCAMP_URL_RE,
    SNDCLOUD_ARTWORK_RE,
    HANDLE_RE,
)


class TestFilenameParsing(unittest.TestCase):
    """Tests for artist/title extraction from filenames."""

    def test_standard_format(self):
        """Standard 'Artist - Title' format."""
        artist, title = extract_metadata_from_filename("Artist - Title.wav")
        self.assertEqual(artist, "Artist")
        self.assertEqual(title, "Title")

    def test_title_only(self):
        """No artist separator."""
        artist, title = extract_metadata_from_filename("Just Title.wav")
        self.assertEqual(artist, "")
        self.assertEqual(title, "Just Title")

    def test_remix_in_title(self):
        """Remix info should be preserved in title."""
        artist, title = extract_metadata_from_filename("Artist - Song (Remix).wav")
        self.assertEqual(artist, "Artist")
        self.assertEqual(title, "Song (Remix)")

    def test_multiple_separators(self):
        """Only first separator is used."""
        artist, title = extract_metadata_from_filename("Artist - Title - Extra.wav")
        self.assertEqual(artist, "Artist")
        self.assertEqual(title, "Title - Extra")

    def test_no_extension(self):
        """Handle files without extension."""
        artist, title = extract_metadata_from_filename("Artist - Title")
        self.assertEqual(artist, "Artist")
        self.assertEqual(title, "Title")

    def test_extra_whitespace(self):
        """Handle extra whitespace."""
        artist, title = extract_metadata_from_filename("  Artist  -  Title  .wav")
        self.assertEqual(artist, "Artist")
        self.assertEqual(title, "Title")

    def test_feat_in_title(self):
        """Featuring info preserved."""
        artist, title = extract_metadata_from_filename("Artist - Song feat. Guest.wav")
        self.assertEqual(artist, "Artist")
        self.assertEqual(title, "Song feat. Guest")


class TestHandleExtraction(unittest.TestCase):
    """Tests for SoundCloud handle extraction from filenames."""

    def test_simple_handle(self):
        """Basic handle extraction."""
        handles = extract_handles("Track [username].wav")
        self.assertEqual(handles, ["username"])

    def test_multiple_handles(self):
        """Multiple handles in one filename."""
        handles = extract_handles("Track [user1] [user2].wav")
        self.assertIn("user1", handles)
        self.assertIn("user2", handles)

    def test_handle_case_insensitive(self):
        """Handles should be case-insensitive."""
        handles = extract_handles("Track [UPPERCASE].wav")
        self.assertIn("uppercase", handles)

    def test_handle_with_underscore(self):
        """Handles with underscores."""
        handles = extract_handles("Track [dj_user_123].wav")
        self.assertIn("dj_user_123", handles)

    def test_handle_with_numbers(self):
        """Handles with numbers."""
        handles = extract_handles("Track [djhulk1].wav")
        self.assertIn("djhulk1", handles)

    def test_handle_too_short(self):
        """Handles under 3 chars are ignored."""
        handles = extract_handles("Track [ab].wav")
        self.assertNotIn("ab", handles)

    def test_no_handle(self):
        """No handle in filename."""
        handles = extract_handles("Artist - Title.wav")
        self.assertEqual(handles, [])

    def test_handle_in_different_positions(self):
        """Handle at start of filename."""
        handles = extract_handles("[gsfreedls] Track Name.wav")
        self.assertIn("gsfreedls", handles)

    def test_handle_with_dash(self):
        """Handle with dash - current regex excludes dashes."""
        handles = extract_handles("Track [user-name].wav")
        self.assertNotIn("user", handles)
        self.assertNotIn("user-name", handles)


class TestTitleCleanup(unittest.TestCase):
    """Tests for title cleanup before search."""

    def test_remove_remix(self):
        """Remove remix keyword."""
        result = clean_title_for_search("Track (Remix)")
        self.assertNotIn("remix", result.lower())

    def test_remove_edit(self):
        """Remove edit keyword."""
        result = clean_title_for_search("Song (Edit)")
        self.assertNotIn("edit", result.lower())

    def test_remove_feat(self):
        """Remove featuring."""
        result = clean_title_for_search("Song (feat. Guest)")
        self.assertNotIn("feat", result.lower())

    def test_nested_brackets(self):
        """Handle nested brackets."""
        result = clean_title_for_search("Track [(remix)]")
        self.assertNotIn("remix", result.lower())

    def test_multiple_keywords(self):
        """Remove multiple keywords."""
        result = clean_title_for_search("Song (Remix) (Edit)")
        self.assertNotIn("remix", result.lower())
        self.assertNotIn("edit", result.lower())

    def test_keep_clean_title(self):
        """Keep title without keywords."""
        result = clean_title_for_search("Clean Title")
        self.assertEqual(result, "Clean Title")

    def test_square_brackets(self):
        """Remove square bracket keywords."""
        result = clean_title_for_search("Track [Remix]")
        self.assertNotIn("remix", result.lower())

    def test_mixed_brackets(self):
        """Mixed round and square brackets."""
        result = clean_title_for_search("Song (Remix) [Radio Edit]")
        self.assertNotIn("remix", result.lower())
        self.assertNotIn("edit", result.lower())


class TestRegexConstants(unittest.TestCase):
    """Tests for regex patterns."""

    def test_og_image_pattern(self):
        """OG image URL extraction."""
        html = '<meta property="og:image" content="https://example.com/cover.jpg">'
        match = OG_IMAGE_RE.search(html)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "https://example.com/cover.jpg")

    def test_og_image_no_match(self):
        """OG image not found."""
        html = '<div>No image here</div>'
        match = OG_IMAGE_RE.search(html)
        self.assertIsNone(match)

    def test_bandcamp_track_url(self):
        """Bandcamp track URL extraction."""
        html = 'https://artist.bandcamp.com/track/song-name'
        match = BANDCAMP_URL_RE.search(html)
        self.assertIsNotNone(match)

    def test_bandcamp_album_url(self):
        """Bandcamp album URL extraction."""
        html = 'https://artist.bandcamp.com/album/album-name'
        match = BANDCAMP_URL_RE.search(html)
        self.assertIsNotNone(match)

    def test_bandcamp_no_match(self):
        """Non-bandcamp URL not matched."""
        html = 'https://example.com/music'
        match = BANDCAMP_URL_RE.search(html)
        self.assertIsNone(match)

    def test_soundcloud_artwork(self):
        """SoundCloud artwork URL extraction."""
        url = "https://i1.sndcdn.com/artworks-abc123-500x500.jpg"
        match = SNDCLOUD_ARTWORK_RE.search(url)
        self.assertIsNotNone(match)

    def test_soundcloud_artwork_png(self):
        """SoundCloud PNG artwork."""
        url = "https://i1.sndcdn.com/artworks-abc123-500x500.png"
        match = SNDCLOUD_ARTWORK_RE.search(url)
        self.assertIsNotNone(match)

    def test_handle_regex(self):
        """Handle extraction regex."""
        match = HANDLE_RE.search("Track [username].wav")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "username")

    def test_handle_regex_case_insensitive(self):
        """Handle regex is case insensitive - returns original case."""
        match = HANDLE_RE.search("Track [USERNAME].wav")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "USERNAME")


class TestCoverSearchLogic(unittest.TestCase):
    """Tests for cover search related functions."""

    def test_clean_title_for_deezer(self):
        """Title cleanup for Deezer search."""
        title = clean_title_for_search("My Song (Radio Edit)")
        self.assertEqual(title, "My Song")

    def test_handle_extraction_for_soundcloud(self):
        """Extract handle for SC search."""
        handles = extract_handles("My Song [gsfreedls].wav")
        self.assertIn("gsfreedls", handles)


class TestEdgeCases(unittest.TestCase):
    """Edge case handling."""

    def test_empty_filename(self):
        """Empty filename."""
        artist, title = extract_metadata_from_filename("")
        self.assertEqual(artist, "")
        self.assertEqual(title, "")

    def test_only_separator(self):
        """Just separator - current behavior returns dash as title."""
        artist, title = extract_metadata_from_filename(" - ")
        self.assertEqual(artist, "")
        self.assertEqual(title, "-")

    def test_special_characters(self):
        """Special characters in filename."""
        artist, title = extract_metadata_from_filename("Artist - Title (feat. Guest) [DJ Mix].wav")
        self.assertEqual(artist, "Artist")
        self.assertIn("feat", title.lower())

    def test_unicode_characters(self):
        """Unicode in filename."""
        artist, title = extract_metadata_from_filename("Kraftwerk - Ä.wav")
        self.assertEqual(artist, "Kraftwerk")
        self.assertIn("Ä", title)

    def test_clean_suffix(self):
        """Filename ends with 'Clean' after separator."""
        artist, title = extract_metadata_from_filename("Here Comes That Sound Again - Clean.wav")
        self.assertEqual(artist, "Here Comes That Sound Again")
        self.assertEqual(title, "Clean")

    def test_multiple_artists_with_comma(self):
        """Multiple artists separated by commas."""
        artist, title = extract_metadata_from_filename("Artist1, Artist2, Artist3 - Title.wav")
        self.assertEqual(artist, "Artist1, Artist2, Artist3")
        self.assertEqual(title, "Title")

    def test_track_number_in_title(self):
        """Track number in title after artist."""
        artist, title = extract_metadata_from_filename("Artist - Track Name - 1 - Extended Mix.wav")
        self.assertEqual(artist, "Artist")
        self.assertIn("Track Name", title)

    def test_handle_at_end_of_title(self):
        """Handle in brackets at end of title (not after artist)."""
        handles = extract_handles("The Martinez Brothers - Song EDIT [NPSM].wav")
        self.assertIn("npsm", handles)

    def test_quotation_marks_in_title(self):
        """Quotation marks in title."""
        artist, title = extract_metadata_from_filename('Artist - "Kilo" (Remix).wav')
        self.assertEqual(artist, "Artist")
        self.assertIn("Kilo", title)


if __name__ == '__main__':
    unittest.main(verbosity=2)

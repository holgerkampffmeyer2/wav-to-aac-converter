#!/usr/bin/env python3
"""Unit tests for convert.py using stdlib unittest."""

import unittest
import sys
import os
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from convert import (
    extract_metadata_from_filename,
    extract_handles,
    clean_title_for_search,
    find_local_cover,
    OG_IMAGE_RE,
    BANDCAMP_URL_RE,
    SNDCLOUD_ARTWORK_RE,
    HANDLE_RE,
    _lookup_itunes,
    _lookup_musicbrainz,
    lookup_online_metadata,
    run_cmd,
    convert_file,
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
        """Handle with dash - updated regex now includes dashes."""
        handles = extract_handles("Track [user-name].wav")
        self.assertNotIn("user", handles)
        self.assertIn("user-name", handles)


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


class TestLocalCoverSearch(unittest.TestCase):
    """Tests for local cover art search."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        for f in Path(self.test_dir).glob('*'):
            f.unlink()
        Path(self.test_dir).rmdir()

    def test_cover_png(self):
        """Find cover.png in same directory."""
        wav_path = Path(self.test_dir) / "song.wav"
        cover_path = Path(self.test_dir) / "cover.png"
        cover_path.touch()
        wav_path.touch()
        result = find_local_cover(str(wav_path))
        self.assertEqual(result, str(cover_path))

    def test_cover_jpg(self):
        """Find cover.jpg in same directory."""
        wav_path = Path(self.test_dir) / "song.wav"
        cover_path = Path(self.test_dir) / "cover.jpg"
        cover_path.touch()
        wav_path.touch()
        result = find_local_cover(str(wav_path))
        self.assertEqual(result, str(cover_path))

    def test_cover_jpeg(self):
        """Find cover.jpeg in same directory."""
        wav_path = Path(self.test_dir) / "song.wav"
        cover_path = Path(self.test_dir) / "cover.jpeg"
        cover_path.touch()
        wav_path.touch()
        result = find_local_cover(str(wav_path))
        self.assertEqual(result, str(cover_path))

    def test_basename_match_png(self):
        """Find cover matching WAV basename."""
        wav_path = Path(self.test_dir) / "Artist - Title.wav"
        cover_path = Path(self.test_dir) / "Artist - Title.png"
        cover_path.touch()
        wav_path.touch()
        result = find_local_cover(str(wav_path))
        self.assertEqual(result, str(cover_path))

    def test_basename_match_jpg(self):
        """Find cover matching WAV basename with jpg."""
        wav_path = Path(self.test_dir) / "MySong.wav"
        cover_path = Path(self.test_dir) / "MySong.jpg"
        cover_path.touch()
        wav_path.touch()
        result = find_local_cover(str(wav_path))
        self.assertEqual(result, str(cover_path))

    def test_any_image_in_folder(self):
        """Find any image file when no specific cover found."""
        wav_path = Path(self.test_dir) / "song.wav"
        any_image = Path(self.test_dir) / "any_image.png"
        any_image.touch()
        wav_path.touch()
        result = find_local_cover(str(wav_path))
        self.assertEqual(result, str(any_image))

    def test_no_cover_found(self):
        """Return None when no cover exists."""
        wav_path = Path(self.test_dir) / "song.wav"
        wav_path.touch()
        result = find_local_cover(str(wav_path))
        self.assertIsNone(result)


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

    def test_dirty_suffix(self):
        """Filename ends with 'Dirty' after separator."""
        artist, title = extract_metadata_from_filename("Track Name - Dirty.wav")
        self.assertEqual(artist, "Track Name")
        self.assertEqual(title, "Dirty")

    def test_radio_suffix(self):
        """Filename ends with 'Radio' after separator."""
        artist, title = extract_metadata_from_filename("Song - Radio Edit.wav")
        self.assertEqual(artist, "Song")
        self.assertEqual(title, "Radio Edit")

    def test_master_suffix(self):
        """Filename ends with 'Master' after separator."""
        artist, title = extract_metadata_from_filename("Track - Master.wav")
        self.assertEqual(artist, "Track")
        self.assertEqual(title, "Master")

    def test_extended_suffix(self):
        """Filename ends with 'Extended' after separator."""
        artist, title = extract_metadata_from_filename("Track - Extended Mix.wav")
        self.assertEqual(artist, "Track")
        self.assertEqual(title, "Extended Mix")

    def test_various_clean_suffixes(self):
        """Various clean/dirty/radio/master suffixes after separator."""
        cases = [
            ("Track - Clean", "Track", "Clean"),
            ("Track - Dirty", "Track", "Dirty"),
            ("Track - Radio Edit", "Track", "Radio Edit"),
            ("Track - Mastered", "Track", "Mastered"),
            ("Track - Extended", "Track", "Extended"),
            ("Track - Short Version", "Track", "Short Version"),
        ]
        for filename, expected_artist, expected_title in cases:
            artist, title = extract_metadata_from_filename(filename)
            self.assertEqual(artist, expected_artist, f"Failed for: {filename}")
            self.assertEqual(title, expected_title, f"Failed for: {filename}")

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


class TestOnlineMetadataLookup(unittest.TestCase):
    """Tests for online metadata lookup via iTunes and MusicBrainz."""

    @patch('convert.fetch_url')
    def test_lookup_itunes_success(self, mock_fetch):
        """iTunes returns a valid track."""
        mock_fetch.return_value = json.dumps({
            "resultCount": 1,
            "results": [{
                "trackName": "Test Song",
                "artistName": "Test Artist"
            }]
        })
        artist, title = _lookup_itunes("Test Song")
        self.assertEqual(artist, "Test Artist")
        self.assertEqual(title, "Test Song")

    @patch('convert.fetch_url')
    def test_lookup_itunes_no_results(self, mock_fetch):
        """iTunes returns no results."""
        mock_fetch.return_value = json.dumps({"resultCount": 0})
        artist, title = _lookup_itunes("Unknown Song")
        self.assertIsNone(artist)
        self.assertIsNone(title)

    @patch('convert.fetch_url')
    def test_lookup_musicbrainz_success(self, mock_fetch):
        """MusicBrainz returns a valid recording."""
        mock_fetch.return_value = json.dumps({
            "recordings": [{
                "title": "Test Song",
                "artist-credit": [{"artist": {"name": "Test Artist"}}]
            }]
        })
        artist, title = _lookup_musicbrainz("Test Song")
        self.assertEqual(artist, "Test Artist")
        self.assertEqual(title, "Test Song")

    @patch('convert.fetch_url')
    def test_lookup_musicbrainz_no_results(self, mock_fetch):
        """MusicBrainz returns no results."""
        mock_fetch.return_value = json.dumps({"recordings": []})
        artist, title = _lookup_musicbrainz("Unknown Song")
        self.assertIsNone(artist)
        self.assertIsNone(title)

    @patch('convert.fetch_url')
    def test_lookup_online_metadata_itunes_first(self, mock_fetch):
        """lookup_online_metadata tries iTunes first."""
        # iTunes returns a result
        mock_fetch.return_value = json.dumps({
            "resultCount": 1,
            "results": [{
                "trackName": "iTunes Song",
                "artistName": "iTunes Artist"
            }]
        })
        artist, title = lookup_online_metadata("iTunes Song")
        self.assertEqual(artist, "iTunes Artist")
        self.assertEqual(title, "iTunes Song")

    @patch('convert.fetch_url')
    def test_lookup_online_metadata_fallback_to_musicbrainz(self, mock_fetch):
        """If iTunes fails, fallback to MusicBrainz."""
        # First call (iTunes) returns no results, second call (MusicBrainz) returns a result
        mock_fetch.side_effect = [
            json.dumps({"resultCount": 0}),  # iTunes
            json.dumps({  # MusicBrainz
                "recordings": [{
                    "title": "MB Song",
                    "artist-credit": [{"artist": {"name": "MB Artist"}}]
                }]
            })
        ]
        artist, title = lookup_online_metadata("MB Song")
        self.assertEqual(artist, "MB Artist")
        self.assertEqual(title, "MB Song")

    @patch('convert.fetch_url')
    def test_lookup_online_metadata_both_fail(self, mock_fetch):
        """Both iTunes and MusicBrainz fail."""
        mock_fetch.return_value = json.dumps({"resultCount": 0})
        artist, title = lookup_online_metadata("Unknown Song")
        self.assertIsNone(artist)
        self.assertIsNone(title)


class TestIntegration(unittest.TestCase):
    """Integration tests for the conversion process."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.wav_path = os.path.join(self.test_dir, "test.wav")
        # Create a silent WAV file (1 second, 44100 Hz, 16-bit mono)
        import struct
        sample_rate = 44100
        duration = 1  # second
        num_samples = sample_rate * duration
        bytes_per_sample = 2  # 16-bit
        num_channels = 1
        byte_rate = sample_rate * num_channels * bytes_per_sample
        block_align = num_channels * bytes_per_sample
        data_size = num_samples * num_channels * bytes_per_sample
        chunk_size = 36 + data_size

        with open(self.wav_path, 'wb') as f:
            f.write(b'RIFF')  # ChunkID
            f.write(struct.pack('<I', chunk_size))  # ChunkSize
            f.write(b'WAVE')  # Format
            f.write(b'fmt ')  # Subchunk1ID
            f.write(struct.pack('<I', 16))  # Subchunk1Size (16 for PCM)
            f.write(struct.pack('<H', 1))   # AudioFormat (1 for PCM)
            f.write(struct.pack('<H', num_channels))  # NumChannels
            f.write(struct.pack('<I', sample_rate))  # SampleRate
            f.write(struct.pack('<I', byte_rate))  # ByteRate
            f.write(struct.pack('<H', block_align))  # BlockAlign
            f.write(struct.pack('<H', bytes_per_sample * 8))  # BitsPerSample
            f.write(b'data')  # Subchunk2ID
            f.write(struct.pack('<I', data_size))  # Subchunk2Size
            # Write silent data (all zeros)
            f.write(b'\x00' * data_size)

    def tearDown(self):
        # Clean up the temporary directory
        import shutil
        shutil.rmtree(self.test_dir)

    @patch('convert.fetch_url')
    @patch('convert.analyze_loudness')
    def test_integration_conversion_with_mocked_online(self, mock_loudness, mock_fetch):
        # Mock loudness analysis to return a fixed dict
        mock_loudness.return_value = {
            'input_i': -16.0,
            'input_tp': -1.0,
            'input_lra': 8.0,
            'input_thresh': -24.0
        }

        # Mock fetch_url for online metadata lookup (iTunes) to return a known track
        mock_fetch.return_value = json.dumps({
            "resultCount": 1,
            "results": [{
                "trackName": "Test Song",
                "artistName": "Test Artist",
                "collectionName": "Test Album"
            }]
        })

        # We also need to mock the cover art search to avoid network calls and return None (no cover)
        # We can do this by patching the specific cover search functions.
        with patch('convert.search_deezer_cover', return_value=None), \
             patch('convert.search_bandcamp_cover', return_value=None), \
             patch('convert.search_soundcloud_web', return_value=(None, None)):

            # Run the conversion
            success, output_file = convert_file(self.wav_path, fmt='mp3')

            # Check that the conversion succeeded
            self.assertTrue(success, "Conversion should succeed")
            self.assertIsNotNone(output_file, "Output file should be returned")
            self.assertTrue(os.path.exists(output_file), "Output file should exist")

            # Check the output file's metadata using ffprobe
            cmd = f'ffprobe -v quiet -print_format json -show_format -show_streams "{output_file}"'
            success_cmd, stdout, _ = run_cmd(cmd)
            self.assertTrue(success_cmd, "ffprobe should succeed")
            data = json.loads(stdout)
            tags = data.get('format', {}).get('tags', {})
            self.assertEqual(tags.get('artist'), 'Test Artist')
            self.assertEqual(tags.get('title'), 'Test Song')

    @patch('convert.fetch_url')
    @patch('convert.analyze_loudness')
    def test_integration_conversion_m4a_with_mocked_online(self, mock_loudness, mock_fetch):
        mock_loudness.return_value = {
            'input_i': -16.0,
            'input_tp': -1.0,
            'input_lra': 8.0,
            'input_thresh': -24.0
        }
        mock_fetch.return_value = json.dumps({
            "resultCount": 1,
            "results": [{
                "trackName": "Test Song M4A",
                "artistName": "Test Artist M4A",
                "collectionName": "Test Album"
            }]
        })

        with patch('convert.search_deezer_cover', return_value=None), \
             patch('convert.search_bandcamp_cover', return_value=None), \
             patch('convert.search_soundcloud_web', return_value=(None, None)):

            success, output_file = convert_file(self.wav_path, fmt='m4a')
            self.assertTrue(success)
            self.assertIsNotNone(output_file)
            self.assertTrue(os.path.exists(output_file))

            cmd = f'ffprobe -v quiet -print_format json -show_format -show_streams "{output_file}"'
            success_cmd, stdout, _ = run_cmd(cmd)
            self.assertTrue(success_cmd)
            data = json.loads(stdout)
            tags = data.get('format', {}).get('tags', {})
            self.assertEqual(tags.get('artist'), 'Test Artist M4A')
            self.assertEqual(tags.get('title'), 'Test Song M4A')


if __name__ == '__main__':
    unittest.main(verbosity=2)

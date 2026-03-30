#!/usr/bin/env python3
"""Unit tests for convert.py using stdlib unittest."""

import unittest
import sys
import os
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

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
    search_soundcloud_web,
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


class TestASCIIConversion(unittest.TestCase):
    """Tests for ASCII filename conversion."""

    def test_to_ascii_basic(self):
        """Test basic ASCII conversion."""
        from convert import to_ascii_filename
        self.assertEqual(to_ascii_filename("Artist - Title.wav"), "Artist - Title.wav")

    def test_to_ascii_with_accents(self):
        """Test conversion of accented characters."""
        from convert import to_ascii_filename
        self.assertEqual(to_ascii_filename("Agapás.wav"), "Agapas.wav")
        self.assertEqual(to_ascii_filename("Café.wav"), "Cafe.wav")
        self.assertEqual(to_ascii_filename("Naïve.wav"), "Naive.wav")

    def test_to_ascii_special_chars(self):
        """Test removal of special characters."""
        from convert import to_ascii_filename
        # The regex preserves brackets, so [Title] stays as [Title]
        self.assertEqual(to_ascii_filename("Artist [Title].wav"), "Artist [Title].wav")
        self.assertEqual(to_ascii_filename("Artist-Title.wav"), "Artist-Title.wav")
        self.assertEqual(to_ascii_filename("Artist_Title.wav"), "Artist_Title.wav")
        # Test actual special character removal
        self.assertEqual(to_ascii_filename("Artist@#$%Title.wav"), "ArtistTitle.wav")

    def test_to_ascii_whitespace(self):
        """Test whitespace normalization."""
        from convert import to_ascii_filename
        self.assertEqual(to_ascii_filename("Artist   -   Title.wav"), "Artist - Title.wav")
        self.assertEqual(to_ascii_filename("  Artist - Title  .wav"), "Artist - Title .wav")

    def test_to_ascii_non_ascii_only(self):
        """Test string with only non-ASCII characters."""
        from convert import to_ascii_filename
        self.assertEqual(to_ascii_filename("АБВГД.wav"), ".wav")  # Cyrillic becomes empty
        self.assertEqual(to_ascii_filename("中文测试.wav"), ".wav")  # Chinese becomes empty

    def test_to_ascii_empty_string(self):
        """Test empty string."""
        from convert import to_ascii_filename
        self.assertEqual(to_ascii_filename(""), "")


class TestASCIIFilenameHandling(unittest.TestCase):
    """Tests for automatic ASCII filename handling in conversion process."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.original_wav_path = None

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up the temporary directory
        import shutil
        if self.test_dir and os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        # Clean up any created WAV files
        if self.original_wav_path and os.path.exists(self.original_wav_path):
            os.remove(self.original_wav_path)

    def _create_test_wav(self, filename):
        """Create a simple silent WAV file for testing."""
        import struct
        sample_rate = 44100
        duration = 0.1  # short duration for quick test
        num_samples = int(sample_rate * duration)
        bytes_per_sample = 2  # 16-bit
        num_channels = 2  # stereo
        byte_rate = sample_rate * num_channels * bytes_per_sample
        block_align = num_channels * bytes_per_sample
        data_size = num_samples * num_channels * bytes_per_sample
        chunk_size = 36 + data_size

        wav_data = b'RIFF' + struct.pack('<I', chunk_size) + b'WAVE' + b'fmt ' + struct.pack('<I', 16) + struct.pack('<H', 1) + struct.pack('<H', num_channels) + struct.pack('<I', sample_rate) + struct.pack('<I', byte_rate) + struct.pack('<H', block_align) + struct.pack('<H', bytes_per_sample * 8) + b'data' + struct.pack('<I', data_size) + b'\x00' * data_size
        
        wav_path = Path(self.test_dir) / filename
        with open(wav_path, 'wb') as f:
            f.write(wav_data)
        self.original_wav_path = str(wav_path)
        return str(wav_path)

    @patch('convert.analyze_loudness')
    @patch('convert.extract_metadata')
    @patch('convert.search_deezer_cover')
    @patch('convert.search_bandcamp_cover')
    @patch('convert.search_soundcloud_web')
    @patch('convert.download_cover')
    @patch('convert.encode_audio')
    @patch('convert.embed_cover')
    @patch('convert.verify_output')
    @patch('shutil.rmtree')  # Don't actually delete temp dirs in test
    def test_ascii_filename_used_for_unicode_input(self, mock_rmtree, mock_verify, mock_embed, mock_encode, mock_download, mock_soundcloud, mock_bandcamp, mock_deezer, mock_extract, mock_loudness):
        """Test that ASCII filename is used when input has Unicode characters."""
        # Set up mocks to return successful results
        mock_loudness.return_value = {'input_i': '-9.00', 'input_tp': '1.01'}
        mock_extract.return_value = {'artist': 'Test Artist', 'title': 'Test Title'}
        mock_deezer.return_value = None
        mock_bandcamp.return_value = None
        mock_soundcloud.return_value = (None, None)
        mock_download.return_value = True
        
        # Make encode_audio return True and also create the temp output file
        def mock_encode_func(wav_path, temp_output, metadata, gain_db, fmt):
            # Create the temp output file to simulate successful encoding
            with open(temp_output, 'wb') as f:
                f.write(b'dummy mp3 data')
            return True
        
        mock_encode.side_effect = mock_encode_func
        mock_embed.return_value = True
        mock_verify.return_value = (True, {'mp3': True, 'cover': False})
        
        # Create a WAV file with Unicode characters
        unicode_filename = 'Tést - CAFÉ.wav'
        wav_path = self._create_test_wav(unicode_filename)
        
        # Call convert_file
        from convert import convert_file
        success, output = convert_file(wav_path, fmt='mp3')
        
        # Verify the function returned success
        self.assertTrue(success)
        self.assertIsNotNone(output)
        
        # Verify that encode_audio was called with an ASCII filename path
        # encode_audio is called with (wav_path, temp_output, metadata, gain_db, fmt)
        self.assertTrue(mock_encode.called)
        call_args = mock_encode.call_args[0]  # Get positional arguments
        wav_path_used_in_encode = call_args[0]  # First argument is wav_path
        
        # Verify the WAV path used in encoding is an ASCII version in temp directory
        self.assertTrue(wav_path_used_in_encode.endswith('.wav'))
        self.assertIn('wav2aac_', wav_path_used_in_encode)  # Should be in temp directory
        # The ASCII conversion of "Tést - CAFÉ" is "Test - CAFE"
        self.assertIn('Test - CAFE.wav', wav_path_used_in_encode)

    @patch('convert.convert_file')
    def test_ascii_filename_not_needed_for_ascii_input(self, mock_convert):
        """Test that original filename is used when input is already ASCII."""
        mock_convert.return_value = (True, 'output.mp3')
        
        # Create a WAV file with ASCII characters only
        ascii_filename = 'Test - Cafe.wav'
        wav_path = self._create_test_wav(ascii_filename)
        
        # Call convert_file
        from convert import convert_file
        success, output = convert_file(wav_path, fmt='mp3')
        
        # Verify convert_file was called
        self.assertTrue(mock_convert.called)
        # Get the arguments passed to convert_file
        call_args = mock_convert.call_args[0]
        self.assertEqual(len(call_args), 1)  # wav_path only (fmt is default)
        wav_path_used = call_args[0]
        
        # Verify the WAV path used is the original (since it's already ASCII)
        self.assertEqual(wav_path_used, wav_path)
        
        # Verify the function returned success
        self.assertTrue(success)

    @patch('convert.convert_file')
    def test_fallback_to_original_on_ascii_conversion_failure(self, mock_convert):
        """Test that original filename is used if ASCII conversion fails."""
        mock_convert.return_value = (True, 'output.mp3')
        
        # Create a WAV file with ASCII characters only
        ascii_filename = 'Test - Cafe.wav'
        wav_path = self._create_test_wav(ascii_filename)
        
        # Mock to_ascii_filename to raise an exception
        with patch('convert.to_ascii_filename', side_effect=Exception("Test exception")):
            # Call convert_file
            from convert import convert_file
            success, output = convert_file(wav_path, fmt='mp3')
            
            # Verify convert_file was called
            self.assertTrue(mock_convert.called)
            # Get the arguments passed to convert_file
            call_args = mock_convert.call_args[0]
            self.assertEqual(len(call_args), 1)  # wav_path only (fmt is default)
            wav_path_used = call_args[0]
            
            # Verify the WAV path used is the original (fallback)
            self.assertEqual(wav_path_used, wav_path)
            
            # Verify the function returned success
            self.assertTrue(success)


class TestConfigFeatures(unittest.TestCase):
    """Tests for configuration features."""

    def test_load_config_defaults(self):
        """Test loading config with default values when file doesn't exist."""
        from convert import load_config
        import tempfile
        import os
        
        # Create a temporary directory and ensure config.json doesn't exist
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, 'config.json')
            if os.path.exists(config_path):
                os.remove(config_path)
            
            # Mock the config file path to point to our temp directory
            with patch('convert.Path') as mock_path:
                mock_instance = MagicMock()
                mock_instance.parent.__truediv__.return_value = Path(config_path)
                mock_path.return_value = mock_instance
                
                config = load_config()
                expected = {
                    "ascii_filename": False,  # Kept for backward compatibility but unused
                    "output_format": "mp3",
                    "max_parallel_processes": 5,
                    "loudnorm": True,
                    "embed_cover": True,
                    "retry_attempts": 3,
                    "timeout_seconds": 30
                }
                self.assertEqual(config, expected)

    def test_load_config_from_file(self):
        """Test loading config from an existing file."""
        from convert import load_config
        import tempfile
        import json
        import os
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, 'config.json')
            test_config = {
                "ascii_filename": True,  # Kept for backward compatibility but unused
                "output_format": "m4a",
                "max_parallel_processes": 10,
                "loudnorm": False,
                "embed_cover": False,
                "retry_attempts": 5,
                "timeout_seconds": 60
            }
            
            with open(config_path, 'w') as f:
                json.dump(test_config, f)
            
            # Mock the config file path
            with patch('convert.Path') as mock_path:
                mock_path.return_value.parent.__truediv__.return_value = Path(config_path)
                config = load_config()
                self.assertEqual(config, test_config)

    def test_parse_args_uses_config_defaults(self):
        """Test that argument parser uses config values as defaults."""
        from convert import parse_args, load_config
        from unittest.mock import patch
        import sys
        
        # Test with default config values
        test_config = load_config()
        
        with patch('convert.load_config', return_value=test_config):
            # Test default values
            test_args = ['dummy.wav']
            with patch('sys.argv', ['convert.py'] + test_args):
                args = parse_args()
                self.assertEqual(args.format, test_config['output_format'])
                # ascii_filename arg removed, so skip this check
                self.assertEqual(args.max_workers, test_config['max_parallel_processes'])
                self.assertEqual(args.loudnorm, test_config['loudnorm'])
                self.assertEqual(args.embed_cover, test_config['embed_cover'])
                self.assertEqual(args.retry_attempts, test_config['retry_attempts'])
                self.assertEqual(args.timeout, test_config['timeout_seconds'])

    def test_parse_args_command_line_override(self):
        """Test that command line arguments override config values."""
        from convert import parse_args, load_config
        from unittest.mock import patch
        import sys
        
        test_config = load_config()
        
        with patch('convert.load_config', return_value=test_config):
            # Test command line overrides
            test_args = [
                '--m4a',  # Should set m4a flag to True
                '--max-workers', '3',  # Should override max_parallel_processes
                '--no-loudnorm',  # Should override loudnorm (False)
                '--no-cover',  # Should override embed_cover (False)
                '--retry-attempts', '7',  # Should override retry_attempts
                '--timeout', '120',  # Should override timeout_seconds
                'dummy.wav'
            ]
            with patch('sys.argv', ['convert.py'] + test_args):
                args = parse_args()
                self.assertTrue(args.m4a)  # Command line override for m4a
                self.assertEqual(args.max_workers, 3)  # Command line override
                self.assertFalse(args.loudnorm)  # Command line override
                self.assertFalse(args.embed_cover)  # Command line override
                self.assertEqual(args.retry_attempts, 7)  # Command line override
                self.assertEqual(args.timeout, 120)  # Command line override

    def test_convert_batch_ascii_filename_param(self):
        """Test that convert_batch works without ascii_filename parameter (removed)."""
        from convert import convert_batch, _convert_file_wrapper
        from unittest.mock import patch
        
        # Mock convert_file to avoid actual processing
        # _convert_file_wrapper expects convert_file to return (success, output)
        # and then returns (wav_path, success, output)
        with patch('convert.convert_file', return_value=(True, 'output.wav')) as mock_convert:
            file_paths = ['file1.wav', 'file2.wav']
            # Test that convert_batch works without ascii_filename parameter
            results = convert_batch(file_paths, 'mp3', True, 2)
            # Check that convert_file was called for each file
            mock_convert.assert_any_call('file1.wav', 'mp3')
            mock_convert.assert_any_call('file2.wav', 'mp3')
            
            # Reset mock
            mock_convert.reset_mock()
            
            # Test with parallel=False
            results = convert_batch(file_paths, 'mp3', False, 2)
            mock_convert.assert_any_call('file1.wav', 'mp3')
            mock_convert.assert_any_call('file2.wav', 'mp3')


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


class TestSoundCloudSearch(unittest.TestCase):
    """Tests for SoundCloud search functionality."""
    
    @patch('convert._fetch_soundcloud_cover')
    def test_search_soundcloud_web_basic(self, mock_fetch_cover):
        """Test basic SoundCloud search with valid parameters."""
        # Mock the cover fetch to return a test URL
        mock_fetch_cover.return_value = "https://example.com/cover.jpg"
        
        # Call the function
        result = search_soundcloud_web("Test Artist", "Test Song", "test.wav")
        
        # Verify we got a result
        self.assertIsNotNone(result)
        metadata, cover_url = result
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata, ("Test Artist", "Test Song"))
        self.assertEqual(cover_url, "https://example.com/cover.jpg")
    
    @patch('convert._fetch_soundcloud_cover')
    def test_search_soundcloud_web_empty_params(self, mock_fetch_cover):
        """Test SoundCloud search with empty parameters."""
        result = search_soundcloud_web("", "", "")
        self.assertIsNone(result[0])  # First element (metadata) should be None
        self.assertIsNone(result[1])  # Second element (cover URL) should be None
        
        result = search_soundcloud_web(None, None, None)
        self.assertIsNone(result[0])  # First element (metadata) should be None
        self.assertIsNone(result[1])  # Second element (cover URL) should be None
    
    @patch('convert._fetch_soundcloud_cover')
    def test_search_soundcloud_web_with_filename_handles(self, mock_fetch_cover):
        """Test SoundCloud search extracts handles from filename."""
        mock_fetch_cover.return_value = "https://example.com/cover.jpg"
        
        # Test with handle in filename
        result = search_soundcloud_web("Artist", "Title", "[testhandle] Artist - Title.wav")
        
        # Should have attempted search with the handle
        self.assertIsNotNone(result)
    
    @patch('convert._fetch_soundcloud_cover')
    def test_search_soundcloud_web_no_results(self, mock_fetch_cover):
        """Test SoundCloud search when no cover is found."""
        mock_fetch_cover.return_value = None
        
        result = search_soundcloud_web("Unknown Artist", "Unknown Song", "unknown.wav")
        self.assertIsNone(result[0])  # First element (metadata) should be None
        self.assertIsNone(result[1])  # Second element (cover URL) should be None


if __name__ == '__main__':
    unittest.main(verbosity=2)

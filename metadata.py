#!/usr/bin/env python3
"""Metadata extraction and online lookup functions for wav-to-aac-converter."""

import json
import logging
from typing import Optional, Tuple, Dict, Any

from utils import (
    ITUNES_SEARCH_URL,
    MUSICBRAINZ_LOOKUP_URL,
    run_cmd as util_run_cmd,
    to_ascii_filename
)

logger = logging.getLogger(__name__)


def run_cmd(cmd: str, capture_output: bool = True, timeout: int = 600):
    """Run shell command and return output."""
    return util_run_cmd(cmd, capture_output, timeout)


def extract_metadata(wav_path: str) -> Dict[str, Any]:
    """Extract metadata from WAV file using ffprobe."""
    cmd = f'ffprobe -v quiet -print_format json -show_format -show_streams "{wav_path}"'
    success, stdout, stderr = run_cmd(cmd)
    
    if not success:
        return {}
    
    try:
        data = json.loads(stdout)
        format_data = data.get('format', {})
        tags = format_data.get('tags', {})
        
        return {
            'artist': tags.get('artist', ''),
            'title': tags.get('title', ''),
            'album': tags.get('album', ''),
            'date': tags.get('date', ''),
            'genre': tags.get('genre', ''),
            'duration': float(format_data.get('duration', 0))
        }
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Metadata extraction error: {e}")
        return {}


def _lookup_itunes(term: str):
    """Lookup track on iTunes Search API."""
    if not term:
        return None, None
    
    from utils import fetch_url
    from urllib.parse import quote
    
    term_quoted = quote(term)
    url = f"{ITUNES_SEARCH_URL}{term_quoted}&entity=song&limit=5"
    content = fetch_url(url)
    if not content:
        return None, None
    try:
        data = json.loads(content)
        for track in data.get("results", []):
            track_name = track.get("trackName", "")
            if track_name.lower() == term.lower():
                artist = track.get("artistName")
                return artist, track_name
        # If no exact match, try to find a match containing the search term
        term_lower = term.lower()
        for track in data.get("results", []):
            track_name = track.get("trackName", "").lower()
            if term_lower in track_name or track_name in term_lower:
                artist = track.get("artistName")
                return artist, track.get("trackName")
        # If still no match, take the first result that has both artist and track name
        if data.get("resultCount", 0):
            track = data["results"][0]
            artist = track.get("artistName")
            track_name = track.get("trackName")
            if artist and track_name:
                return artist, track_name
    except (json.JSONDecodeError, KeyError):
        pass
    return None, None


def _lookup_musicbrainz(term: str):
    """Lookup track on MusicBrainz API."""
    if not term:
        return None, None
    
    from utils import fetch_url
    from urllib.parse import quote
    
    term_quoted = quote(term)
    url = f"{MUSICBRAINZ_LOOKUP_URL}recording={term_quoted}&fmt=json&limit=5"
    content = fetch_url(url)
    if not content:
        return None, None
    
    try:
        data = json.loads(content)
        recordings = data.get('recordings', [])
        if recordings:
            recording = recordings[0]
            # Try to get artist from releases
            releases = recording.get('releases', [])
            if releases:
                artist_credit = releases[0].get('artist-credit', [])
                for ac in artist_credit:
                    if ac.get('name'):
                        artist = ac['name']
                        break
                    elif ac.get('artist', {}).get('name'):
                        artist = ac['artist']['name']
                        break
                else:
                    artist = ''
            else:
                artist = ''
            title = recording.get('title', '')
            if artist and title:
                return artist, title
    except (json.JSONDecodeError, KeyError):
        pass
    return None, None


def lookup_online_metadata(base_name: str):
    """Look up metadata online using iTunes and MusicBrainz."""
    # Try iTunes first
    artist, title = _lookup_itunes(base_name)
    if artist and title:
        return artist, title
    
    # Fallback to MusicBrainz
    return _lookup_musicbrainz(base_name)


def extract_metadata_from_filename(filename: str) -> Tuple[str, str]:
    """Extract artist and title from filename."""
    import re
    
    # Remove .wav extension
    name = filename
    for ext in ['.wav', '.WAV', '.mp3', '.m4a']:
        if name.lower().endswith(ext):
            name = name[:-len(ext)]
            break
    
    # Check for "Artist - Title" format
    if ' - ' in name:
        parts = name.split(' - ', 1)
        artist = parts[0].strip()
        title = parts[1].strip()
        
        return artist, title
    
    # Fallback: just use the whole name as title
    return '', name.strip()


def _is_valid_artist_handle(potential_artist: str, descriptive_terms: set) -> bool:
    """Check if potential artist looks valid (not just descriptive text)."""
    # Reject if it's all descriptive terms
    words = potential_artist.lower().split()
    if words and all(w in descriptive_terms for w in words):
        return False
    # Reject if too short
    if len(potential_artist) < 2:
        return False
    return True


def _parse_separators(name: str, descriptive_terms: set) -> Tuple[Optional[str], Optional[str]]:
    """Try to split name by various separators."""
    # Try various separators
    for sep in [' - ', '-', '|', '/', '::']:
        if sep in name:
            parts = name.split(sep, 1)
            artist = parts[0].strip()
            title = parts[1].strip()
            if _is_valid_artist_handle(artist, descriptive_terms):
                return artist, title
    return None, None


def _looks_like_track_number(text: str) -> bool:
    """Check if text looks like a track number."""
    return bool(re.match(r'^\d{1,3}\.?[\s\-]?', text.strip()))


def _is_valid_filename_part(text: str, descriptive_terms: set) -> bool:
    """Check if a filename part looks like valid content."""
    text_lower = text.lower()
    # Skip if it's just descriptive terms
    if text_lower in descriptive_terms:
        return False
    # Skip track numbers
    if _looks_like_track_number(text):
        return False
    # Skip if too short
    if len(text.strip()) < 2:
        return False
    return True
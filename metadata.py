#!/usr/bin/env python3
"""Metadata extraction and online lookup functions for wav-to-aac-converter."""

import json
import logging
from typing import Optional, Tuple, Dict, Any
from difflib import SequenceMatcher

from utils import (
    ITUNES_SEARCH_URL,
    MUSICBRAINZ_LOOKUP_URL,
    run_cmd as util_run_cmd,
    to_ascii_filename,
    load_config
)

logger = logging.getLogger(__name__)


def run_cmd(cmd: str, capture_output: bool = True, timeout: int = 600):
    """Run shell command and return output."""
    return util_run_cmd(cmd, capture_output, timeout)


def _fuzzy_match(search_term: str, candidate: str, threshold: float = 0.8) -> bool:
    """Check if search_term matches candidate with fuzzy matching.
    
    Args:
        search_term: Term to search for
        candidate: Candidate string to match against
        threshold: Minimum similarity score (0-1)
        
    Returns:
        True if match found above threshold
    """
    if not search_term or not candidate:
        return False
    
    search_lower = search_term.lower().strip()
    candidate_lower = candidate.lower().strip()
    
    # Exact match
    if search_lower == candidate_lower:
        return True
    
    # Partial match (one contains the other)
    if search_lower in candidate_lower or candidate_lower in search_lower:
        return True
    
    # Fuzzy match using SequenceMatcher
    score = SequenceMatcher(None, search_lower, candidate_lower).ratio()
    return score >= threshold


def _find_best_match(search_terms: list, candidates: list, threshold: float = 0.8) -> Optional[tuple]:
    """Find best match between search terms and candidates using fuzzy matching.
    
    Args:
        search_terms: List of terms to search for
        candidates: List of candidate strings
        threshold: Minimum similarity score
        
    Returns:
        Tuple of (best_candidate, best_score) or None
    """
    best_match = None
    best_score = 0.0
    
    for term in search_terms:
        for candidate in candidates:
            score = SequenceMatcher(None, term.lower().strip(), candidate.lower().strip()).ratio()
            if score > best_score:
                best_score = score
                best_match = candidate
                if score == 1.0:  # Exact match, stop early
                    return best_match, score
    
    if best_score >= threshold:
        return best_match, best_score
    return None


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
    """Lookup track on iTunes Search API with fuzzy matching."""
    if not term:
        return None, None
    
    config = load_config()
    threshold = config.get('fuzzy_threshold', 0.8)
    
    from utils import fetch_url
    from urllib.parse import quote
    
    term_quoted = quote(term)
    url = f"{ITUNES_SEARCH_URL}{term_quoted}&entity=song&limit=10"
    content = fetch_url(url)
    if not content:
        return None, None
    try:
        data = json.loads(content)
        
        # First try exact match
        for track in data.get("results", []):
            track_name = track.get("trackName", "")
            if track_name.lower() == term.lower():
                artist = track.get("artistName")
                return artist, track_name
        
        # Try fuzzy matching against all track names
        results = data.get("results", [])
        if results:
            # Create list of track names for matching
            track_names = [t.get("trackName", "") for t in results if t.get("trackName")]
            match = _find_best_match([term], track_names, threshold)
            if match:
                matched_track_name, score = match
                # Find the full track info
                for track in results:
                    if track.get("trackName") == matched_track_name:
                        return track.get("artistName"), matched_track_name
            
            # Fallback: take first result with both artist and track
            for track in results:
                artist = track.get("artistName")
                track_name = track.get("trackName")
                if artist and track_name:
                    # Check if fuzzy matches
                    if _fuzzy_match(term, track_name, threshold):
                        return artist, track_name
            
            # Last resort: first result
            track = results[0]
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


def _lookup_bandcamp(term: str):
    """Lookup track on Bandcamp via web search."""
    if not term:
        return None, None
    
    from utils import fetch_url, clean_title_for_search
    from urllib.parse import quote
    
    cleaned_term = clean_title_for_search(term)
    if not cleaned_term:
        cleaned_term = term
    
    search_url = f"https://bandcamp.com/search?q={quote(cleaned_term)}&search_type=title"
    content = fetch_url(search_url)
    if not content:
        return None, None
    
    try:
        from utils import BANDCAMP_URL_RE
        match = BANDCAMP_URL_RE.search(content)
        if match:
            bandcamp_url = match.group(0).split('"')[0].split('&')[0]
            page_content = fetch_url(bandcamp_url)
            if page_content:
                # Try to extract artist and title from page
                import re
                # Look for <title>Artist - Title | Bandcamp</title>
                title_match = re.search(r'<title>([^-|]+)\s*-\s*([^|<]+)', page_content, re.IGNORECASE)
                if title_match:
                    artist = title_match.group(1).strip()
                    title = title_match.group(2).strip()
                    if artist and title:
                        return artist, title
    except Exception:
        pass
    return None, None


def lookup_online_metadata(base_name: str):
    """Look up metadata online using multiple sources.
    
    Search order (like cover art):
    1. iTunes (primary - best for mainstream)
    2. Bandcamp (great for remixes, indie)
    3. MusicBrainz (fallback for obscure)
    """
    # Try iTunes first
    artist, title = _lookup_itunes(base_name)
    if artist and title:
        logger.debug(f"  iTunes found: {artist} - {title}")
        return artist, title
    
    # Fallback to Bandcamp
    artist, title = _lookup_bandcamp(base_name)
    if artist and title:
        logger.debug(f"  Bandcamp found: {artist} - {title}")
        return artist, title
    
    # Last resort: MusicBrainz
    artist, title = _lookup_musicbrainz(base_name)
    if artist and title:
        logger.debug(f"  MusicBrainz found: {artist} - {title}")
        return artist, title
    
    return None, None


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
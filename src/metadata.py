#!/usr/bin/env python3
"""Metadata extraction and online lookup functions for wav-to-aac-converter."""

import json
import logging
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from difflib import SequenceMatcher
from functools import lru_cache

from src.utils import (
    ITUNES_SEARCH_URL,
    MUSICBRAINZ_LOOKUP_URL,
    run_cmd as util_run_cmd,
    to_ascii_filename,
    load_config
)

logger = logging.getLogger(__name__)

# Alias for convenience
quote = urllib.parse.quote


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
    
    from .utils import fetch_url
    
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
    
    from .utils import fetch_url
    
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
    
    from .utils import fetch_url, clean_title_for_search
    
    cleaned_term = clean_title_for_search(term)
    if not cleaned_term:
        cleaned_term = term
    
    search_url = f"https://bandcamp.com/search?q={quote(cleaned_term)}&search_type=title"
    content = fetch_url(search_url)
    if not content:
        return None, None
    
    try:
        from .utils import BANDCAMP_URL_RE
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


def _lookup_deezer(term: str):
    """Lookup track on Deezer API."""
    if not term:
        return None, None
    
    from .utils import fetch_url
    
    try:
        query = quote(term)
        url = f"https://api.deezer.com/search/track?q={query}&limit=5"
        content = fetch_url(url, timeout=10)
        if not content:
            return None, None
        data = json.loads(content)
        if data.get('data') and len(data['data']) > 0:
            track = data['data'][0]
            artist = track.get('artist', {}).get('name', '')
            title = track.get('title', '')
            if artist and title:
                return artist, title
    except Exception:
        pass
    return None, None


def lookup_online_metadata(base_name: str):
    """Look up metadata online using multiple sources.
    
    Search order:
    1. iTunes (primary - best for mainstream)
    2. Deezer (good for European tracks)
    3. Bandcamp (great for remixes, indie)
    4. MusicBrainz (fallback for obscure)
    """
    # Try iTunes first
    artist, title = _lookup_itunes(base_name)
    if artist and title:
        logger.debug(f"  iTunes found: {artist} - {title}")
        return artist, title
    
    # Try Deezer
    artist, title = _lookup_deezer(base_name)
    if artist and title:
        logger.debug(f"  Deezer found: {artist} - {title}")
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


@lru_cache(maxsize=256)
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


_label_cache = {}
_genre_cache = {}
_additional_metadata_cache = {}


def _is_electronic_genre(genre: str) -> bool:
    """Check if a genre is likely electronic music."""
    if not genre:
        return False
    
    genre_lower = genre.lower().strip()
    
    electronic_keywords = {
        'electronic', 'techno', 'house', 'trance', 'drum and bass', 'drum n bass', 
        'drum & bass', 'jungle', 'dubstep', 'electronica', 'ambient', 'industrial',
        'edm', 'dance', 'garage', 'breakbeat', 'hardcore', 'hard house', 'progressive',
        'minimal', 'deep house', 'tech house', 'acid house', 'hard techno', 'hard trance',
        'gabber', 'happy hardcore', 'uk garage', '2step', 'breaks', 'electro', 'synthpop',
        'idm', 'intelligent dance music', 'chiptune', 'glitch', 'hardstyle', 'hardcore techno',
        'power noise', 'noisecore', 'dark ambient', 'vrtechno', 'hard dance', 
        'nu skool breaks', 'funky breaks', 'bassline', 'uk funky', 'future garage', 
        'post dubstep', 'future bass', 'trap', 'downtempo', 'chillout', 'lounge', 
        'nu jazz', 'electro swing', 'electroclash', 'new rave', 'bleep', 'bmore club', 
        'baltimore club', 'ghetto house', 'juke', 'footwork', 'seapunk', 'vaporwave', 
        'cloud rap', 'witch house', 'salem', 'drag'
    }
    
    for keyword in electronic_keywords:
        if keyword in genre_lower:
            return True
    
    return False


def _normalize_genre(genre: str) -> str:
    """Normalize genre to standard forms."""
    if not genre:
        return ""
    
    genre = genre.strip()
    
    normalizations = {
        'drum and bass': 'DRUM N BASS',
        'drum & bass': 'DRUM N BASS',
        'electronic dance music': 'EDM',
        'intelligent dance music': 'IDM',
        'uk garage': 'UKG',
    }
    
    genre_lower = genre.lower()
    for key, value in normalizations.items():
        if key in genre_lower:
            genre = genre.lower().replace(key, value)
    
    if genre.lower() == genre.strip().lower() and genre == genre.strip():
        applied_normalization = False
        for key in normalizations.keys():
            if key in genre_lower:
                applied_normalization = True
                break
        
        if not applied_normalization:
            return genre.title()
    
    return genre


def _get_genre_from_bandcamp(artist: str, title: str) -> Tuple[Optional[str], Optional[str]]:
    """Lookup genre and label via Bandcamp search."""
    from .utils import fetch_url
    
    cache_key = f"{artist.lower()}:{title.lower()}"
    if cache_key in _genre_cache:
        cached = _genre_cache[cache_key]
        if isinstance(cached, tuple) and len(cached) == 2:
            return cached
        return (None, None)
    
    result = (None, None)
    
    try:
        query = quote(f"{artist} {title}")
        search_url = f"https://bandcamp.com/search?q={query}&item_type=t"
        
        request = urllib.request.Request(
            search_url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        
        with urllib.request.urlopen(request, timeout=10) as response:
            html_content = response.read().decode('utf-8', errors='ignore')
            result = _parse_bandcamp_genre(html_content)
            
            if result[0] is None and result[1] is None:
                result = _try_direct_bandcamp_url(artist, title)
            
            if result[0] is not None or result[1] is not None:
                _genre_cache[cache_key] = result
                return result
                
    except Exception:
        pass
    
    _genre_cache[cache_key] = (None, None)
    return (None, None)


def _try_direct_bandcamp_url(artist: str, title: str) -> Tuple[Optional[str], Optional[str]]:
    """Try to access Bandcamp page directly using artist name."""
    from .utils import fetch_url
    
    artist_slug = artist.lower().replace(' ', '-').replace('&', '').replace("'", '').strip()
    title_slug = title.lower().replace(' ', '-').replace('(', '').replace(')', '').replace('[', '').replace(']', '').replace("'", '').replace('&', '').strip()
    
    url_patterns = [
        f"https://{artist_slug}.bandcamp.com/track/{title_slug}",
        f"https://{artist_slug}.bandcamp.com/track/{artist_slug}-{title_slug}",
    ]
    
    for url in url_patterns:
        try:
            request = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status == 200:
                    html_content = response.read().decode('utf-8', errors='ignore')
                    result = _parse_bandcamp_json_ld(html_content)
                    if result[0] is not None or result[1] is not None:
                        return result
        
        except Exception:
            continue
    
    return (None, None)


def _parse_bandcamp_json_ld(html_content: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse Bandcamp JSON-LD schema to extract genre keywords and label."""
    import re
    
    genre = None
    label = None
    
    json_ld_pattern = r'<script[^>]*type="application/ld\+json"[^>]*>([^<]+)</script>'
    matches = re.findall(json_ld_pattern, html_content, re.IGNORECASE)
    
    keywords_found = []
    
    for match in matches:
        try:
            data = json.loads(match)
            
            if isinstance(data, dict):
                keywords = data.get('keywords', [])
                if isinstance(keywords, list):
                    keywords_found.extend([k.lower() for k in keywords])
                
                publisher = data.get('publisher', {})
                if isinstance(publisher, dict):
                    label = publisher.get('name')
                
                if not label:
                    by_artist = data.get('byArtist', {})
                    if isinstance(by_artist, dict):
                        label = by_artist.get('name')
                        
        except (json.JSONDecodeError, TypeError):
            continue
    
    keywords_lower = [k.lower() for k in keywords_found]
    
    house_keywords = {'house', 'tech house', 'afro house', 'deep house', 'disco house',
                     'melodic house', 'organic house', 'future house', 'progressive house',
                     'tropical house', 'funky house', 'garage', 'funky'}
    
    dnb_keywords = {'drum and bass', 'dnb', 'drum&bass', 'drum n bass', 'jungle', 'neurofunk', 'techstep'}
    
    techno_keywords = {'techno', 'hard techno', 'minimal'}
    trance_keywords = {'trance', 'psytrance', 'progressive trance'}
    
    for kw in keywords_lower:
        if kw in house_keywords:
            genre = 'House'
            break
        elif kw in dnb_keywords:
            genre = 'DnB'
            break
        elif kw in techno_keywords:
            genre = 'Techno'
            break
        elif kw in trance_keywords:
            genre = 'Trance'
            break
    
    if not genre:
        for kw in keywords_lower:
            if 'house' in kw:
                genre = 'House'
                break
            elif 'drum' in kw and 'bass' in kw:
                genre = 'DnB'
                break
    
    return (genre, label)


def _parse_bandcamp_genre(html_content: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse Bandcamp search results HTML to find genre and label."""
    import re
    
    genre = None
    label = None
    
    json_ld_result = _parse_bandcamp_json_ld(html_content)
    if json_ld_result[0] is not None or json_ld_result[1] is not None:
        return json_ld_result
    
    tag_pattern = r'<a[^>]+class="tag"[^>]*>([^<]+)</a>'
    tags = re.findall(tag_pattern, html_content, re.IGNORECASE)
    
    house_related = {'house', 'tech house', 'afro house', 'deep house', 'disco house', 
                     'melodic house', 'organic house', 'future house', 'progressive house',
                     'tropical house', 'funky house'}
    
    electronic_genres = {'techno', 'tech house', 'trance', 'ambient', 'electronica', 
                        'downtempo', 'chillout', 'electro', 'dubstep', 'drum and bass',
                        'dnb', 'drone', 'idm', 'experimental'}
    
    all_tags = [tag.strip().lower() for tag in tags]
    
    for tag in all_tags:
        if tag in house_related:
            genre = 'House'
            break
        elif tag in electronic_genres:
            genre = tag.title()
            break
        elif tag == 'electronic':
            genre = 'Electronic'
            break
    
    if not genre:
        for tag in all_tags:
            if 'house' in tag:
                genre = 'House'
                break
            elif 'techno' in tag:
                genre = 'Techno'
                break
            elif 'trance' in tag:
                genre = 'Trance'
                break
    
    return (genre, label)


def lookup_label_online(artist: str, title: str) -> Optional[str]:
    """Lookup label via online services (iTunes primary with track ID lookup)."""
    cache_key = f"{artist.lower()}:{title.lower()}"
    if cache_key in _label_cache:
        return _label_cache[cache_key]
    
    try:
        query = quote(f"{artist} {title}")
        url = f"https://itunes.apple.com/search?term={query}&entity=musicTrack&attribute=songTerm&limit=5"
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data['resultCount'] > 0:
                for track in data['results'][:3]:
                    label = track.get('label')
                    if label and label.strip():
                        _label_cache[cache_key] = label.strip()
                        return label.strip()
                    elif 'trackId' in track:
                        track_id = track['trackId']
                        detail_url = f"https://itunes.apple.com/lookup?id={track_id}"
                        with urllib.request.urlopen(detail_url, timeout=10) as detail_response:
                            detail_data = json.loads(detail_response.read().decode())
                            if detail_data['resultCount'] > 0:
                                detail_label = detail_data['results'][0].get('label')
                                if detail_label and detail_label.strip():
                                    _label_cache[cache_key] = detail_label.strip()
                                    return detail_label.strip()
    except Exception:
        pass
    
    _label_cache[cache_key] = None
    return None


def get_genre_online(artist: str, title: str) -> Optional[str]:
    """Lookup genre via online services with improved accuracy for electronic music."""
    cache_key = f"{artist.lower()}:{title.lower()}"
    if cache_key in _genre_cache:
        cached = _genre_cache[cache_key]
        if isinstance(cached, str):
            return cached
        return None
    
    try:
        query = quote(f"{artist} {title}")
        url = f"https://itunes.apple.com/search?term={query}&entity=musicTrack&attribute=songTerm&limit=10"
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data['resultCount'] > 0:
                electronic_genres = []
                for track in data['results'][:5]:
                    genre = track.get('primaryGenreName')
                    if genre and _is_electronic_genre(genre):
                        electronic_genres.append(_normalize_genre(genre))
                
                if electronic_genres:
                    best_genre = electronic_genres[0]
                    _genre_cache[cache_key] = best_genre
                    return best_genre
                if data['results']:
                    first_genre = data['results'][0].get('primaryGenreName')
                    if first_genre:
                        normalized_genre = _normalize_genre(first_genre)
                        _genre_cache[cache_key] = normalized_genre
                        return normalized_genre
    except Exception:
        pass
    
    bandcamp_genre, _ = _get_genre_from_bandcamp(artist, title)
    if bandcamp_genre:
        _genre_cache[cache_key] = bandcamp_genre
        return bandcamp_genre
    
    try:
        query = quote(f'artist:"{artist}" AND recording:"{title}"')
        url = f"https://musicbrainz.org/ws/2/recording/?query={query}&fmt=json&limit=5"
        request = urllib.request.Request(
            url, 
            headers={'User-Agent': 'WavConverter/1.0'}
        )
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data.get('recordings'):
                for recording in data['recordings'][:3]:
                    recording_id = recording['id']
                    rg_url = f"https://musicbrainz.org/ws/2/release-group/?recording={recording_id}&fmt=json"
                    rg_request = urllib.request.Request(rg_url, headers={'User-Agent': 'WavConverter/1.0'})
                    with urllib.request.urlopen(rg_request, timeout=10) as rg_response:
                        rg_data = json.loads(rg_response.read().decode())
                        if rg_data.get('release-groups'):
                            rg_id = rg_data['release-groups'][0]['id']
                            tag_url = f"https://musicbrainz.org/ws/2/release-group/{rg_id}?inc=tags&fmt=json"
                            tag_request = urllib.request.Request(tag_url, headers={'User-Agent': 'WavConverter/1.0'})
                            with urllib.request.urlopen(tag_request, timeout=10) as tag_response:
                                tag_data = json.loads(tag_response.read().decode())
                                if 'tags' in tag_data.get('release-group', {}) and tag_data['release-group']['tags']:
                                    genre_candidates = []
                                    for tag in tag_data['release-group']['tags']:
                                        tag_name = tag['name'].strip()
                                        if _is_electronic_genre(tag_name):
                                            genre_candidates.append((tag['count'], _normalize_genre(tag_name)))
                                    
                                    if genre_candidates:
                                        genre_candidates.sort(reverse=True)
                                        best_genre = genre_candidates[0][1]
                                        _genre_cache[cache_key] = best_genre
                                        return best_genre
                                    elif tag_data['release-group']['tags']:
                                        tags = tag_data['release-group']['tags']
                                        try:
                                            tags.sort(key=lambda x: x.get('count', 0), reverse=True)
                                        except Exception:
                                            pass
                                        best_genre = _normalize_genre(tags[0]['name'])
                                        _genre_cache[cache_key] = best_genre
                                        return best_genre
    except Exception:
        pass
    
    _genre_cache[cache_key] = None
    return None


def get_additional_metadata_online(artist: str, title: str) -> Dict[str, Optional[str]]:
    """Lookup additional metadata (album, year, track_number) from online services."""
    cache_key = f"{artist.lower()}:{title.lower()}"
    if cache_key in _additional_metadata_cache:
        return _additional_metadata_cache[cache_key]
    
    result = {'album': None, 'year': None, 'track_number': None}
    
    try:
        query = quote(f"{artist} {title}")
        url = f"https://itunes.apple.com/search?term={query}&entity=musicTrack&attribute=songTerm&limit=5"
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data['resultCount'] > 0:
                track = data['results'][0]
                result['album'] = track.get('collectionName')
                result['track_number'] = track.get('trackNumber')
                release_date = track.get('releaseDate')
                if release_date:
                    result['year'] = release_date[:4] if len(release_date) >= 4 else None
    except Exception:
        pass
    
    _additional_metadata_cache[cache_key] = result
    return result


def _write_metadata_tags(wav_path: str, tags: Dict[str, str]) -> bool:
    """Write multiple metadata tags to audio file in a single ffmpeg call."""
    import os
    import subprocess
    
    if not tags:
        return True
    
    try:
        path_obj = Path(wav_path)
        suffix = path_obj.suffix.lower()
        temp_path = str(path_obj) + '.tmp' + suffix
        
        cmd = [
            'ffmpeg', '-y', '-i', str(wav_path),
            '-map', '0',
            '-codec', 'copy',
        ]
        
        for tag, value in tags.items():
            escaped_value = value.replace("'", "'\\''")
            cmd.extend(['-metadata', f'{tag}={escaped_value}'])
        
        cmd.append(temp_path)
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            os.replace(temp_path, str(wav_path))
            return True
        else:
            logger.warning(f"Failed to write metadata tags to {wav_path}: {result.stderr[:200]}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return False
    except Exception as e:
        logger.warning(f"Error writing metadata tags to {wav_path}: {str(e)}")
        return False


def enrich_file_metadata(wav_path: str, artist: str, title: str, config: Dict[str, Any], current_metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Enrich file metadata from online sources and write to file.
    
    Args:
        wav_path: Path to the WAV file
        artist: Artist name
        title: Track title
        config: Configuration dict with enrich_metadata settings
        current_metadata: Pre-extracted metadata to avoid duplicate ffprobe calls
        
    Returns:
        Dict with enriched metadata fields
    """
    enriched = {}
    write_tags = config.get('enrich_metadata', {}).get('write_tags', [])
    label_source_tag = config.get('enrich_metadata', {}).get('label_source_tag', 'label')
    
    if not write_tags:
        return enriched
    
    if current_metadata is None:
        current_metadata = extract_metadata(wav_path)
    
    label_tag = label_source_tag if label_source_tag else 'label'
    tags_to_write = {}
    
    if 'label' in write_tags:
        label = current_metadata.get('label') or current_metadata.get('Label') or current_metadata.get('TPUB')
        if not label:
            label = lookup_label_online(artist, title)
            if label:
                tags_to_write[label_tag] = label
                enriched['label'] = label
    
    if 'genre' in write_tags:
        genre = current_metadata.get('genre')
        if not genre:
            genre = get_genre_online(artist, title)
            if genre:
                tags_to_write['genre'] = genre
                enriched['genre'] = genre
    
    if 'album' in write_tags or 'year' in write_tags or 'track_number' in write_tags:
        album = current_metadata.get('album')
        year = current_metadata.get('date')
        track_number = current_metadata.get('track_number')
        
        if not album or not year or not track_number:
            additional = get_additional_metadata_online(artist, title)
            
            if 'album' in write_tags and not album and additional.get('album'):
                tags_to_write['album'] = additional['album']
                enriched['album'] = additional['album']
            
            if 'year' in write_tags and not year and additional.get('year'):
                tags_to_write['date'] = additional['year']
                enriched['year'] = additional['year']
            
            if 'track_number' in write_tags and not track_number and additional.get('track_number'):
                tags_to_write['track'] = str(additional['track_number'])
                enriched['track_number'] = additional['track_number']
    
    if tags_to_write:
        if _write_metadata_tags(wav_path, tags_to_write):
            logger.info(f"  Enriched metadata: {enriched}")
        else:
            enriched = {}
    
    return enriched
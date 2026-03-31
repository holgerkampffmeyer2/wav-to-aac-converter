#!/usr/bin/env python3
"""WAV to MP3/M4A converter with loudness normalization, metadata, and cover art."""

import subprocess
import json
import sys
import os
import re
import time
import argparse
import logging
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import wraps
from urllib.parse import quote
import unicodedata
from typing import Optional, Tuple, Dict, Any, List, Set, Union

logger = logging.getLogger(__name__)

# These constants are now loaded from config.json
# MAX_PARALLEL_PROCESSES = 5
# OUTPUT_FORMAT = 'mp3'

OG_IMAGE_RE = re.compile(r'"og:image"\s+content="([^"]+)"')
BANDCAMP_URL_RE = re.compile(r'https?://[^\s"\'<>]*\.bandcamp\.com/(?:track|album)/[^\s"\'<>]*')
SNDCLOUD_ARTWORK_RE = re.compile(r'https?://i1\.sndcdn\.com/artworks-[\w-]+\.(?:png|jpg)')
HANDLE_RE = re.compile(r'\[([^\]]+)\]', re.IGNORECASE)
NON_WORD_RE = re.compile(r'[^\w]')
MULTI_DASH_RE = re.compile(r'-+')
BRACKET_CLEANUP_RE = re.compile(r'\([^)]*\)|\[[^\]]*\]')
REMIX_KEYWORDS_RE = re.compile(
    r'(?:remix|edit|mix|flip|rework|cover|feat|ft\.|featuring|radio|clean|explicit|instrumental|acappella|bootleg)',
    re.IGNORECASE
)
USER_AGENT = '"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"'


def retry(max_attempts: int = 3, delay: int = 1, backoff: int = 2):
    """Retry decorator with exponential backoff for HTTP operations."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    result = func(*args, **kwargs)
                    if result is not None:
                        return result
                except Exception as e:
                    last_exception = e
                if attempt < max_attempts - 1:
                    sleep_time = delay * (backoff ** attempt)
                    time.sleep(sleep_time)
            return None
        return wrapper
    return decorator


def load_config() -> Dict[str, Any]:
    """Load configuration from config.json file."""
    config_path = Path(__file__).parent / 'config.json'
    default_config: Dict[str, Any] = {
        "ascii_filename": False,
        "output_format": "mp3",
        "max_parallel_processes": 5,
        "loudnorm": True,
        "embed_cover": True,
        "retry_attempts": 3,
        "timeout_seconds": 30
    }
    
    try:
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = json.load(f)
                # Merge with defaults to ensure all keys exist
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                return config
        else:
            return default_config
    except Exception as e:
        logger.warning(f"Could not load config file: {e}")
        return default_config


def to_ascii_filename(filename: str) -> str:
    """Convert Unicode filename to ASCII equivalent."""
    # Normalize Unicode characters (decompose accents, etc.)
    normalized = unicodedata.normalize('NFKD', filename)
    # Remove non-ASCII characters
    ascii_only = normalized.encode('ascii', 'ignore').decode('ascii')
    # Clean up any extra spaces or special characters that might result
    ascii_only = re.sub(r'[^\w\s\-_.()\[\]]', '', ascii_only)
    ascii_only = re.sub(r'\s+', ' ', ascii_only).strip()
    return ascii_only


def run_cmd(cmd: str, capture_output: bool = True, timeout: int = 600) -> Tuple[bool, str, str]:
    """Run shell command and return output."""
    print(f"DEBUG run_cmd: executing: {cmd[:200]}...", flush=True)
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=capture_output, text=True, timeout=timeout
        )
        print(f"DEBUG run_cmd: returncode={result.returncode}", flush=True)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        print(f"DEBUG run_cmd: TIMEOUT", flush=True)
        return False, "", "Command timed out"


def analyze_loudness(wav_path: str) -> Optional[Dict[str, Any]]:
    """Analyze loudness of WAV file using first 5 minutes for speed."""
    cmd = f'ffmpeg -t 300 -i "{wav_path}" -af loudnorm=print_format=json -f null - 2>&1'
    success, stdout, stderr = run_cmd(cmd)
    if not success:
        return None
    output = stdout + stderr
    try:
        start = output.index('{')
        end = output.rindex('}') + 1
        json_str = output[start:end]
        return json.loads(json_str)
    except (ValueError, json.JSONDecodeError):
        return None


def extract_metadata(wav_path: str) -> Dict[str, Any]:
    """Extract metadata from WAV file."""
    cmd = f'ffprobe -v quiet -print_format json -show_format -show_streams "{wav_path}"'
    success, stdout, _ = run_cmd(cmd)
    if not success:
        return {}
    try:
        data = json.loads(stdout)
        tags = data.get('format', {}).get('tags', {})
        return {
            'title': tags.get('title', ''),
            'artist': tags.get('artist', ''),
            'album': tags.get('album', ''),
            'genre': tags.get('genre', ''),
            'date': tags.get('date', ''),
            'duration': float(data.get('format', {}).get('duration', 0))
        }
    except json.JSONDecodeError:
        return {}


def fetch_url(url: str, timeout: int = 15, headers: Optional[Dict[str, str]] = None, method: str = 'GET', data: Optional[Dict[str, str]] = None) -> str:
    """Fetch URL content with configurable options.
    
    Args:
        url (str): URL to fetch
        timeout (int): Request timeout in seconds
        headers (dict): Custom headers to send
        method (str): HTTP method (GET, POST, etc.)
        data (dict): Data to send (for POST requests)
        
    Returns:
        str: Response content or empty string on failure
    """
    # Default headers
    default_headers: Dict[str, str] = {
        'User-Agent': USER_AGENT.strip('"'),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }
    
    # Merge custom headers with defaults
    if headers:
        default_headers.update(headers)
    
    # Build curl command
    curl_cmd = ['curl', '-sL']  # Silent, follow redirects
    
    # Add headers - properly quote values that might contain special characters
    for key, value in default_headers.items():
        # Properly format the header for shell: -H "Key: Value"
        # Quote the entire value to handle spaces and special characters
        curl_cmd.extend(['-H', f'{key}: "{value}"'])
    
    # Add timeout
    curl_cmd.extend(['--max-time', str(timeout)])
    
    # Add method and data if needed
    if method.upper() == 'POST' and data:
        curl_cmd.extend(['-X', 'POST'])
        # Convert dict to form data
        form_data = []
        for key, value in data.items():
            # Properly escape the form data values
            escaped_value = value.replace('"', '\\"')
            form_data.extend(['-d', f'{key}={escaped_value}'])
        curl_cmd.extend(form_data)
    
    # Add URL
    curl_cmd.append(url)
    
    # Execute command
    success, stdout, _ = run_cmd(' '.join(curl_cmd), timeout=timeout + 5)
    return stdout if success else ""


@retry(max_attempts=3, delay=1, backoff=2)
def search_deezer_cover(artist: str, title: str) -> Optional[str]:
    """Search Deezer API for cover art."""
    if not artist and not title:
        return None
    query = f"{artist}+{title}".replace(' ', '+')
    url = f"https://api.deezer.com/search/album?q={query}"
    content = fetch_url(url)
    if not content:
        return None
    try:
        data = json.loads(content)
        if data.get('data') and len(data['data']) > 0:
            return data['data'][0].get('cover_big')
    except json.JSONDecodeError:
        pass
    return None


@retry(max_attempts=3, delay=1, backoff=2)
def search_bandcamp_cover(artist: str, title: str) -> Optional[str]:
    """Search Bandcamp for cover art via web search."""
    if not artist and not title:
        return None
    query = f"{artist} {title}".strip()
    if not query:
        return None
    search_url = f"https://bandcamp.com/search?q={query.replace(' ', '+')}"
    content = fetch_url(search_url)
    if not content:
        return None
    
    match = BANDCAMP_URL_RE.search(content)
    if not match:
        return None
    
    bandcamp_url = match.group(0).split('"')[0].split('&')[0]
    page_content = fetch_url(bandcamp_url)
    if page_content:
        img_match = OG_IMAGE_RE.search(page_content)
        if img_match:
            return img_match.group(1)
    return None


def extract_handles(filename: str) -> List[str]:
    """Extract SoundCloud handles from filename."""
    return [h for h in HANDLE_RE.findall(filename.lower()) if len(h) >= 3]


def clean_title_for_search(title: str) -> str:
    """Remove remix/edit/etc. info from title for cover art search.
    
    Removes any bracket (with nested content) if it contains remix/edit/etc. keywords.
    """
    def find_matching_paren(text: str, start: int) -> int:
        """Find the closing paren/bracket for the opener at start."""
        opener = text[start]
        closer = ']' if opener == '[' else ')'
        depth = 0
        for i in range(start, len(text)):
            if text[i] in '()[]':
                if text[i] == opener:
                    depth += 1
                elif text[i] == closer:
                    depth -= 1
                    if depth == 0:
                        return i
        return -1
    
    def strip_brackets(text: str) -> str:
        """Remove brackets containing keywords."""
        removed_something = True
        while removed_something:
            removed_something = False
            for opener in ['[', '(']:
                closer = ']' if opener == '[' else ')'
                idx = 0
                while idx < len(text):
                    if idx < len(text) and text[idx] == opener:
                        end = find_matching_paren(text, idx)
                        if end > idx:
                            content = text[idx+1:end]
                            if REMIX_KEYWORDS_RE.search(content):
                                text = text[:idx] + text[end+1:]
                                removed_something = True
                                break
                    idx += 1
        return text.strip()
    
    return strip_brackets(title)


def _fetch_soundcloud_cover(sc_url: str) -> Optional[str]:
    """Fetch cover art from a SoundCloud page."""
    content = _fetch_url(sc_url)
    if not content:
        return None
    
    img_match = OG_IMAGE_RE.search(content)
    if img_match:
        return img_match.group(1)
    
    img_match = SNDCLOUD_ARTWORK_RE.search(content)
    if img_match:
        return img_match.group(0)
    return None


def _fetch_url(url: str) -> str:
    """Internal helper to fetch URL for SoundCloud (reuses fetch_url logic)."""
    # Reuse the existing fetch_url function but without parameters for simplicity in this context
    return fetch_url(url)


def _generate_soundcloud_handles_from_artist(artist: str) -> List[str]:
    """Generate potential SoundCloud handles from an artist name."""
    if not artist:
        return []
    handles: Set[str] = set()
    # Basic conversions
    artist_lower = artist.lower()
    # Replace spaces and punctuation with hyphens, then clean
    artist_clean = re.sub(r'[^\w]+', '-', artist_lower).strip('-')
    # Remove leading/trailing hyphens and collapse multiple hyphens
    artist_clean = MULTI_DASH_RE.sub('-', artist_clean)
    if artist_clean and len(artist_clean) >= 3:
        handles.add(artist_clean)
    # Also try with underscores instead of hyphens
    artist_underscore = re.sub(r'[^\w]+', '_', artist_lower).strip('_')
    # Fix: Use underscore-specific regex for collapsing underscores
    artist_underscore = re.sub(r'_+', '_', artist_underscore)
    if len(artist_underscore) >= 3:
        handles.add(artist_underscore)
    # Try removing spaces entirely
    artist_nospace = artist_lower.replace(' ', '')
    if len(artist_nospace) >= 3:
        handles.add(artist_nospace)
    # Common suffixes that might be used in SoundCloud usernames
    suffixes = ['_dj', '_official', '_music', '_records', '_label', '_prod', '_producer', '_audio', '_sound']
    base_for_suffix = artist_clean if artist_clean else artist_nospace
    if base_for_suffix:
        for suffix in suffixes:
            handle = base_for_suffix + suffix
            if len(handle) >= 3:
                handles.add(handle)
    # Also try the first word if it's long enough
    words = artist_lower.split()
    for word in words:
        if len(word) >= 3:
            handles.add(word)
            # Add suffixes to first word too
            for suffix in suffixes:
                handle = word + suffix
                if len(handle) >= 3:
                    handles.add(handle)
    return list(handles)


def _search_soundcloud_with_components(
    artist: str, 
    title: str, 
    filename: str,
    all_handles: List[str],
    track_base_from_title: str,
    track_base_from_filename: str,
    artist_slug: str
) -> Tuple[Optional[Tuple[str, str]], Optional[str]]:
    """Search SoundCloud via web for track info and cover art using prepared components."""
    searched: Set[str] = set()
    
    # Try combinations of handles and track bases
    for handle in all_handles:
        if len(handle) < 3:
            continue
        for track_base in [track_base_from_title, track_base_from_filename]:
            if not track_base:
                continue
            # Try the track base alone as the slug (most common pattern: artist/track)
            slug: str = track_base
            slug = MULTI_DASH_RE.sub('-', slug).strip('-')
            if slug and len(slug) >= 3:
                for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                    sc_url: str = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                    if sc_url not in searched:
                        searched.add(sc_url)
                        img_url: Optional[str] = _fetch_soundcloud_cover(sc_url)
                        if img_url:
                            return (artist, title), img_url
            # Try artist_slug + track_base as the slug
            slug: str = f"{artist_slug}-{track_base}"
            slug = MULTI_DASH_RE.sub('-', slug).strip('-')
            if slug and len(slug) >= 3:
                for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                    sc_url: str = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                    if sc_url not in searched:
                        searched.add(sc_url)
                        img_url: Optional[str] = _fetch_soundcloud_cover(sc_url)
                        if img_url:
                            return (artist, title), img_url
            # Try the original combinations for completeness
            for slug in [f"{artist_slug}-{track_base}-{handle}", f"{handle}-{track_base}", f"{track_base}-{handle}"]:
                slug: str = MULTI_DASH_RE.sub('-', slug).strip('-')
                if slug and len(slug) >= 3:
                    for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                        sc_url: str = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                        if sc_url not in searched:
                            searched.add(sc_url)
                            img_url: Optional[str] = _fetch_soundcloud_cover(sc_url)
                            if img_url:
                                return (artist, title), img_url
        # Also try the handle alone (artist profile page) - though this is less likely to have cover art for a specific track
        sc_url: str = f"https://soundcloud.com/{handle}"
        if sc_url not in searched:
            searched.add(sc_url)
            img_url: Optional[str] = _fetch_soundcloud_cover(sc_url)
            if img_url:
                return (artist, title), img_url
    
    return None, None


def search_soundcloud_web(artist: str, title: str, filename: str = "") -> Tuple[Optional[Tuple[str, str]], Optional[str]]:
    """Search SoundCloud via web for track info and cover art."""
    if not artist and not title and not filename:
        return None, None
    
    # Extract and prepare search components
    filename_handles = extract_handles(filename or "")
    artist_handles = _generate_soundcloud_handles_from_artist(artist)
    all_handles: List[str] = list(set(filename_handles + artist_handles))
    
    # Clean title for search: remove filename handles and bracketed content
    cleaned_title: str = title
    for handle in filename_handles:  # Only remove handles that came from the filename
        cleaned_title = re.sub(r'\[' + re.escape(handle) + r'\]', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = BRACKET_CLEANUP_RE.sub('', cleaned_title)
    cleaned_title = re.sub(r'[_-]+', '-', cleaned_title)
    track_base_from_title: str = cleaned_title.lower().replace('(', '-').replace(')', '').replace(' ', '-')
    for kw in ['remix', 'edit', 'mix', 'master', 'loud', 'dub', 'clean', 'explicit', 'instrumental', 'acappella', 'radio', 'original', 'free', 'download']:
        track_base_from_title = re.sub(rf'-{kw}-?', '-', track_base_from_title)
    track_base_from_title = MULTI_DASH_RE.sub('-', track_base_from_title).strip('-')
    
    # Also try to get track base from the part before the first ' - ' in filename
    track_base_from_filename: str = ""
    if ' - ' in filename:
        before_dash = filename.split(' - ')[0].strip()
        # Clean it: make lowercase, replace non-alphanumeric with hyphen, collapse hyphens
        temp: str = re.sub(r'[^\w]+', '-', before_dash).lower()
        track_base_from_filename = MULTI_DASH_RE.sub('-', temp).strip('-')
    
    # We'll try both track bases
    track_bases_to_try: Set[str] = set()
    if track_base_from_title:
        track_bases_to_try.add(track_base_from_title)
    if track_base_from_filename:
        track_bases_to_try.add(track_base_from_filename)
    
    artist_slug: str = artist.lower().replace(' ', '-') if artist else ''
    
    return _search_soundcloud_with_components(
        artist, title, filename,
        all_handles,
        track_base_from_title,
        track_base_from_filename,
        artist_slug
    )
    
    # Extract handles from filename
    filename_handles = extract_handles(filename or "")
    # Generate potential handles from artist name
    artist_handles = _generate_soundcloud_handles_from_artist(artist)
    # Combine and deduplicate
    all_handles = list(set(filename_handles + artist_handles))
    
    # Clean title for search: remove filename handles and bracketed content
    cleaned_title = title
    for handle in filename_handles:  # Only remove handles that came from the filename
        cleaned_title = re.sub(r'\[' + re.escape(handle) + r'\]', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = BRACKET_CLEANUP_RE.sub('', cleaned_title)
    cleaned_title = re.sub(r'[_-]+', '-', cleaned_title)
    track_base_from_title = cleaned_title.lower().replace('(', '-').replace(')', '').replace(' ', '-')
    for kw in ['remix', 'edit', 'mix', 'master', 'loud', 'dub', 'clean', 'explicit', 'instrumental', 'acappella', 'radio', 'original', 'free', 'download']:
        track_base_from_title = re.sub(rf'-{kw}-?', '-', track_base_from_title)
    track_base_from_title = MULTI_DASH_RE.sub('-', track_base_from_title).strip('-')
    
    # Also try to get track base from the part before the first ' - ' in filename
    track_base_from_filename = ""
    if ' - ' in filename:
        before_dash = filename.split(' - ')[0].strip()
        # Clean it: make lowercase, replace non-alphanumeric with hyphen, collapse hyphens
        temp = re.sub(r'[^\w]+', '-', before_dash).lower()
        track_base_from_filename = MULTI_DASH_RE.sub('-', temp).strip('-')
    
    # We'll try both track bases
    track_bases_to_try = set()
    if track_base_from_title:
        track_bases_to_try.add(track_base_from_title)
    if track_base_from_filename:
        track_bases_to_try.add(track_base_from_filename)
    
    artist_slug = artist.lower().replace(' ', '-') if artist else ''
    
    searched = set()
    
    # Try combinations of handles and track bases
    for handle in all_handles:
        if len(handle) < 3:
            continue
        for track_base in track_bases_to_try:
            if not track_base:
                continue
            # Try the track base alone as the slug (most common pattern: artist/track)
            slug = track_base
            slug = MULTI_DASH_RE.sub('-', slug).strip('-')
            if slug and len(slug) >= 3:
                for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                    sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                    if sc_url not in searched:
                        searched.add(sc_url)
                        img_url = _fetch_soundcloud_cover(sc_url)
                        if img_url:
                            return (artist, title), img_url
            # Try artist_slug + track_base as the slug
            slug = f"{artist_slug}-{track_base}"
            slug = MULTI_DASH_RE.sub('-', slug).strip('-')
            if slug and len(slug) >= 3:
                for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                    sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                    if sc_url not in searched:
                        searched.add(sc_url)
                        img_url = _fetch_soundcloud_cover(sc_url)
                        if img_url:
                            return (artist, title), img_url
            # Try the original combinations for completeness
            for slug in [f"{artist_slug}-{track_base}-{handle}", f"{handle}-{track_base}", f"{track_base}-{handle}"]:
                slug = MULTI_DASH_RE.sub('-', slug).strip('-')
                if slug and len(slug) >= 3:
                    for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                        sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                        if sc_url not in searched:
                            searched.add(sc_url)
                            img_url = _fetch_soundcloud_cover(sc_url)
                            if img_url:
                                return (artist, title), img_url
        # Also try the handle alone (artist profile page) - though this is less likely to have cover art for a specific track
        sc_url = f"https://soundcloud.com/{handle}"
        if sc_url not in searched:
            searched.add(sc_url)
            img_url = _fetch_soundcloud_cover(sc_url)
            if img_url:
                return (artist, title), img_url
    
    return None, None
    
    # Extract handles from filename
    filename_handles = extract_handles(filename or "")
    # Generate potential handles from artist name
    artist_handles = _generate_soundcloud_handles_from_artist(artist)
    # Combine and deduplicate
    all_handles = list(set(filename_handles + artist_handles))
    
    # Clean title for search: remove filename handles and bracketed content
    cleaned_title = title
    for handle in filename_handles:  # Only remove handles that came from the filename
        cleaned_title = re.sub(r'\[' + re.escape(handle) + r'\]', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = BRACKET_CLEANUP_RE.sub('', cleaned_title)
    cleaned_title = re.sub(r'[_-]+', '-', cleaned_title)
    track_base_from_title = cleaned_title.lower().replace('(', '-').replace(')', '').replace(' ', '-')
    for kw in ['remix', 'edit', 'mix', 'master', 'loud', 'dub', 'clean', 'explicit', 'instrumental', 'acappella', 'radio', 'original', 'free', 'download']:
        track_base_from_title = re.sub(rf'-{kw}-?', '-', track_base_from_title)
    track_base_from_title = MULTI_DASH_RE.sub('-', track_base_from_title).strip('-')
    
    # Also try to get track base from the part before the first ' - ' in filename
    track_base_from_filename = ""
    if ' - ' in filename:
        before_dash = filename.split(' - ')[0].strip()
        # Clean it: make lowercase, replace non-alphanumeric with hyphen, collapse hyphens
        temp = re.sub(r'[^\w]+', '-', before_dash).lower()
        track_base_from_filename = MULTI_DASH_RE.sub('-', temp).strip('-')
    
    # We'll try both track bases
    track_bases_to_try = set()
    if track_base_from_title:
        track_bases_to_try.add(track_base_from_title)
    if track_base_from_filename:
        track_bases_to_try.add(track_base_from_filename)
    
    artist_slug = artist.lower().replace(' ', '-') if artist else ''
    
    searched = set()
    
    # Try combinations of handles and track bases
    for handle in all_handles:
        if len(handle) < 3:
            continue
        for track_base in track_bases_to_try:
            if not track_base:
                continue
            # Try the track base alone as the slug (most common pattern: artist/track)
            slug = track_base
            slug = MULTI_DASH_RE.sub('-', slug).strip('-')
            if slug and len(slug) >= 3:
                for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                    sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                    if sc_url not in searched:
                        searched.add(sc_url)
                        img_url = _fetch_soundcloud_cover(sc_url)
                        if img_url:
                            return (artist, title), img_url
            # Try artist_slug + track_base as the slug
            slug = f"{artist_slug}-{track_base}"
            slug = MULTI_DASH_RE.sub('-', slug).strip('-')
            if slug and len(slug) >= 3:
                for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                    sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                    if sc_url not in searched:
                        searched.add(sc_url)
                        img_url = _fetch_soundcloud_cover(sc_url)
                        if img_url:
                            return (artist, title), img_url
            # Try the original combinations for completeness
            for slug in [f"{artist_slug}-{track_base}-{handle}", f"{handle}-{track_base}", f"{track_base}-{handle}"]:
                slug = MULTI_DASH_RE.sub('-', slug).strip('-')
                if slug and len(slug) >= 3:
                    for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                        sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                        if sc_url not in searched:
                            searched.add(sc_url)
                        img_url = _fetch_soundcloud_cover(sc_url)
                        if img_url:
                            return (artist, title), img_url
        # Also try the handle alone (artist profile page) - though this is less likely to have cover art for a specific track
        sc_url = f"https://soundcloud.com/{handle}"
        if sc_url not in searched:
            searched.add(sc_url)
            img_url = _fetch_soundcloud_cover(sc_url)
            if img_url:
                return (artist, title), img_url
    
    return None, None
    
    # Extract handles from filename
    filename_handles = extract_handles(filename or "")
    # Generate potential handles from artist name
    artist_handles = _generate_soundcloud_handles_from_artist(artist)
    # Combine and deduplicate
    all_handles = list(set(filename_handles + artist_handles))
    
    # Clean title for search: remove filename handles and bracketed content
    cleaned_title = title
    for handle in filename_handles:  # Only remove handles that came from the filename
        cleaned_title = re.sub(r'\[' + re.escape(handle) + r'\]', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = BRACKET_CLEANUP_RE.sub('', cleaned_title)
    cleaned_title = re.sub(r'[_-]+', '-', cleaned_title)
    track_base_from_title = cleaned_title.lower().replace('(', '-').replace(')', '').replace(' ', '-')
    for kw in ['remix', 'edit', 'mix', 'master', 'loud', 'dub', 'clean', 'explicit', 'instrumental', 'acappella', 'radio', 'original', 'free', 'download']:
        track_base_from_title = re.sub(rf'-{kw}-?', '-', track_base_from_title)
    track_base_from_title = MULTI_DASH_RE.sub('-', track_base_from_title).strip('-')
    
    # Also try to get track base from the part before the first ' - ' in filename
    track_base_from_filename = ""
    if ' - ' in filename:
        before_dash = filename.split(' - ')[0].strip()
        # Clean it: make lowercase, replace non-alphanumeric with hyphen, collapse hyphens
        temp = re.sub(r'[^\w]+', '-', before_dash).lower()
        track_base_from_filename = MULTI_DASH_RE.sub('-', temp).strip('-')
    
    # We'll try both track bases
    track_bases_to_try = set()
    if track_base_from_title:
        track_bases_to_try.add(track_base_from_title)
    if track_base_from_filename:
        track_bases_to_try.add(track_base_from_filename)
    
    artist_slug = artist.lower().replace(' ', '-') if artist else ''
    
    searched = set()
    
    # Try combinations of handles and track bases
    for handle in all_handles:
        if len(handle) < 3:
            continue
        for track_base in track_bases_to_try:
            if not track_base:
                continue
            # Try the track base alone as the slug (most common pattern: artist/track)
            slug = track_base
            slug = MULTI_DASH_RE.sub('-', sg).strip('-')
            if sg and len(sg) >= 3:
                for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                    sc_url = f"https://soundcloud.com/{handle}/{sg}{suffix}"
                    if sc_url not in searched:
                        searched.add(sc_url)
                        img_url = _fetch_soundcloud_cover(sc_url)
                        if img_url:
                            return (artist, title), img_url
            # Try artist_slug + track_base as the slug
            slug = f"{artist_slug}-{track_base}"
            sg = MULTI_DASH_RE.sub('-', sg).strip('-')
            if sg and len(sg) >= 3:
                for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                    sc_url = f"https://soundcloud.com/{handle}/{sg}{suffix}"
                    if sc_url not in searched:
                        searched.add(sc_url)
                        img_url = _fetch_soundcloud_cover(sc_url)
                        if img_url:
                            return (artist, title), img_url
            # Try the original combinations for completeness
            for sg in [f"{artist_slug}-{track_base}-{handle}", f"{handle}-{track_base}", f"{track_base}-{handle}"]:
                sg = MULTI_DASH_RE.sub('-', sg).strip('-')
                if sg and len(sg) >= 3:
                    for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                        sc_url = f"https://soundcloud.com/{handle}/{sg}{suffix}"
                        if sc_url not in searched:
                            searched.add(sc_url)
                        img_url = _fetch_soundcloud_cover(sc_url)
                        if img_url:
                            return (artist, title), img_url
        # Also try the handle alone (artist profile page) - though this is less likely to have cover art for a specific track
        sc_url = f"https://soundcloud.com/{handle}"
        if sc_url not in searched:
            searched.add(sc_url)
            img_url = _fetch_soundcloud_cover(sc_url)
            if img_url:
                return (artist, title), img_url
    
    return None, None
    
    # Extract handles from filename
    filename_handles = extract_handles(filename or "")
    # Generate potential handles from artist name
    artist_handles = _generate_soundcloud_handles_from_artist(artist)
    # Combine and deduplicate
    all_handles = list(set(filename_handles + artist_handles))
    
    # Clean title for search: remove filename handles and bracketed content
    cleaned_title = title
    for handle in filename_handles:  # Only remove handles that came from the filename
        cleaned_title = re.sub(r'\[' + re.escape(handle) + r'\]', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = BRACKET_CLEANUP_RE.sub('', cleaned_title)
    cleaned_title = re.sub(r'[_-]+', '-', cleaned_title)
    track_base_from_title = cleaned_title.lower().replace('(', '-').replace(')', '').replace(' ', '-')
    for kw in ['remix', 'edit', 'mix', 'master', 'loud', 'dub', 'clean', 'explicit', 'instrumental', 'acappella', 'radio', 'original', 'free', 'download']:
        track_base_from_title = re.sub(rf'-{kw}-?', '-', track_base_from_title)
    track_base_from_title = MULTI_DASH_RE.sub('-', track_base_from_title).strip('-')
    
    # Also try to get track base from the part before the first ' - ' in filename
    track_base_from_filename = ""
    if ' - ' in filename:
        before_dash = filename.split(' - ')[0].strip()
        # Clean it: make lowercase, replace non-alphanumeric with hyphen, collapse hyphens
        temp = re.sub(r'[^\w]+', '-', before_dash).lower()
        track_base_from_filename = MULTI_DASH_RE.sub('-', temp).strip('-')
    
    # We'll try both track bases
    track_bases_to_try = set()
    if track_base_from_title:
        track_bases_to_try.add(track_base_from_title)
    if track_base_from_filename:
        track_bases_to_try.add(track_base_from_filename)
    
    artist_slug = artist.lower().replace(' ', '-') if artist else ''
    
    searched = set()
    found_img_url = None
    found_web_metadata = None
    
    logger.debug(f"SoundCloud search: artist='{artist}', title='{title}', filename='{filename}'")
    logger.debug(f"SoundCloud search: filename_handles={filename_handles}")
    logger.debug(f"SoundCloud search: artist_handles={artist_handles}")
    logger.debug(f"SoundCloud search: all_handles={all_handles}")
    logger.debug(f"SoundCloud search: track_base_from_title='{track_base_from_title}'")
    logger.debug(f"SoundCloud search: track_base_from_filename='{track_base_from_filename}'")
    logger.debug(f"SoundCloud search: track_bases_to_try={list(track_bases_to_try)}")
    logger.debug(f"SoundCloud search: artist_slug='{artist_slug}'")
    
    # Try combinations of handles and track bases
    for handle in all_handles:
        if len(handle) < 3:
            continue
        for track_base in track_bases_to_try:
            if not track_base:
                continue
            # Try the track base alone as the slug (most common pattern: artist/track)
            slug = track_base
            slug = MULTI_DASH_RE.sub('-', slug).strip('-')
            if slug and len(slug) >= 3:
                for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                    sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                    if sc_url not in searched:
                        searched.add(sc_url)
                        logger.debug(f"SoundCloud search: Trying URL: {sc_url}")
                        img_url = _fetch_soundcloud_cover(sc_url)
                        if img_url:
                            logger.debug(f"SoundCloud search: FOUND COVER: {img_url}")
                            return (artist, title), img_url
            # Try artist_slug + track_base as the slug
            slug = f"{artist_slug}-{track_base}"
            slug = MULTI_DASH_RE.sub('-', slug).strip('-')
            if slug and len(slug) >= 3:
                for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                    sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                    if sc_url not in searched:
                        searched.add(sc_url)
                        logger.debug(f"SoundCloud search: Trying URL: {sc_url}")
                        img_url = _fetch_soundcloud_cover(sc_url)
                        if img_url:
                            logger.debug(f"SoundCloud search: FOUND COVER: {img_url}")
                            return (artist, title), img_url
            # Try the original combinations for completeness
            for slug in [f"{artist_slug}-{track_base}-{handle}", f"{handle}-{track_base}", f"{track_base}-{handle}"]:
                slug = MULTI_DASH_RE.sub('-', slug).strip('-')
                if slug and len(slug) >= 3:
                    for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                        sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                        if sc_url not in searched:
                            searched.add(sc_url)
                            logger.debug(f"SoundCloud search: Trying URL: {sc_url}")
                            img_url = _fetch_soundcloud_cover(sc_url)
                            if img_url:
                                logger.debug(f"SoundCloud search: FOUND COVER: {img_url}")
                                return (artist, title), img_url
        # Also try the handle alone (artist profile page) - though this is less likely to have cover art for a specific track
        sc_url = f"https://soundcloud.com/{handle}"
        if sc_url not in searched:
            searched.add(sc_url)
            logger.debug(f"SoundCloud search: Trying profile URL: {sc_url}")
            img_url = _fetch_soundcloud_cover(sc_url)
            if img_url:
                logger.debug(f"SoundCloud search: FOUND COVER from profile: {img_url}")
                return (artist, title), img_url
    
    logger.debug(f"SoundCloud search: NO COVER FOUND after trying {len(searched)} URLs")
    return None, None
    
    handles = extract_handles(filename or "")
    
    cleaned_title = title
    for handle in handles:
        cleaned_title = re.sub(r'\[' + re.escape(handle) + r'\]', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = BRACKET_CLEANUP_RE.sub('', cleaned_title)
    cleaned_title = re.sub(r'[_-]+', '-', cleaned_title)
    track_base = cleaned_title.lower().replace('(', '-').replace(')', '').replace(' ', '-')
    for kw in ['remix', 'edit', 'mix', 'master', 'loud', 'dub', 'clean', 'explicit', 'instrumental', 'acappella', 'radio', 'original', 'free', 'download']:
        track_base = re.sub(rf'-{kw}-?', '-', track_base)
    track_base = MULTI_DASH_RE.sub('-', track_base).strip('-')
    
    artist_slug = artist.lower().replace(' ', '-') if artist else ''
    
    searched = set()
    
    # Try filename-derived handles with combinations of artist_slug and track_base
    for handle in handles:
        if len(handle) >= 3:
            for slug in [f"{artist_slug}-{track_base}-{handle}", f"{handle}-{track_base}", f"{track_base}-{handle}"]:
                slug = MULTI_DASH_RE.sub('-', slug).strip('-')
                if slug and len(slug) >= 3:
                    for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                        sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                        if sc_url not in searched:
                            searched.add(sc_url)
                            img_url = _fetch_soundcloud_cover(sc_url)
                            if img_url:
                                return (artist, title), img_url
    
    # Try handle alone (artist profile page)
    for handle in handles:
        if len(handle) >= 3:
            sc_url = f"https://soundcloud.com/{handle}"
            if sc_url not in searched:
                searched.add(sc_url)
                img_url = _fetch_soundcloud_cover(sc_url)
                if img_url:
                    return (artist, title), img_url
    
    # Try to derive track slug from the part before the first ' - ' in filename
    if ' - ' in filename:
        before_dash = filename.split(' - ')[0].strip()
        # Clean it: make lowercase, replace spaces and punctuation with dashes
        track_slug_candidate = re.sub(r'[^\w]+', '-', before_dash).lower().strip('-')
        if track_slug_candidate:
            for handle in handles:
                if len(handle) >= 3:
                    for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                        sc_url = f"https://soundcloud.com/{handle}/{track_slug_candidate}{suffix}"
                        if sc_url not in searched:
                            searched.add(sc_url)
                            img_url = _fetch_soundcloud_cover(sc_url)
                            if img_url:
                                return (artist, title), img_url
    
    # If we have artist from metadata but no handles in filename, try artist name variations
    if artist and not handles:
        # Generate potential SoundCloud handles from the artist name
        potential_handles = []
        artist_clean = NON_WORD_RE.sub('', artist).lower()
        if len(artist_clean) >= 3:
            potential_handles.append(artist_clean)
        
        # Add common variations that might be used on SoundCloud
        artist_lower = artist.lower()
        variations = ['', '_dj', '_official', '_music', '_records', '_label', '_prod', '_producer']
        for base in [artist_clean] + [artist_lower.replace(' ', '')]:
            for suffix in variations:
                handle = base + suffix
                if len(handle) >= 3 and handle not in potential_handles:
                    potential_handles.append(handle)
        
        # Also try without spaces, with underscores
        no_space = artist.lower().replace(' ', '')
        if len(no_space) >= 3 and no_space not in potential_handles:
            potential_handles.append(no_space)
            for suffix in ['_dj', '_official', '_music']:
                handle = no_space + suffix
                if len(handle) >= 3 and handle not in potential_handles:
                    potential_handles.append(handle)
        
        # Try these potential handles
        for handle in potential_handles:
            if len(handle) >= 3:
                # Try the handle as a profile page
                sc_url = f"https://soundcloud.com/{handle}"
                if sc_url not in searched:
                    searched.add(sc_url)
                    img_url = _fetch_soundcloud_cover(sc_url)
                    if img_url:
                        return (artist, title), img_url
                
                # Try combinations with track base
                for slug in [f"{artist_slug}-{track_base}", f"{track_base}"]:
                    slug = MULTI_DASH_RE.sub('-', slug).strip('-')
                    if slug and len(slug) >= 3:
                        for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                            full_slug = f"{slug}{suffix}"
                            sc_url = f"https://soundcloud.com/{handle}/{full_slug}"
                            if sc_url not in searched:
                                searched.add(sc_url)
                                img_url = _fetch_soundcloud_cover(sc_url)
                                if img_url:
                                    return (artist, title), img_url
    
    # If no handles found in filename, try artist-derived handles (original logic)
    if not handles and (artist or title):
        potential_handles = []
        if artist:
            artist_clean = NON_WORD_RE.sub('', artist).lower()
            if len(artist_clean) >= 3:
                potential_handles.append(artist_clean)
            parts = artist.split()
            for part in parts:
                part_clean = NON_WORD_RE.sub('', part).lower()
                if len(part_clean) >= 4:
                    potential_handles.append(part_clean)
        
        for handle in potential_handles:
            for slug in [f"{artist_slug}-{track_base}", f"{track_base}"]:
                slug = MULTI_DASH_RE.sub('-', slug).strip('-')
                if slug and len(slug) >= 3:
                    for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                        full_slug = f"{slug}{suffix}"
                        sc_url = f"https://soundcloud.com/{handle}/{full_slug}"
                        if sc_url not in searched:
                            searched.add(sc_url)
                            img_url = _fetch_soundcloud_cover(sc_url)
                            if img_url:
                                return (artist, title), img_url
    
    # If still no handles, try common handles
    if not handles and (artist or title):
        common_handles = ['gsfreedls', 'freedldownload', 'freedownload', 'free download', 'mp3', 'zippyshare', 'mediafire', 'downloadfree', 'freedls']
        for slug in [f"{artist_slug}-{track_base}", f"{track_base}"]:
            slug = MULTI_DASH_RE.sub('-', slug).strip('-')
            if slug and len(slug) >= 3:
                for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                    for handle in common_handles:
                        sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                        if sc_url not in searched:
                            searched.add(sc_url)
                            img_url = _fetch_soundcloud_cover(sc_url)
                            if img_url:
                                return (artist, title), img_url
    
    return None, None


def search_all_sources(artist: str, title: str, filename: str = "") -> Tuple[Dict[str, Any], Optional[str]]:
    """Search all online sources for track metadata and cover art.
    Returns: (metadata dict, cover_url)
    """
    result_metadata: Dict[str, Any] = {}
    cover_url: Optional[str] = None
    
    if not artist and not title:
        return result_metadata, cover_url
    
    sources = [
        ("Deezer", lambda a, t: search_deezer_cover(a, t)),
        ("Bandcamp", lambda a, t: search_bandcamp_cover(a, t)),
        ("SoundCloud", lambda a, t: search_soundcloud_web(a, t, filename)[1]),
    ]
    
    for source_name, search_func in sources:
        try:
            found_cover: Optional[str] = search_func(artist, title)
            if found_cover and not cover_url:
                cover_url = found_cover
                logger.info(f"  {source_name} cover found")
        except Exception as e:
            logger.warning(f"  {source_name} search failed: {e}")
    
    return result_metadata, cover_url


def extract_metadata_from_filename(filename: str) -> Dict[str, Any]:
    """Extract artist and title from filename with improved robustness."""
    name = Path(filename).stem.strip()
    
    # Define descriptive terms that should NOT be treated as artists even if found in brackets
    descriptive_terms: Set[str] = {
        'remix', 'edit', 'mix', 'flip', 'rework', 'cover', 'feat', 'ft', 'featuring',
        'radio', 'clean', 'explicit', 'instrumental', 'acappella', 'dub', 'master',
        'extended', 'version', 'cut', 'mixshow', 'club', 'original', 'live', 'draft',
    }
    
    # Handle leading bracketed terms
    leading_bracket_match = re.match(r'\[([^\]]+)\]\s+(.+)', name)
    if leading_bracket_match:
        bracket_content = leading_bracket_match.group(1).strip()
        remaining_title = leading_bracket_match.group(2).strip()
        
        # Check if bracket content should be treated as artist handle
        if _is_valid_artist_handle(bracket_content, descriptive_terms):
            return bracket_content, remaining_title
        # Otherwise fall through to normal processing
    
    # Handle trailing bracketed terms
    trailing_bracket_match = re.match(r'(.+)\s+\[([^\]]+)\]', name)
    if trailing_bracket_match:
        title_part = trailing_bracket_match.group(1).strip()
        bracket_content = trailing_bracket_match.group(2).strip()
        
        # Only treat bracketed content as artist if there's also a separator in the filename
        # This prevents treating "Track [username].wav" as artist="username", title="Track"
        has_separator = any(sep in name for sep in [' - ', ' – ', ' — ', '_', '.'])
        
        # Check if bracket content should be treated as artist handle
        if has_separator and _is_valid_artist_handle(bracket_content, descriptive_terms):
            return bracket_content, title_part
        # Otherwise fall through to normal processing
    
    # Handle separators
    return _parse_separators(name, descriptive_terms)


def _is_valid_artist_handle(potential_artist, descriptive_terms):
    """Check if a string looks like a valid artist handle (not a descriptive term)."""
    if not potential_artist:
        return False
    if potential_artist.isdigit():
        return False
    if len(potential_artist) < 2:
        return False
    if potential_artist.lower() in descriptive_terms:
        return False
    if re.search(r'(?:remix|edit|mix|flip|rework|cover|feat|ft\.|featuring|radio|clean|explicit|instrumental|acappella|dub|master|extended|version|cut|mixshow|club|original|mix|edit|remix|edit)', potential_artist, re.IGNORECASE):
        return False
    return True


def _parse_separators(name, descriptive_terms):
    """Parse filename using separator logic."""
    # Definite separators (with spaces)
    separators = [' - ', ' – ', ' — ']
    # Flexible separators (need context check)
    flexible_separators = ['_', '.']
    
    # Check definite separators first
    for sep in separators:
        if sep in name:
            parts = name.split(sep, 1)
            artist = parts[0].strip()
            title = parts[1].strip()
            
            # Check if artist part looks like a track number
            if _looks_like_track_number(artist):
                # Try to get artist from title part
                for sep2 in separators + flexible_separators:
                    if sep2 in title:
                        parts2 = title.split(sep2, 1)
                        artist = parts2[0].strip()
                        title = parts2[1].strip()
                        break
                else:
                    # No second separator found, treat title part as title only
                    artist = ''
                    title = name.strip()
            return artist, title
    
    # Check flexible separators with more context
    for sep in flexible_separators:
        if sep in name:
            parts = name.split(sep, 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                title = parts[1].strip()
                
                # Validate both parts look reasonable
                if _is_valid_filename_part(artist, descriptive_terms) and _is_valid_filename_part(title, descriptive_terms):
                    # Additional check for artist being track number
                    if _looks_like_track_number(artist):
                        # Try to get artist from title part
                        for sep2 in separators + flexible_separators:
                            if sep2 in title:
                                parts2 = title.split(sep2, 1)
                                artist = parts2[0].strip()
                                title = parts2[1].strip()
                                break
                        else:
                            # No second separator found, treat title part as title only
                            artist = ''
                            title = name.strip()
                    return artist, title
    
    return '', name.strip()


def _looks_like_track_number(text):
    """Check if text looks like a track number."""
    return bool(re.match(r'^\d+(\s*(st|nd|rd|th))?$', text))


def _is_valid_filename_part(text, descriptive_terms):
    """Check if a filename part looks reasonable (not just numbers or descriptive terms)."""
    if not text:
        return False
    if text.lower() in descriptive_terms:
        return False
    if len(text) < 2:
        return False
    # Check if it contains vowels or is reasonable length
    if not (any(c in 'aeiouAEIOU' for c in text) or len(text) >= 3):
        return False
    # Extra restriction: if the part is all uppercase and contains lowercase with underscores,
    # it's likely a single title like "ATTRACTION_DEMO_G_125"
    if text.isupper() and '_' in text and any(c.islower() for c in text):
        return False
    return True


def find_local_cover(wav_path):
    """Find cover art (PNG/JPG) in the same directory as the WAV file.
    
    Strategy:
    1. Look for cover.png/cover.jpg in same directory
    2. Look for any image file matching the base name pattern
    """
    wav_dir = Path(wav_path).parent.resolve()
    base_name = Path(wav_path).stem
    
    patterns = [
        wav_dir / "cover.png",
        wav_dir / "cover.jpg",
        wav_dir / "cover.jpeg",
        wav_dir / f"{base_name}.png",
        wav_dir / f"{base_name}.jpg",
        wav_dir / f"{base_name}.jpeg",
    ]
    
    for pattern in patterns:
        if pattern.exists():
            return str(pattern)
    
    for ext in ['*.png', '*.jpg', '*.jpeg']:
        for img in wav_dir.glob(ext):
            if img.exists():
                return str(img)
    
    return None


def download_cover(url, output_path):
    """Download cover art from URL."""
    cmd = f'curl -sL "{url}" -o "{output_path}"'
    success, _, _ = run_cmd(cmd, timeout=30)
    return success


def process_cover(cover_path, output_path):
    """Process cover art to 600x600."""
    cmd = f'ffmpeg -y -i "{cover_path}" -vf "scale=600:600:force_original_aspect_ratio=decrease,pad=600:600:(ow-iw)/2:(oh-ih)/2" -frames:v 1 -q:v 2 "{output_path}" 2>/dev/null'
    success, _, _ = run_cmd(cmd)
    return success


def encode_audio(wav_path, output_path, metadata, gain_db, fmt):
    """Encode WAV to audio format (MP3 or M4A) with metadata."""
    if fmt == 'mp3':
        codec = 'libmp3lame'
        extra_args = ''
    elif fmt == 'm4a':
        codec = 'aac'
        extra_args = '-movflags +use_metadata_tags'
    else:
        raise ValueError(f"Unsupported format: {fmt}")
    
    cmd = f'ffmpeg -y -i "{wav_path}" -map 0:a -af "volume={gain_db}dB" -c:a {codec} -b:a 320k'
    for key, value in metadata.items():
        if value and isinstance(value, str):
            cmd += f' -metadata {key}="{value}"'
    if extra_args:
        cmd += f' {extra_args}'
    cmd += f' "{output_path}"'
    print(f"DEBUG encode_audio: running cmd: {cmd}", flush=True)
    success, stdout, stderr = run_cmd(cmd)
    print(f"DEBUG encode_audio: success={success}, stderr={stderr[:200] if stderr else ''}", flush=True)
    return success


def embed_cover(input_path, cover_path, final_path, fmt):
    """Embed cover art into audio file (MP3 or M4A)."""
    if fmt == 'mp3':
        cmd = f'ffmpeg -y -i "{input_path}" -i "{cover_path}" -map 0:a -map 1:v -c:a copy -c:v copy -id3v2_version 3 -metadata:s:v title="Album cover" -metadata:s:v mimetype="image/jpeg" "{final_path}"'
    elif fmt == 'm4a':
        cmd = f'ffmpeg -y -i "{input_path}" -i "{cover_path}" -c:a copy -c:v copy -map 0:a -map 1:v -disposition:1 attached_pic "{final_path}"'
    else:
        raise ValueError(f"Unsupported format: {fmt}")
    
    success, _, _ = run_cmd(cmd)
    return success


def verify_output(output_path, fmt) -> tuple[bool, dict[str, bool] | str]:
    """Verify output file."""
    cmd = f'ffprobe -v quiet -show_format -show_streams "{output_path}"'
    success, stdout, _ = run_cmd(cmd)
    if not success:
        return False, "Failed to read file"
    
    if fmt == 'mp3':
        has_codec = 'codec_name=mp3' in stdout or 'codec_name=libmp3lame' in stdout
    else:
        has_codec = 'codec_name=aac' in stdout
    has_cover = 'attached_pic=1' in stdout or 'stream_tags' in stdout
    info: dict[str, bool] = {fmt: has_codec, "cover": has_cover}
    return True, info


def save_result_json(wav_path, metadata, loudness, output_name, success, has_cover=False, fmt='mp3'):
    """Save conversion result to JSON file."""
    result = {
        "source_wav": str(wav_path),
        f"output_{fmt}": output_name if success else None,
        "success": success,
        "metadata": metadata,
        "loudness": loudness,
        "has_cover": has_cover
    }
    json_path = Path(wav_path).with_suffix('.json')
    with open(json_path, 'w') as f:
        json.dump(result, f, indent=2)


def convert_file(wav_path: str, fmt: str = 'mp3') -> Tuple[bool, Optional[str]]:
    """Convert a single WAV file to MP3 or M4A."""
    original_wav_path = wav_path
    temp_dir = None
    try:
        path_obj = Path(wav_path)
        ascii_stem = to_ascii_filename(path_obj.stem)
        # Always use ASCII filename for processing to avoid Unicode issues with ffmpeg/ffprobe
        if ascii_stem:
            # Create ASCII filename in temporary directory
            import tempfile
            temp_dir = tempfile.mkdtemp(prefix='wav2aac_')
            ascii_filename_path = Path(temp_dir) / (ascii_stem + path_obj.suffix)
            # Copy file to temporary location with ASCII name
            import shutil
            shutil.copy2(original_wav_path, ascii_filename_path)
            wav_path = str(ascii_filename_path)
            if ascii_stem != path_obj.stem:
                logger.info(f"  Using ASCII filename: {ascii_filename_path.name}")
            else:
                logger.info(f"  Using filename: {ascii_filename_path.name} (already ASCII)")
        else:
            # Fallback to original filename if ASCII conversion results in empty string
            wav_path = str(path_obj)
            logger.info(f"  Using filename: {Path(wav_path).name}")
    except Exception as e:
        logger.warning(f"  Could not create ASCII filename: {e}")
        # Fall back to original path
        wav_path = str(original_wav_path)
        # Clean up temp directory on failure
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir = None
    
    wav_path = str(wav_path)
    base_name = Path(wav_path).stem
    output_name = base_name + f'.{fmt}'
    
    file_hash = hash(wav_path) % 1000000
    temp_cover = f'cover_{file_hash}.jpg'
    temp_output = f'output_{file_hash}.{fmt}'
    
    loudness = analyze_loudness(wav_path)
    if not loudness:
        logger.error(f"  Loudness analysis failed")
        return False, None
    logger.info(f"  Loudness: {loudness.get('input_i', 'N/A')} LUFS, True Peak: {loudness.get('input_tp', 'N/A')} dB")
    
    input_tp = float(loudness.get('input_tp', -10))
    gain_db = min(0, -0.1 - input_tp)
    
    metadata = extract_metadata(wav_path)
    logger.debug(f"  Metadata: {metadata}")
    
    search_artist = metadata.get('artist', '')
    search_title = metadata.get('title', '')
    
    # If we don't have both artist and title from tags, try online lookup
    if not (search_artist and search_title):
        online_artist, online_title = lookup_online_metadata(base_name)
        if online_artist and online_title:
            search_artist, search_title = online_artist, online_title
            metadata['artist'] = search_artist
            metadata['title'] = search_title
            logger.info(f"  Metadata: found via online lookup → {search_artist} – {search_title}")
        else:
            # Fallback to filename parser
            artist, title = extract_metadata_from_filename(base_name)
            if not search_artist:
                search_artist = artist
                metadata['artist'] = artist
            if not search_title:
                search_title = title
                metadata['title'] = title
            logger.info(f"  Metadata: derived from filename → {search_artist} – {search_title}")
    
    metadata = {k: v for k, v in metadata.items() if isinstance(v, str)}
    
    cover_path = None
    web_metadata = None
    
    cmd = f'ffmpeg -y -i "{wav_path}" -map 0:v -map -0:a -c:v copy "{temp_cover}" 2>/dev/null'
    success, _, _ = run_cmd(cmd)
    if Path(temp_cover).exists():
        cover_path = temp_cover
        logger.info(f"  Cover: Extracted from source")
    else:
        local_cover = find_local_cover(wav_path)
        if local_cover:
            if local_cover.lower().endswith('.png'):
                success, _, _ = run_cmd(f'ffmpeg -y -i "{local_cover}" "{temp_cover}" 2>/dev/null')
                if success and Path(temp_cover).exists():
                    cover_path = temp_cover
            else:
                cover_path = local_cover
            logger.info(f"  Cover: Found local file")
        else:
            search_title_clean = clean_title_for_search(search_title)
            
            cover_url = search_deezer_cover(search_artist, search_title_clean)
            if cover_url:
                download_cover(cover_url, temp_cover)
                logger.info(f"  Cover: Downloaded from Deezer")
            elif search_artist or search_title:
                cover_url = search_bandcamp_cover(search_artist, search_title_clean)
                if cover_url:
                    download_cover(cover_url, temp_cover)
                    logger.info(f"  Cover: Downloaded from Bandcamp")
                else:
                    web_metadata, cover_url = search_soundcloud_web(search_artist, search_title, base_name)
                    if cover_url:
                        download_cover(cover_url, temp_cover)
                        logger.info(f"  Cover: Downloaded from SoundCloud")
                        if web_metadata and not metadata.get('artist'):
                            metadata['artist'] = web_metadata[0] or ''
                        if web_metadata and not metadata.get('title'):
                            metadata['title'] = web_metadata[1] or ''
            
            if Path(temp_cover).exists():
                cover_path = temp_cover
            else:
                logger.debug(f"  Cover: Not found")
    
    success = encode_audio(wav_path, temp_output, metadata, gain_db, fmt)
    
    if not success:
        logger.error(f"  Encoding failed")
        save_result_json(wav_path, metadata, loudness, output_name, False, False, fmt)
        for f in [temp_output, temp_cover]:
            if f and Path(f).exists():
                os.remove(f)
        return False, None
    
    if cover_path and Path(cover_path).exists():
        embed_success = embed_cover(temp_output, cover_path, output_name, fmt)
        
        if embed_success:
            for f in [temp_output, temp_cover, cover_path]:
                if f and f != cover_path and Path(f).exists():
                    os.remove(f)
            if cover_path == temp_cover and Path(temp_cover).exists():
                os.remove(temp_cover)
        else:
            logger.warning(f"  Cover embedding failed, using raw file")
            os.rename(temp_output, output_name)
            if cover_path == temp_cover and Path(temp_cover).exists():
                os.remove(temp_cover)
    else:
        os.rename(temp_output, output_name)
    
    valid, result = verify_output(output_name, fmt)
    info = result if isinstance(result, dict) else {}
    if valid:
        logger.info(f"  SUCCESS: {output_name} ({fmt.upper()}: {info.get(fmt)}, Cover: {info.get('cover')})")
        # Clean up temporary directory if it was created
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        return True, output_name
    else:
        logger.error(f"  FAIL: Verification failed - {result}")
        save_result_json(wav_path, metadata, loudness, output_name, False, bool(info.get('cover')), fmt)
        # Clean up temporary directory if it was created
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        return False, None
    
    logger.info(f"  Loudness: {loudness.get('input_i', 'N/A')} LUFS, True Peak: {loudness.get('input_tp', 'N/A')} dB")
    
    input_tp = float(loudness.get('input_tp', -10))
    gain_db = min(0, -0.1 - input_tp)
    
    metadata = extract_metadata(wav_path)
    logger.debug(f"  Metadata: {metadata}")
    
    search_artist = metadata.get('artist', '')
    search_title = metadata.get('title', '')
    
    # If we don't have both artist and title from tags, try online lookup
    if not (search_artist and search_title):
        online_artist, online_title = lookup_online_metadata(base_name)
        if online_artist and online_title:
            search_artist, search_title = online_artist, online_title
            metadata['artist'] = search_artist
            metadata['title'] = search_title
            logger.info(f"  Metadata: found via online lookup → {search_artist} – {search_title}")
        else:
            # Fallback to filename parser
            artist, title = extract_metadata_from_filename(base_name)
            if not search_artist:
                search_artist = artist
                metadata['artist'] = artist
            if not search_title:
                search_title = title
                metadata['title'] = title
            logger.info(f"  Metadata: derived from filename → {search_artist} – {search_title}")
    
    metadata = {k: v for k, v in metadata.items() if isinstance(v, str)}
    
    cover_path = None
    web_metadata = None
    
    cmd = f'ffmpeg -y -i "{wav_path}" -map 0:v -map -0:a -c:v copy "{temp_cover}" 2>/dev/null'
    success, _, _ = run_cmd(cmd)
    if Path(temp_cover).exists():
        cover_path = temp_cover
        logger.info(f"  Cover: Extracted from source")
    else:
        local_cover = find_local_cover(wav_path)
        if local_cover:
            if local_cover.lower().endswith('.png'):
                success, _, _ = run_cmd(f'ffmpeg -y -i "{local_cover}" "{temp_cover}" 2>/dev/null')
                if success and Path(temp_cover).exists():
                    cover_path = temp_cover
            else:
                cover_path = local_cover
            logger.info(f"  Cover: Found local file")
        else:
            search_title_clean = clean_title_for_search(search_title)
            
            cover_url = search_deezer_cover(search_artist, search_title_clean)
            if cover_url:
                download_cover(cover_url, temp_cover)
                logger.info(f"  Cover: Downloaded from Deezer")
            elif search_artist or search_title:
                cover_url = search_bandcamp_cover(search_artist, search_title_clean)
                if cover_url:
                    download_cover(cover_url, temp_cover)
                    logger.info(f"  Cover: Downloaded from Bandcamp")
                else:
                    web_metadata, cover_url = search_soundcloud_web(search_artist, search_title, base_name)
                    if cover_url:
                        download_cover(cover_url, temp_cover)
                        logger.info(f"  Cover: Downloaded from SoundCloud")
                        if web_metadata and not metadata.get('artist'):
                            metadata['artist'] = web_metadata[0] or ''
                        if web_metadata and not metadata.get('title'):
                            metadata['title'] = web_metadata[1] or ''
            
            if Path(temp_cover).exists():
                cover_path = temp_cover
            else:
                logger.debug(f"  Cover: Not found")
    
    success = encode_audio(wav_path, temp_output, metadata, gain_db, fmt)
    
    if not success:
        logger.error(f"  Encoding failed")
        save_result_json(wav_path, metadata, loudness, output_name, False, False, fmt)
        for f in [temp_output, temp_cover]:
            if f and Path(f).exists():
                os.remove(f)
        return False, None
    
    if cover_path and Path(cover_path).exists():
        embed_success = embed_cover(temp_output, cover_path, output_name, fmt)
        
        if embed_success:
            for f in [temp_output, temp_cover, cover_path]:
                if f and f != cover_path and Path(f).exists():
                    os.remove(f)
            if cover_path == temp_cover and Path(temp_cover).exists():
                os.remove(temp_cover)
        else:
            logger.warning(f"  Cover embedding failed, using raw file")
            os.rename(temp_output, output_name)
            if cover_path == temp_cover and Path(temp_cover).exists():
                os.remove(temp_cover)
    else:
        os.rename(temp_output, output_name)
    
    valid, result = verify_output(output_name, fmt)
    info = result if isinstance(result, dict) else {}
    if valid:
        logger.info(f"  SUCCESS: {output_name} ({fmt.upper()}: {info.get(fmt)}, Cover: {info.get('cover')})")
        # Clean up temporary directory if it was created
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        return True, output_name
    else:
        logger.error(f"  FAIL: Verification failed - {result}")
        save_result_json(wav_path, metadata, loudness, output_name, False, bool(info.get('cover')), fmt)
        # Clean up temporary directory if it was created
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        return False, None


def _lookup_itunes(term: str):
    """Lookup track on iTunes Search API."""
    if not term:
        return None, None
    term_quoted = quote(term)
    url = f"https://itunes.apple.com/search?term={term_quoted}&entity=song&limit=5"
    content = fetch_url(url)
    if not content:
        return None, None
    try:
        data = json.loads(content)
        for track in data.get("results", []):
            track_name = track.get("trackName", "")
            # We want an exact match on track name (case-insensitive) to avoid false positives
            if track_name.lower() == term.lower():
                artist = track.get("artistName")
                return artist, track_name
        # If no exact match, take the first result that has both artist and track name
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
    # MusicBrainz uses a different query format
    query = f'recording:"{term}"'
    url = f"https://musicbrainz.org/ws/2/recording/?query={quote(query)}&fmt=json&limit=5"
    content = fetch_url(url)
    if not content:
        return None, None
    try:
        data = json.loads(content)
        for recording in data.get("recordings", []):
            title = recording.get("title")
            artist_credit = recording.get("artist-credit", [])
            artist = None
            if artist_credit:
                # Extract artist names from the artist-credit
                artist_names = []
                for ac in artist_credit:
                    if isinstance(ac, dict) and 'artist' in ac:
                        artist_names.append(ac['artist'].get('name'))
                if artist_names:
                    artist = ", ".join(artist_names)
            if artist and title:
                return artist, title
        # If no exact match, take the first recording that has both
        for recording in data.get("recordings", []):
            title = recording.get("title")
            artist_credit = recording.get("artist-credit", [])
            artist = None
            if artist_credit:
                artist_names = []
                for ac in artist_credit:
                    if isinstance(ac, dict) and 'artist' in ac:
                        artist_names.append(ac['artist'].get('name'))
                if artist_names:
                    artist = ", ".join(artist_names)
            if artist and title:
                return artist, title
    except (json.JSONDecodeError, KeyError):
        pass
    return None, None


def lookup_online_metadata(base_name: str):
    """
    Try iTunes first, then MusicBrainz.
    Returns (artist, title) or (None, None) if nothing usable is found.
    """
    artist, title = _lookup_itunes(base_name)
    if artist and title:
        return artist, title
    return _lookup_musicbrainz(base_name)


def _convert_file_wrapper(args):
    """Wrapper for parallel processing."""
    wav_path, fmt = args
    success, output = convert_file(wav_path, fmt)
    return (wav_path, success, output)


def convert_batch(file_paths, fmt='mp3', parallel=True, max_workers=5):
    """Convert multiple WAV files.
    
    Args:
        file_paths: List of WAV file paths
        fmt: Output format ('mp3' or 'm4a')
        parallel: Use parallel processing (default: True)
        max_workers: Max parallel processes (default: 5)
    
    Returns:
        List of (wav_path, success, output) tuples
    """
    results = []
    
    if not parallel or len(file_paths) < 4:
        for wav_path in file_paths:
            results.append(_convert_file_wrapper((wav_path, fmt)))
        return results
    
    logger.info(f"Converting {len(file_paths)} files in parallel (max {max_workers} workers)...")
    
    with ProcessPoolExecutor(max_workers=min(max_workers, len(file_paths))) as executor:
        futures = {executor.submit(_convert_file_wrapper, (fp, fmt)): fp for fp in file_paths}
        for future in as_completed(futures):
            results.append(future.result())
    
    return results


def parse_args():
    """Parse command line arguments."""
    # Load config first to use as defaults
    config = load_config()
    
    parser = argparse.ArgumentParser(
        description='WAV to MP3/M4A converter with loudness normalization and cover art.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python3 convert.py song.wav                      # Convert to MP3 (default)
  python3 convert.py --m4a song.wav               # Convert to M4A
  python3 convert.py --format m4a song.wav         # Convert to M4A (long form)
  python3 convert.py --mp3 *.wav                   # Batch convert to MP3
  python3 convert.py --m4a folder/*.wav            # Batch convert to M4A
'''
    )
    format_group = parser.add_mutually_exclusive_group()
    format_group.add_argument('--mp3', action='store_true', help='Output MP3 format (default)')
    format_group.add_argument('--m4a', action='store_true', help='Output M4A/AAC format')
    parser.add_argument('--format', choices=['mp3', 'm4a'], default=config['output_format'],
                       help='Output format (default: mp3)')
    parser.add_argument('--max-workers', type=int, default=config['max_parallel_processes'],
                       help=f'Max parallel processes (default: {config["max_parallel_processes"]})')
    parser.add_argument('--no-loudnorm', action='store_false', dest='loudnorm',
                       default=config['loudnorm'],
                       help='Disable loudness normalization')
    parser.add_argument('--no-cover', action='store_false', dest='embed_cover',
                       default=config['embed_cover'],
                       help='Disable cover art embedding')
    parser.add_argument('--retry-attempts', type=int, default=config['retry_attempts'],
                       help=f'Retry attempts for failed operations (default: {config["retry_attempts"]})')
    parser.add_argument('--timeout', type=int, default=config['timeout_seconds'],
                       help=f'Timeout in seconds for operations (default: {config["timeout_seconds"]})')
    parser.add_argument('files', nargs='+', help='WAV file(s) to convert')
    return parser.parse_args()


if __name__ == '__main__':
    # Configure logging to output to stdout with level and message
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    args = parse_args()
    
    wav_files = [f for f in args.files if f.endswith('.wav') or f.endswith('.WAV')]
    
    if not wav_files:
        logger.error("Error: No WAV files found")
        sys.exit(1)
    
    if args.m4a:
        fmt = 'm4a'
    else:
        fmt = args.format
    
    logger.info(f"Output format: {fmt.upper()}")
    
    if len(wav_files) == 1:
        success, output = convert_file(wav_files[0], fmt)
        sys.exit(0 if success else 1)
    
    results = convert_batch(wav_files, fmt, parallel=(len(wav_files) >= 4), max_workers=args.max_workers)
    
    success_count = sum(1 for _, s, _ in results if s)
    logger.info(f"\nBatch complete: {success_count}/{len(results)} succeeded")
    
    sys.exit(0 if success_count == len(results) else 1)
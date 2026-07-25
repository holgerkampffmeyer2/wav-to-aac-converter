#!/usr/bin/env python3
"""Utility functions, constants, and helper code for wav-to-aac-converter."""

import re
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Callable, Tuple, Optional
from functools import wraps

logger = logging.getLogger(__name__)


def get_config_dir() -> Path:
    """Return config directory: ~/.config/audioconvert/ for bundles, project root for scripts."""
    import sys
    if getattr(sys, 'frozen', False):
        config_dir = Path.home() / '.config' / 'audioconvert'
    else:
        config_dir = Path(__file__).parent.parent
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

# === Environment ===
def _load_env() -> dict:
    """Load environment variables from .env file in config directory."""
    env_path = get_config_dir() / '.env'
    env_vars = {}
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, _, value = line.partition('=')
                        env_vars[key.strip()] = value.strip()
    return env_vars

_env = _load_env()
SOUNDCLOUD_CLIENT_ID: str = _env.get('SOUNDCLOUD_CLIENT_ID', '')

# === Regex Patterns ===
OG_IMAGE_RE = re.compile(r'"og:image"\s+content="([^"]+)"')
BANDCAMP_URL_RE = re.compile(r'https?://[^\s"\'<>]*\.bandcamp\.com/(?:track|album)/[^\s"\'<>]*')
NON_WORD_RE = re.compile(r'[^\w]')
MULTI_DASH_RE = re.compile(r'-+')
BRACKET_CLEANUP_RE = re.compile(r'\([^)]*\)|\[[^\]]*\]')
REMIX_KEYWORDS_RE = re.compile(
    r'(?:remix|edit|mix|flip|rework|cover|feat|ft\.|featuring|radio|clean|explicit|instrumental|acappella|bootleg)',
    re.IGNORECASE
)

# === User Agent ===
USER_AGENT = '"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"'

# === Audio Settings ===
DEFAULT_BITRATE = "320k"           # MP3/M4A bitrate
COVER_DIMENSIONS = 600              # Cover art resize dimensions

# === Timeouts (seconds) ===
DEFAULT_TIMEOUT = 15               # fetch_url default
SEARCH_TIMEOUT = 10                # API search timeouts
ENCODE_TIMEOUT = 600               # FFmpeg encoding timeout
LOUDNESS_TIMEOUT = 120             # Loudness analysis timeout

# === Retry Settings ===
RETRY_ATTEMPTS = 3                  # Default retry attempts
RETRY_DELAY = 1                    # Initial retry delay (seconds)
RETRY_BACKOFF = 2                  # Exponential backoff multiplier

# === API Endpoints ===
DEEZER_API_URL = "https://api.deezer.com/search/album?q="
MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/release/"
MUSICBRAINZ_COVER_URL = "https://coverartarchive.org/release/"
BANDCAMP_SEARCH_URL = "https://bandcamp.com/search?q="
ITUNES_SEARCH_URL = "https://itunes.apple.com/search?term="
MUSICBRAINZ_LOOKUP_URL = "https://musicbrainz.org/ws/2/recording/?query="

# === Exception Classes ===
class NetworkError(Exception):
    """Network-related errors."""
    pass

class CoverSearchError(Exception):
    """Cover art search failures."""
    pass

class EncodingError(Exception):
    """Audio encoding failures."""
    pass


def run_cmd(cmd: str, capture_output: bool = True, timeout: int = ENCODE_TIMEOUT) -> Tuple[bool, str, str]:
    """Run shell command and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=capture_output, text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"


def retry(max_attempts: int = RETRY_ATTEMPTS, delay: int = RETRY_DELAY, backoff: int = RETRY_BACKOFF):
    """Retry decorator with exponential backoff for HTTP operations."""
    def decorator(func: Callable):
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
                    import time
                    sleep_time = delay * (backoff ** attempt)
                    time.sleep(sleep_time)
            return None
        return wrapper
    return decorator


def load_config() -> Dict[str, Any]:
    """Load configuration from config.json file."""
    from pathlib import Path
    config_path = get_config_dir() / 'config.json'
    default_config: Dict[str, Any] = {
        "output_format": "mp3",
        "max_parallel_processes": 5,
        "loudnorm": True,
        "embed_cover": True,
        "retry_attempts": 3,
        "timeout_seconds": 30,
        "fuzzy_threshold": 0.8,
        "soundcloud_confidence_threshold": 0.6,
        "metadata": {
            "enabled": True,
            "offline": False,
            "sources": ["soundcloud", "itunes", "deezer", "bandcamp", "musicbrainz"],
            "fallback_to_filename": True,
            "enrich_tags": ["label", "genre", "album", "year", "track_number"],
            "label_source_tag": "label"
        }
    }
    try:
        if config_path.exists():
            import json
            with open(config_path, 'r') as f:
                config = json.load(f)
                if config:
                    return config
                else:
                    return default_config
        else:
            return default_config
    except Exception as e:
        logger.warning(f"Could not load config file: {e}")
        return default_config


def to_ascii_filename(filename: str) -> str:
    """Convert Unicode filename to ASCII equivalent."""
    import unicodedata
    # Normalize Unicode characters (decompose accents, etc.)
    normalized = unicodedata.normalize('NFKD', filename)
    # Remove non-ASCII characters
    ascii_only = normalized.encode('ascii', 'ignore').decode('ascii')
    # Clean up any extra spaces or special characters that might result
    ascii_only = re.sub(r'[^\w\s\-_.()\[\]]', '', ascii_only)
    ascii_only = re.sub(r'\s+', ' ', ascii_only).strip()
    return ascii_only


def clean_title_for_search(title: str) -> str:
    """Remove remix/edit/etc. info from title for cover art search.
    
    Removes any bracket (with nested content) if it contains remix/edit/etc. keywords.
    """
    if not title:
        return ""
    
    def find_matching_paren(text: str, start: int) -> int:
        """Find the closing paren/bracket for the opener at start."""
        opener = text[start]
        closer = ']' if opener == '[' else ')'
        depth = 1
        i = start + 1
        while i < len(text) and depth > 0:
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
            i += 1
        return i - 1 if depth == 0 else -1
    
    def strip_brackets(text: str) -> str:
        """Remove bracketed content that contains remix/edit keywords."""
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


def calculate_match_confidence(expected_artist: str, expected_title: str, found_track_title: str) -> float:
    """Calculate confidence (0.0–1.0) that found_track_title matches expected artist/title.
    
    Uses word-level containment for multi-word names (e.g. "Emmanuel Callejas Erick Cz"
    appears in "Emmanuel Callejas, Erick Cz - The Rub 212 [SLFREEDL062]") and falls
    back to SequenceMatcher fuzzy ratio for single-word or partial matches.
    """
    from difflib import SequenceMatcher

    if not found_track_title:
        return 0.0

    found_lower = found_track_title.lower()
    expected_artist = (expected_artist or '').strip()
    expected_title = (expected_title or '').strip()

    def _score(expected: str) -> float:
        if not expected:
            return 1.0
        expected_lower = expected.lower()
        words = expected_lower.split()
        if len(words) >= 2:
            matches = sum(1 for w in words if w in found_lower)
            word_score = matches / len(words)
        else:
            word_score = 1.0 if expected_lower in found_lower else 0.0
        fuzzy = SequenceMatcher(None, expected_lower, found_lower).ratio()
        return max(word_score, fuzzy)

    scores = [_score(expected_artist), _score(expected_title)]
    return (scores[0] + scores[1]) / 2


def validate_soundcloud_client_id() -> bool:
    """Validate SoundCloud client ID with a lightweight API probe.

    Returns True if the ID is valid, False otherwise.
    Logs a warning with remediation steps when invalid.
    """
    import json

    if not SOUNDCLOUD_CLIENT_ID:
        return False

    url = (f"https://api-v2.soundcloud.com/search/tracks"
           f"?q=test&client_id={SOUNDCLOUD_CLIENT_ID}&limit=1")
    content = fetch_url(url, timeout=10)
    if not content:
        logger.warning(
            "SoundCloud client ID validation failed — no response. "
            "SoundCloud metadata/cover search will be unavailable."
        )
        return False

    try:
        data = json.loads(content)
        if 'collection' in data:
            return True
        if data.get('errors'):
            logger.warning(
                "SoundCloud client ID is invalid or expired (API returned errors). "
                "To fix: open SoundCloud in your browser, play a track, open DevTools "
                "(F12) → Network tab, reload, find a request with '?client_id=', "
                "copy the client_id value and update .env: "
                "SOUNDCLOUD_CLIENT_ID=<new_id>"
            )
            return False
    except json.JSONDecodeError:
        pass

    logger.warning(
        "SoundCloud client ID validation failed — unexpected response. "
        "SoundCloud metadata/cover search will be unavailable."
    )
    return False

def search_soundcloud_api(query: str, limit: int = 5) -> list:
    """Search SoundCloud via API v2. Returns list of track result dicts."""
    import json
    from urllib.parse import quote

    if not SOUNDCLOUD_CLIENT_ID:
        logger.warning("No SOUNDCLOUD_CLIENT_ID in .env — SoundCloud search disabled")
        return []

    url = (f"https://api-v2.soundcloud.com/search/tracks"
           f"?q={quote(query)}&client_id={SOUNDCLOUD_CLIENT_ID}&limit={limit}")
    content = fetch_url(url, timeout=SEARCH_TIMEOUT)
    if not content:
        return []

    try:
        data = json.loads(content)
        return data.get('collection', [])
    except json.JSONDecodeError:
        return []


def try_soundcloud_api_result(track: dict, expected_artist: str, expected_title: str,
                              config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Validate a SoundCloud API track result with confidence scoring.

    Returns enriched dict with title, artist, thumbnail, url, confidence.
    """
    if config is None:
        config = load_config()

    api_title = track.get('title', '')
    uploader = track.get('user', {}).get('username', '') if track.get('user') else ''
    artwork = track.get('artwork_url', '')
    permalink = track.get('permalink_url', '')

    if not api_title:
        return None

    confidence = calculate_match_confidence(expected_artist, expected_title, api_title)
    threshold = config.get('soundcloud_confidence_threshold', 0.6)

    if confidence >= threshold:
        # Upgrade artwork to t500x500 for higher resolution
        if artwork and '-large.jpg' in artwork:
            artwork = artwork.replace('-large.jpg', '-t500x500.jpg')
        return {
            'title': api_title,
            'artist': uploader,
            'thumbnail': artwork,
            'url': permalink,
            'confidence': confidence,
        }

    logger.debug(f"  SoundCloud API confidence {confidence:.2f} < {threshold}")
    return None


def fetch_url(url: str, timeout: int = DEFAULT_TIMEOUT, headers: Optional[Dict[str, str]] = None, method: str = 'GET', data: Optional[Dict[str, str]] = None) -> str:
    """Fetch URL content with configurable options."""
    from typing import Dict
    from urllib.parse import urlparse
    
    # Validate URL before processing
    try:
        parsed = urlparse(url)
        if not parsed.scheme or parsed.scheme not in ('http', 'https'):
            logger.warning(f"Invalid URL scheme: {parsed.scheme}")
            return ""
        if not parsed.netloc:
            logger.warning("Invalid URL: missing netloc")
            return ""
    except Exception as e:
        logger.warning(f"URL parse error: {e}")
        return ""
    
    default_headers: Dict[str, str] = {
        'User-Agent': USER_AGENT.strip('"'),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }
    
    if headers:
        default_headers.update(headers)
    
    curl_cmd = ['curl', '-sL']
    
    for key, value in default_headers.items():
        curl_cmd.extend(['-H', f'{key}: "{value}"'])
    
    curl_cmd.extend(['--max-time', str(timeout)])
    
    if method.upper() == 'POST' and data:
        curl_cmd.extend(['-X', 'POST'])
        form_data = []
        for key, value in data.items():
            escaped_value = value.replace('"', '\\"')
            form_data.extend(['-d', f'{key}={escaped_value}'])
        curl_cmd.extend(form_data)
    
    curl_cmd.append(f'"{url}"')
    
    success, stdout, _ = run_cmd(' '.join(curl_cmd), timeout=timeout + 5)
    return stdout if success else ""
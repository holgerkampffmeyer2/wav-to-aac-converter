#!/usr/bin/env python3
"""Utility functions, constants, and helper code for wav-to-aac-converter."""

import re
import shlex
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


def shq(s: str) -> str:
    """Shell-quote a string so it is safe to interpolate into shell=True commands.

    Protects filenames, metadata values, and URLs containing special characters
    (e.g. $, backticks, quotes) from being interpreted by the shell.
    """
    return shlex.quote(str(s) if s is not None else "")


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
            "label_source_tag": "label",
            "soundcloud_pages": 2
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


def strip_all_bracketed(text: str) -> str:
    """Remove all bracket/parenthesis groups (nested-safe) from text."""
    if not text:
        return ""
    result = text
    prev = None
    while prev != result:
        prev = result
        result = BRACKET_CLEANUP_RE.sub(' ', result)
    return ' '.join(result.split())


def split_artist_variants(artist: str) -> list:
    """Return artist variants for collaborations (feat., &, +, vs., x)."""
    artist = (artist or '').strip()
    if not artist:
        return []
    separators = (r'\s+&\s+', r'\s+\+\s+', r'\s+ft\.?\s+',
                  r'\s+feat\.?\s+', r'\s+vs\.?\s+', r'\s+x\s+')
    split = [artist]
    for sep in separators:
        if re.search(sep, artist, re.IGNORECASE):
            split = [p.strip() for p in re.split(sep, artist, flags=re.IGNORECASE) if p.strip()]
            break
    parts = [artist]
    if split != [artist]:
        parts.extend(split)
    variants = []
    for p in parts:
        if p and p not in variants:
            variants.append(p)
    return variants


def build_soundcloud_queries(artist: str, title: str) -> list:
    """Build ordered candidate queries for SoundCloud search.

    SoundCloud's /search/tracks is sensitive to non-title tokens such as catalog
    numbers ([DR016]) or mix qualifiers: a query containing them returns no
    results even when the track exists. Each candidate strips those tokens from
    the query; confidence scoring still runs against the full expected values.
    """
    artist = (artist or '').strip()
    title = (title or '').strip()
    if not title:
        return []

    cleaned = clean_title_for_search(title)
    stripped = strip_all_bracketed(title)
    words = stripped.split()
    prefix = ' '.join(words[:2])

    variants = [cleaned, stripped]
    if prefix and prefix not in variants:
        variants.append(prefix)

    candidates = []
    seen = set()
    for variant in variants:
        if not variant:
            continue
        queries = []
        for artist_variant in split_artist_variants(artist):
            query = f"{artist_variant} {variant}".strip()
            if query:
                queries.append(query)
        queries.append(variant)
        for query in queries:
            key = query.lower()
            if key not in seen:
                seen.add(key)
                candidates.append(query)
        if len(candidates) >= 8:
            break
    return candidates


def _token_containment(needle: str, haystack: str) -> float:
    """Fraction of needle's word tokens present in haystack (0.0-1.0)."""
    needle_tokens = re.findall(r'\w+', (needle or '').lower())
    if not needle_tokens:
        return 0.0
    haystack_lower = (haystack or '').lower()
    return sum(1 for t in needle_tokens if t in haystack_lower) / len(needle_tokens)


def _soundcloud_confidence(expected_artist: str, expected_title: str,
                           api_title: str, uploader: str) -> float:
    """Combine title-based confidence with uploader-artist agreement."""
    base = calculate_match_confidence(expected_artist, expected_title, api_title)
    if not expected_artist or not uploader:
        return base
    uploader_conf = _token_containment(expected_artist, uploader)
    if uploader_conf >= 0.5:
        return max(base, (base + uploader_conf) / 2)
    return base


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
    found_tokens = set(re.findall(r'\w+', found_lower))
    expected_artist = (expected_artist or '').strip()
    expected_title = (expected_title or '').strip()

    def _score(expected: str) -> float:
        if not expected:
            return 1.0
        expected_lower = expected.lower()
        words = re.findall(r'\w+', expected_lower)
        if len(words) >= 2:
            matches = sum(1 for w in words if w in found_tokens)
            word_score = matches / len(words)
        else:
            token = words[0] if words else expected_lower
            word_score = 1.0 if (token in found_tokens or expected_lower in found_lower) else 0.0
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

_soundcloud_track_cache: Dict[Any, Any] = {}


def _soundcloud_cache_key(artist: str, title: str):
    """Normalized cache key for a validated SoundCloud result."""
    return ((artist or '').strip().lower(), (title or '').strip().lower())


def get_soundcloud_result_cached(artist: str, title: str) -> Optional[Dict[str, Any]]:
    """Return a previously-validated SoundCloud result for artist/title, if any."""
    return _soundcloud_track_cache.get(_soundcloud_cache_key(artist, title))


def cache_soundcloud_result(artist: str, title: str, result: Dict[str, Any]) -> None:
    """Cache a validated SoundCloud track result for reuse."""
    _soundcloud_track_cache[_soundcloud_cache_key(artist, title)] = result


def search_soundcloud_api(query: str, limit: int = 20, pages: Optional[int] = None) -> list:
    """Search SoundCloud via API v2. Returns list of track result dicts."""
    import json
    from urllib.parse import quote

    if not SOUNDCLOUD_CLIENT_ID:
        logger.warning("No SOUNDCLOUD_CLIENT_ID in .env — SoundCloud search disabled")
        return []

    if pages is None:
        pages = load_config().get('metadata', {}).get('soundcloud_pages', 2)

    url = (f"https://api-v2.soundcloud.com/search/tracks"
           f"?q={quote(query)}&client_id={SOUNDCLOUD_CLIENT_ID}&limit={limit}")
    tracks = []
    seen = set()
    pages_fetched = 0
    while url and pages_fetched < max(1, pages):
        content = fetch_url(url, timeout=SEARCH_TIMEOUT)
        if not content:
            break
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            break
        for track in data.get('collection', []):
            key = track.get('permalink_url') or track.get('id')
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            tracks.append(track)
        pages_fetched += 1
        url = data.get('next_href') or ''
    return tracks


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

    confidence = _soundcloud_confidence(expected_artist, expected_title, api_title, uploader)
    threshold = config.get('soundcloud_confidence_threshold', 0.6)

    if confidence >= threshold:
        # Upgrade artwork to t500x500 for higher resolution
        if artwork and '-large.jpg' in artwork:
            artwork = artwork.replace('-large.jpg', '-t500x500.jpg')
        result = {
            'title': api_title,
            'artist': uploader,
            'thumbnail': artwork,
            'url': permalink,
            'confidence': confidence,
        }
        cache_soundcloud_result(expected_artist, expected_title, result)
        return result

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
    
    curl_cmd.append(shq(url))
    
    success, stdout, _ = run_cmd(' '.join(curl_cmd), timeout=timeout + 5)
    return stdout if success else ""
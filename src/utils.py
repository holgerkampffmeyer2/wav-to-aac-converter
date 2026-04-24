#!/usr/bin/env python3
"""Utility functions, constants, and helper code for wav-to-aac-converter."""

import re
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Callable, Tuple, Optional
from functools import wraps

logger = logging.getLogger(__name__)

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
    config_path = Path(__file__).parent / 'config.json'
    default_config: Dict[str, Any] = {
        "ascii_filename": False,
        "output_format": "mp3",
        "max_parallel_processes": 5,
        "loudnorm": True,
        "embed_cover": True,
        "retry_attempts": 3,
        "timeout_seconds": 30,
        "fuzzy_threshold": 0.8,
        "metadata": {
            "enabled": True,
            "sources": ["itunes", "bandcamp", "musicbrainz", "deezer"],
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


def fetch_url(url: str, timeout: int = DEFAULT_TIMEOUT, headers: Optional[Dict[str, str]] = None, method: str = 'GET', data: Optional[Dict[str, str]] = None) -> str:
    """Fetch URL content with configurable options."""
    from typing import Dict
    
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
    
    curl_cmd.append(url)
    
    success, stdout, _ = run_cmd(' '.join(curl_cmd), timeout=timeout + 5)
    return stdout if success else ""
#!/usr/bin/env python3
"""Cover art search functions for wav-to-aac-converter."""

import json
import logging
from typing import Optional
from urllib.parse import quote

from utils import (
    DEEZER_API_URL,
    MUSICBRAINZ_SEARCH_URL,
    MUSICBRAINZ_COVER_URL,
    BANDCAMP_SEARCH_URL,
    SEARCH_TIMEOUT,
    RETRY_ATTEMPTS,
    RETRY_DELAY,
    RETRY_BACKOFF,
    OG_IMAGE_RE,
    BANDCAMP_URL_RE,
    retry,
    fetch_url,
    clean_title_for_search
)

logger = logging.getLogger(__name__)


@retry(max_attempts=RETRY_ATTEMPTS, delay=RETRY_DELAY, backoff=RETRY_BACKOFF)
def search_deezer_cover(artist: str, title: str) -> Optional[str]:
    """Search Deezer API for cover art using track search."""
    if not artist and not title:
        return None
    
    # Try track search first (better for getting actual track cover)
    query = f"{artist}+{title}".replace(' ', '+')
    url = f"https://api.deezer.com/search/track?q={quote(query)}&limit=5"
    content = fetch_url(url, timeout=SEARCH_TIMEOUT)
    if not content:
        return None
    try:
        data = json.loads(content)
        if data.get('data') and len(data['data']) > 0:
            # Get cover from track's album
            for track in data['data']:
                album = track.get('album')
                if album:
                    cover = album.get('cover_big') or album.get('cover_medium') or album.get('cover_small')
                    if cover:
                        return cover
            # Fallback: get any cover from results
            return data['data'][0].get('album', {}).get('cover_big')
    except json.JSONDecodeError:
        pass
    
    # Fallback: try album search
    url = f"{DEEZER_API_URL}{query}"
    content = fetch_url(url, timeout=SEARCH_TIMEOUT)
    if not content:
        return None
    try:
        data = json.loads(content)
        if data.get('data') and len(data['data']) > 0:
            return data['data'][0].get('cover_big')
    except json.JSONDecodeError:
        pass
    return None


def search_musicbrainz_cover(artist: str, title: str) -> Optional[str]:
    """Search MusicBrainz Cover Art Archive for cover art."""
    if not artist and not title:
        return None
    
    query = f'artist:"{artist}" AND recording:"{title}"'
    search_url = f"{MUSICBRAINZ_SEARCH_URL}?query={quote(query)}&fmt=json&limit=1"
    content = fetch_url(search_url, timeout=SEARCH_TIMEOUT)
    if not content:
        return None
    
    try:
        data = json.loads(content)
        releases = data.get('releases', [])
        if not releases:
            return None
        mbid = releases[0].get('id')
        if not mbid:
            return None
    except (json.JSONDecodeError, KeyError, IndexError):
        return None
    
    cover_url = f"{MUSICBRAINZ_COVER_URL}{mbid}/front-500"
    content = fetch_url(cover_url, timeout=SEARCH_TIMEOUT)
    if not content:
        return None
    
    if content.startswith('http'):
        return content
    
    return None


@retry(max_attempts=RETRY_ATTEMPTS, delay=RETRY_DELAY, backoff=RETRY_BACKOFF)
def search_bandcamp_cover(artist: str, title: str) -> Optional[str]:
    """Search Bandcamp for cover art via web search."""
    if not artist and not title:
        return None
    query = f"{artist} {title}".strip()
    if not query:
        return None
    search_url = f"{BANDCAMP_SEARCH_URL}{query.replace(' ', '+')}"
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


def search_all_sources(artist: str, title: str, filename: str = "") -> tuple[dict, Optional[str]]:
    """Search all cover art sources in order.
    
    Returns:
        tuple: (metadata dict, cover_url or None)
    """
    from utils import extract_metadata_from_filename
    
    result_metadata: Dict[str, Any] = {}
    cover_url: Optional[str] = None
    
    # Try to get metadata from filename first
    if not artist or not title:
        artist, title = extract_metadata_from_filename(filename or "")
        result_metadata = {"artist": artist, "title": title}
    
    sources = [
        ("Deezer", lambda a, t: search_deezer_cover(a, t)),
        ("MusicBrainz", lambda a, t: search_musicbrainz_cover(a, t)),
        ("Bandcamp", lambda a, t: search_bandcamp_cover(a, t)),
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
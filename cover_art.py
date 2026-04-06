#!/usr/bin/env python3
"""Cover art search functions for wav-to-aac-converter."""

import json
import logging
from typing import Optional, Dict, Any, Tuple
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
    clean_title_for_search,
    load_config
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


def enrich_and_search_cover(wav_path: str, filename: str, config: Dict[str, Any], original_wav_path: str = None) -> Tuple[Dict[str, Any], Optional[str]]:
    """Combined function: Online metadata lookup + enrich + cover search.
    
    Cover priority:
    1. Embedded cover in WAV file (extract with ffmpeg)
    2. Local cover file in same folder (uses original path)
    3. Online cover (Deezer → MusicBrainz → Bandcamp)
    
    Args:
        wav_path: Path to the WAV file (may be temp copy)
        filename: Original filename for fallback
        config: Configuration dict
        original_wav_path: Original WAV path for local cover search
        
    Returns:
        Tuple of (metadata_dict, cover_source)
        cover_source can be:
        - Path to extracted/downloaded cover file
        - URL string (http://...) for online download
        - None if no cover found
    """
    from metadata import (
        extract_metadata,
        lookup_online_metadata,
        extract_metadata_from_filename,
        enrich_file_metadata,
        lookup_label_online,
        get_genre_online,
        get_additional_metadata_online
    )
    from audio_processing import find_local_cover, run_cmd as audio_run_cmd
    from pathlib import Path
    
    online_lookup_enabled = config.get('online_lookup', {}).get('enabled', True)
    enrich_enabled = config.get('enrich_metadata', {}).get('enabled', True)
    fallback_to_filename = config.get('online_lookup', {}).get('fallback_to_filename', True)
    
    metadata = {}
    cover_source = None
    artist = None
    title = None
    
    current_metadata = extract_metadata(wav_path)
    metadata = {k: v for k, v in current_metadata.items() if isinstance(v, str)}
    
    artist = metadata.get('artist', '')
    title = metadata.get('title', '')
    
    if not (artist and title) and fallback_to_filename:
        raw_artist, raw_title = extract_metadata_from_filename(filename or Path(wav_path).stem)
        if not artist:
            artist = raw_artist
            metadata['artist'] = artist
        if not title:
            title = raw_title
            metadata['title'] = title
    
    if online_lookup_enabled and not (artist and title):
        online_artist, online_title = lookup_online_metadata(f"{artist} {title}")
        if online_artist and online_title:
            artist = online_artist
            title = online_title
            metadata['artist'] = artist
            metadata['title'] = title
            logger.info(f"  Online metadata: {artist} - {title}")
    
    if not artist or not title:
        if fallback_to_filename:
            raw_artist, raw_title = extract_metadata_from_filename(filename or Path(wav_path).stem)
            if not artist:
                artist = raw_artist
                metadata['artist'] = artist
            if not title:
                title = raw_title
                metadata['title'] = title
            logger.info(f"  Metadata from filename: {artist} - {title}")
    
    if enrich_enabled and artist and title:
        enriched = enrich_file_metadata(wav_path, artist, title, config, current_metadata)
        if enriched:
            metadata.update(enriched)
    
    cover_path_for_local = original_wav_path if original_wav_path else wav_path
    cover_source = _find_cover(wav_path, artist, title, cover_path_for_local)
    
    return metadata, cover_source


def _find_cover(wav_path: str, artist: str, title: str, original_wav_path: str = None) -> Optional[str]:
    """Find cover with priority: embedded in WAV → local → online.
    
    Args:
        wav_path: Path to the WAV file (may be temp copy)
        artist: Artist name
        title: Track title
        original_wav_path: Original WAV path for local cover search (if different from wav_path)
    
    Returns:
        - Local file path if found
        - URL string (http://...) for online download
        - None if no cover
    """
    from audio_processing import find_local_cover, run_cmd as audio_run_cmd, download_cover
    from pathlib import Path
    
    path_for_local_search = original_wav_path if original_wav_path else wav_path
    
    file_hash = hash(wav_path) % 1000000
    temp_cover = f'/tmp/cover_{file_hash}.jpg'
    
    cmd = f'ffmpeg -y -i "{wav_path}" -map 0:v -map -0:a -c:v copy "{temp_cover}" 2>/dev/null'
    success, _, _ = audio_run_cmd(cmd)
    if success and Path(temp_cover).exists():
        logger.info(f"  Cover: Extracted from source")
        return temp_cover
    
    local_cover = find_local_cover(path_for_local_search)
    if local_cover:
        if local_cover.lower().endswith('.png'):
            png_cover = f'/tmp/cover_{file_hash}.png'
            import shutil
            shutil.copy(local_cover, png_cover)
            logger.info(f"  Cover: Found local file (PNG)")
            return png_cover
        logger.info(f"  Cover: Found local file")
        return local_cover
    
    if artist and title:
        search_title = clean_title_for_search(title) if clean_title_for_search(title) else title
        
        cover_url = search_deezer_cover(artist, search_title)
        if cover_url:
            logger.info(f"  Cover: Found on Deezer")
            return cover_url
        
        cover_url = search_musicbrainz_cover(artist, search_title)
        if cover_url:
            logger.info(f"  Cover: Found on MusicBrainz")
            return cover_url
        
        cover_url = search_bandcamp_cover(artist, search_title)
        if cover_url:
            logger.info(f"  Cover: Found on Bandcamp")
            return cover_url
    
    logger.debug(f"  Cover: Not found")
    return None
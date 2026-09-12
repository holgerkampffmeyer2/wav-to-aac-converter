#!/usr/bin/env python3
"""Cover art search functions for wav-to-aac-converter."""

import json
import logging
from typing import Optional, Dict, Any, Tuple
from urllib.parse import quote

from src.utils import (
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
    load_config,
    shq,
    search_soundcloud_api,
    try_soundcloud_api_result,
    build_soundcloud_queries,
    get_soundcloud_result_cached,
    strip_all_bracketed,
)

logger = logging.getLogger(__name__)


@retry(max_attempts=RETRY_ATTEMPTS, delay=RETRY_DELAY, backoff=RETRY_BACKOFF)
def search_deezer_cover(artist: str, title: str) -> Optional[str]:
    """Search Deezer API for cover art using track search."""
    if not artist and not title:
        return None
    
    artist = strip_all_bracketed(artist or '').strip()
    title = strip_all_bracketed(title or '').strip()
    if not artist and not title:
        return None

    # Try track search first (better for getting actual track cover)
    query = f"{artist}+{title}".replace(' ', '+').strip('+')
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

    artist = strip_all_bracketed(artist or '').strip()
    title = strip_all_bracketed(title or '').strip()
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

    artist = strip_all_bracketed(artist or '').strip()
    title = strip_all_bracketed(title or '').strip()
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


def search_soundcloud_cover(artist: str, title: str) -> Optional[str]:
    """Search SoundCloud for cover art via API v2 with confidence scoring."""
    if not artist and not title:
        return None

    cached = get_soundcloud_result_cached(artist, title)
    if cached is not None and cached.get('thumbnail'):
        return cached['thumbnail']

    config = load_config()
    for query in build_soundcloud_queries(artist, title):
        results = search_soundcloud_api(query)
        if not results:
            continue
        for track in results:
            result = try_soundcloud_api_result(track, artist, title, config)
            if result:
                logger.info(f"  SoundCloud cover found (confidence {result['confidence']:.2f})")
                return result['thumbnail']
    return None


def search_all_sources(artist: str, title: str, filename: str = "") -> tuple[dict, Optional[str]]:
    """Search all cover art sources in order.
    
    Returns:
        tuple: (metadata dict, cover_url or None)
    """
    from .metadata import extract_metadata_from_filename
    
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
    from .metadata import (
        extract_metadata,
        lookup_online_metadata,
        extract_metadata_from_filename,
        enrich_file_metadata,
        lookup_label_online,
        get_genre_online,
        get_additional_metadata_online
    )
    from .audio_processing import find_local_cover, run_cmd as audio_run_cmd
    from pathlib import Path
    
    metadata_enabled = config.get('metadata', {}).get('enabled', True)
    offline = config.get('metadata', {}).get('offline', False)
    fallback_to_filename = config.get('metadata', {}).get('fallback_to_filename', True)

    search_filename = Path(original_wav_path).stem if original_wav_path else (filename or Path(wav_path).stem)

    metadata = {}
    artist = None
    title = None
    
    current_metadata = extract_metadata(wav_path)
    metadata = {k: v for k, v in current_metadata.items() if isinstance(v, str)}
    
    artist = metadata.get('artist', '')
    title = metadata.get('title', '')
    
    if not (artist and title) and fallback_to_filename:
        raw_artist, raw_title = extract_metadata_from_filename(search_filename)
        fname = search_filename
        if ' - ' in fname:
            artist = raw_artist
            title = raw_title
            metadata['artist'] = artist
            metadata['title'] = title
        else:
            if not artist:
                artist = raw_artist
                metadata['artist'] = artist
            if not title:
                title = raw_title
                metadata['title'] = title
    
    search_term = f"{artist} {title}".strip()
    if metadata_enabled and search_term and not (artist and title):
        online_artist, online_title = lookup_online_metadata(search_term)
        if online_artist and online_title:
            artist = online_artist
            title = online_title
            metadata['artist'] = artist
            metadata['title'] = title
            logger.info(f"  Online metadata: {artist} - {title}")
    
    if not artist and not title:
        if fallback_to_filename:
            raw_artist, raw_title = extract_metadata_from_filename(search_filename)
            if not artist:
                artist = raw_artist
                metadata['artist'] = artist
            if not title:
                title = raw_title
                metadata['title'] = title
            logger.info(f"  Metadata from filename: {artist} - {title}")
    
    # Filenames may use "Title - Artist" instead of "Artist - Title". When relying on
    # filename parsing, verify the ordering against online metadata sources.
    if (metadata_enabled and not offline and fallback_to_filename
            and artist and title and ' - ' in search_filename):
        from .metadata import resolve_artist_title_online
        resolved_artist, resolved_title = resolve_artist_title_online(artist, title, config)
        if (resolved_artist, resolved_title) != (artist, title):
            artist, title = resolved_artist, resolved_title
            metadata['artist'] = artist
            metadata['title'] = title
            logger.info(f"  Online metadata (disambiguated): {artist} - {title}")
    
    if metadata_enabled and artist and title:
        enriched = enrich_file_metadata(wav_path, artist, title, config, current_metadata)
        if enriched:
            metadata.update(enriched)
    
    cover_path_for_local = original_wav_path if original_wav_path else wav_path
    cover_source = _find_cover(wav_path, artist, title, cover_path_for_local, offline, config)
    
    return metadata, cover_source


COVER_SOURCE_DISPATCH = {
    'deezer': ('Deezer', lambda a, t, c: search_deezer_cover(a, t)),
    'soundcloud': ('SoundCloud', lambda a, t, c: search_soundcloud_cover(a, t)),
    'musicbrainz': ('MusicBrainz', lambda a, t, c: search_musicbrainz_cover(a, t)),
    'bandcamp': ('Bandcamp', lambda a, t, c: search_bandcamp_cover(a, t)),
}


def _get_cover_sources(config: Dict[str, Any]) -> list:
    """Get ordered list of cover source names from config, filtered to valid sources only."""
    all_sources = config.get('metadata', {}).get('sources', [
        'deezer', 'soundcloud', 'musicbrainz', 'bandcamp'
    ])
    return [s for s in all_sources if s.lower() in COVER_SOURCE_DISPATCH]


def _find_cover(wav_path: str, artist: str, title: str, original_wav_path: str = None,
                offline: bool = False, config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Find cover with priority: embedded → local → online (configurable sources).
    
    Args:
        wav_path: Path to the audio file (may be temp copy)
        artist: Artist name
        title: Track title
        original_wav_path: Original path for local cover search
        offline: If True, skip online cover search
        config: Configuration dict (for source ordering)
    
    Returns:
        - Local file path if found
        - URL string (http://...) for online download
        - None if no cover
    """
    from .audio_processing import find_local_cover, run_cmd as audio_run_cmd, download_cover
    from pathlib import Path
    
    if config is None:
        from .utils import load_config
        config = load_config()
    
    path_for_local_search = original_wav_path if original_wav_path else wav_path
    
    file_hash = hash(wav_path) % 1000000
    temp_cover = f'/tmp/cover_{file_hash}.jpg'
    
    cmd = f'ffmpeg -y -i {shq(wav_path)} -map 0:v -map -0:a -c:v copy {shq(temp_cover)} 2>/dev/null'
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
    
    if not offline and artist and title:
        search_title = clean_title_for_search(title) if clean_title_for_search(title) else title
        sources = _get_cover_sources(config)
        
        for source_name in sources:
            entry = COVER_SOURCE_DISPATCH.get(source_name.lower())
            if not entry:
                logger.warning(f"  Unknown cover source: {source_name}")
                continue
            label, func = entry
            try:
                cover_url = func(artist, search_title, config)
                if cover_url:
                    logger.info(f"  Cover: Found on {label}")
                    return cover_url
            except Exception as e:
                logger.warning(f"  {label} search failed: {e}")
    
    logger.debug(f"  Cover: Not found")
    return None
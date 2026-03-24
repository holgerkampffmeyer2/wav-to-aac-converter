#!/usr/bin/env python3
"""WAV to MP3/M4A converter with loudness normalization, metadata, and cover art."""

import subprocess
import json
import sys
import os
import re
import time
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import wraps

MAX_PARALLEL_PROCESSES = 5
OUTPUT_FORMAT = 'mp3'

OG_IMAGE_RE = re.compile(r'"og:image"\s+content="([^"]+)"')
BANDCAMP_URL_RE = re.compile(r'https?://[^\s"\'<>]*\.bandcamp\.com/(?:track|album)/[^\s"\'<>]*')
SNDCLOUD_ARTWORK_RE = re.compile(r'https?://i1\.sndcdn\.com/artworks-[\w-]+\.(?:png|jpg)')
HANDLE_RE = re.compile(r'\[([^\]]+)\]', re.IGNORECASE)
NON_WORD_RE = re.compile(r'[^\w]')
MULTI_DASH_RE = re.compile(r'-+')
BRACKET_CLEANUP_RE = re.compile(r'\([^)]*\)|\[[^\]]*\]')
REMIX_KEYWORDS_RE = re.compile(
    r'(?:remix|edit|mix|flip|rework|cover|feat|ft\.|featuring|radio|clean|explicit|instrumental|acappella)',
    re.IGNORECASE
)
USER_AGENT = '"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"'


def retry(max_attempts=3, delay=1, backoff=2):
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


def run_cmd(cmd, capture_output=True, timeout=600):
    """Run shell command and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=capture_output, text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"


def analyze_loudness(wav_path):
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


def extract_metadata(wav_path):
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


def _fetch_url(url, timeout=15):
    """Fetch URL content with custom headers."""
    headers = f'-A {USER_AGENT} -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"'
    cmd = f'curl -sL {headers} --max-time {timeout} "{url}"'
    success, stdout, _ = run_cmd(cmd, timeout=timeout + 5)
    return stdout if success else ""


@retry(max_attempts=3, delay=1, backoff=2)
def search_deezer_cover(artist, title):
    """Search Deezer API for cover art."""
    if not artist and not title:
        return None
    query = f"{artist}+{title}".replace(' ', '+')
    url = f"https://api.deezer.com/search/album?q={query}"
    content = _fetch_url(url)
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
def search_bandcamp_cover(artist, title):
    """Search Bandcamp for cover art via web search."""
    if not artist and not title:
        return None
    query = f"{artist} {title}".strip()
    if not query:
        return None
    search_url = f"https://bandcamp.com/search?q={query.replace(' ', '+')}"
    content = _fetch_url(search_url)
    if not content:
        return None
    
    match = BANDCAMP_URL_RE.search(content)
    if not match:
        return None
    
    bandcamp_url = match.group(0).split('"')[0].split('&')[0]
    page_content = _fetch_url(bandcamp_url)
    if page_content:
        img_match = OG_IMAGE_RE.search(page_content)
        if img_match:
            return img_match.group(1)
    return None


def extract_handles(filename):
    """Extract SoundCloud handles from filename."""
    return [h for h in HANDLE_RE.findall(filename.lower()) if len(h) >= 3]


def clean_title_for_search(title):
    """Remove remix/edit/etc. info from title for cover art search.
    
    Removes any bracket (with nested content) if it contains remix/edit/etc. keywords.
    """
    def find_matching_paren(text, start):
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
    
    def strip_brackets(text):
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


@retry(max_attempts=3, delay=1, backoff=2)
def _fetch_soundcloud_cover(sc_url):
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


def search_soundcloud_web(artist, title, filename=""):
    """Search SoundCloud via web for track info and cover art."""
    if not artist and not title and not filename:
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
    
    for handle in handles:
        if len(handle) >= 3:
            sc_url = f"https://soundcloud.com/{handle}"
            if sc_url not in searched:
                searched.add(sc_url)
                img_url = _fetch_soundcloud_cover(sc_url)
                if img_url:
                    return (artist, title), img_url
    
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


def search_all_sources(artist, title, filename=""):
    """Search all online sources for track metadata and cover art.
    Returns: (metadata dict, cover_url)
    """
    result_metadata = {}
    cover_url = None
    
    if not artist and not title:
        return result_metadata, cover_url
    
    sources = [
        ("Deezer", lambda a, t: search_deezer_cover(a, t)),
        ("Bandcamp", lambda a, t: search_bandcamp_cover(a, t)),
        ("SoundCloud", lambda a, t: search_soundcloud_web(a, t, filename)[1]),
    ]
    
    for source_name, search_func in sources:
        try:
            found_cover = search_func(artist, title)
            if found_cover and not cover_url:
                cover_url = found_cover
                print(f"  {source_name} cover found")
        except Exception as e:
            print(f"  {source_name} search failed: {e}")
    
    return result_metadata, cover_url


def extract_metadata_from_filename(filename):
    """Extract artist and title from filename with improved robustness.
    
    Rules:
    - Multiple separators: " - ", " – ", " — ", "_", "." (when not file extension)
    - First separator splits Artist from Title
    - Special patterns: "[handle] Title.wav" and "Title [handle].wav" (only for SC-style handles that look like usernames)
    - Skip leading track numbers: "01 - Artist - Title.wav"
    - No artist info in filename? Return empty artist
    """
    name = Path(filename).stem.strip()
    
    # Define descriptive terms that should NOT be treated as artists even if found in brackets
    descriptive_terms = {
        'remix', 'edit', 'mix', 'flip', 'rework', 'cover', 'feat', 'ft', 'featuring',
        'radio', 'clean', 'explicit', 'instrumental', 'acappella', 'dub', 'master',
        'extended', 'version', 'cut', 'mixshow', 'club', 'original', 'live', 'draft',
        'preview', 'teaser', 'snippet', 'demo', 'test', 'unmastered', 'unreleased',
        'wip', 'work in progress', 'flip', 'bootleg', 'vip', 'dbl', 'tb'
    }
    
    # Handle special SoundCloud patterns: [handle] Title or Title [handle]
    # But only if the handle looks like a username (not just descriptive text)
    handle_match = re.match(r'\[([^\]]+)\]\s+(.+)', name)
    if handle_match:
        potential_artist = handle_match.group(1).strip()
        title = handle_match.group(2).strip()
        # Only use handle as artist if it looks like a username and not a descriptive term
        if (potential_artist and 
            not potential_artist.isdigit() and 
            len(potential_artist) >= 2 and
            potential_artist.lower() not in descriptive_terms and
            not re.search(r'(?:remix|edit|mix|flip|rework|cover|feat|ft\.|featuring|radio|clean|explicit|instrumental|acappella|dub|master|extended|version|cut|mixshow|club|original|mix|edit|remix|edit)', potential_artist, re.IGNORECASE)):
            return potential_artist, title
        # Otherwise fall through to normal separator processing
    
    handle_match = re.match(r'(.+)\s+\[([^\]]+)\]', name)
    if handle_match:
        title = handle_match.group(1).strip()
        potential_artist = handle_match.group(2).strip()
        # Only use handle as artist if it looks like a username and not a descriptive term
        if (potential_artist and 
            not potential_artist.isdigit() and 
            len(potential_artist) >= 2 and
            potential_artist.lower() not in descriptive_terms and
            not re.search(r'(?:remix|edit|mix|flip|rework|cover|feat|ft\.|featuring|radio|clean|explicit|instrumental|acappella|dub|master|extended|version|cut|mixshow|club|original|mix|edit|remix|edit)', potential_artist, re.IGNORECASE)):
            return potential_artist, title
        # Otherwise fall through to normal separator processing
    
    # Handle multiple separator types - but be more careful with underscore and dot
    # Only treat underscore/dot as separator if it looks like a deliberate separator pattern
    separators = [' - ', ' – ', ' — ']  # Definite separators (with spaces)
    flexible_separators = ['_', '.']   # Potential separators (need context check)
    
    # Check definite separators first
    for sep in separators:
        if sep in name:
            # Only split on first occurrence
            parts = name.split(sep, 1)
            artist = parts[0].strip()
            title = parts[1].strip()
            
            # Check if artist part looks like a track number (digits only or with common suffixes)
            if re.match(r'^\d+(\s*(st|nd|rd|th))?$', artist):
                # This looks like a track number, try to get artist from title part
                # Look for another separator in the title part
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
            # Only treat as separator if surrounded by alphanumerics or common filename chars
            # This avoids treating "Artist_Title" as separator when it's actually part of a single title
            parts = name.split(sep, 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                title = parts[1].strip()
                
                # Additional validation: both parts should look reasonable
                # Artist should not be just numbers or descriptive terms
                # Title should not be empty
                if (artist and title and 
                    not re.match(r'^\d+(\s*(st|nd|rd|th))?$', artist) and  # Not just track number
                    artist.lower() not in descriptive_terms and  # Not descriptive term
                    len(artist) >= 1):  # Reasonable length
                    
                    # Check if artist part looks like a track number
                    if re.match(r'^\d+(\s*(st|nd|rd|th))?$', artist):
                        # This looks like a track number, try to get artist from title part
                        # Look for another separator in the title part
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


def encode_mp3(wav_path, output_path, metadata, gain_db):
    """Encode WAV to MP3 with metadata."""
    cmd = f'ffmpeg -y -i "{wav_path}" -map 0:a -af "volume={gain_db}dB" -c:a libmp3lame -b:a 320k'
    for key, value in metadata.items():
        if value and isinstance(value, str):
            cmd += f' -metadata {key}="{value}"'
    cmd += f' "{output_path}"'
    success, _, stderr = run_cmd(cmd)
    return success


def encode_m4a(wav_path, output_path, metadata, gain_db):
    """Encode WAV to M4A/AAC with metadata."""
    cmd = f'ffmpeg -y -i "{wav_path}" -map 0:a -af "volume={gain_db}dB" -c:a aac -b:a 320k'
    for key, value in metadata.items():
        if value and isinstance(value, str):
            cmd += f' -metadata {key}="{value}"'
    cmd += f' -movflags +use_metadata_tags "{output_path}"'
    success, _, stderr = run_cmd(cmd)
    return success


def embed_cover_mp3(mp3_path, cover_path, final_path):
    """Embed cover art into MP3 using ffmpeg."""
    cmd = f'ffmpeg -y -i "{mp3_path}" -i "{cover_path}" -map 0:a -map 1:v -c:a copy -c:v copy -id3v2_version 3 -metadata:s:v title="Album cover" -metadata:s:v mimetype="image/jpeg" "{final_path}"'
    success, _, _ = run_cmd(cmd)
    return success


def embed_cover_m4a(m4a_path, cover_path, final_path):
    """Embed cover art into M4A."""
    cmd = f'ffmpeg -y -i "{m4a_path}" -i "{cover_path}" -c:a copy -c:v copy -map 0:a -map 1:v -disposition:1 attached_pic "{final_path}"'
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


def convert_file(wav_path, fmt='mp3'):
    """Convert a single WAV file to MP3 or M4A."""
    print(f"Processing: {wav_path} -> {fmt.upper()}")
    
    wav_path = str(wav_path)
    base_name = Path(wav_path).stem
    output_name = base_name + f'.{fmt}'
    
    file_hash = hash(wav_path) % 1000000
    temp_cover = f'cover_{file_hash}.jpg'
    temp_output = f'output_{file_hash}.{fmt}'
    
    loudness = analyze_loudness(wav_path)
    if not loudness:
        print(f"  FAIL: Loudness analysis failed")
        return False, None
    print(f"  Loudness: {loudness.get('input_i', 'N/A')} LUFS, True Peak: {loudness.get('input_tp', 'N/A')} dB")
    
    input_tp = float(loudness.get('input_tp', -10))
    gain_db = min(0, -0.1 - input_tp)
    
    metadata = extract_metadata(wav_path)
    print(f"  Metadata: {metadata}")
    
    search_artist = metadata.get('artist', '')
    search_title = metadata.get('title', '')
    
    if not search_artist or not search_title:
        artist, title = extract_metadata_from_filename(base_name)
        if not search_artist:
            search_artist = artist
            metadata['artist'] = artist
        if not search_title:
            search_title = title
            metadata['title'] = title
    
    metadata = {k: v for k, v in metadata.items() if isinstance(v, str)}
    
    cover_path = None
    web_metadata = None
    
    cmd = f'ffmpeg -y -i "{wav_path}" -map 0:v -map -0:a -c:v copy "{temp_cover}" 2>/dev/null'
    success, _, _ = run_cmd(cmd)
    if Path(temp_cover).exists():
        cover_path = temp_cover
        print(f"  Cover: Extracted from source")
    else:
        local_cover = find_local_cover(wav_path)
        if local_cover:
            if local_cover.lower().endswith('.png'):
                success, _, _ = run_cmd(f'ffmpeg -y -i "{local_cover}" "{temp_cover}" 2>/dev/null')
                if success and Path(temp_cover).exists():
                    cover_path = temp_cover
            else:
                cover_path = local_cover
            print(f"  Cover: Found local file")
        else:
            search_title_clean = clean_title_for_search(search_title)
            
            cover_url = search_deezer_cover(search_artist, search_title_clean)
            if cover_url:
                download_cover(cover_url, temp_cover)
                print(f"  Cover: Downloaded from Deezer")
            elif search_artist or search_title:
                cover_url = search_bandcamp_cover(search_artist, search_title_clean)
                if cover_url:
                    download_cover(cover_url, temp_cover)
                    print(f"  Cover: Downloaded from Bandcamp")
                else:
                    web_metadata, cover_url = search_soundcloud_web(search_artist, search_title, base_name)
                    if cover_url:
                        download_cover(cover_url, temp_cover)
                        print(f"  Cover: Downloaded from SoundCloud")
                        if web_metadata and not metadata.get('artist'):
                            metadata['artist'] = web_metadata[0] or ''
                        if web_metadata and not metadata.get('title'):
                            metadata['title'] = web_metadata[1] or ''
            
            if Path(temp_cover).exists():
                cover_path = temp_cover
            else:
                print(f"  Cover: Not found")
    
    if fmt == 'mp3':
        success = encode_mp3(wav_path, temp_output, metadata, gain_db)
    else:
        success = encode_m4a(wav_path, temp_output, metadata, gain_db)
    
    if not success:
        print(f"  FAIL: Encoding failed")
        save_result_json(wav_path, metadata, loudness, output_name, False, False, fmt)
        for f in [temp_output, temp_cover]:
            if f and Path(f).exists():
                os.remove(f)
        return False, None
    
    if cover_path and Path(cover_path).exists():
        if fmt == 'mp3':
            embed_success = embed_cover_mp3(temp_output, cover_path, output_name)
        else:
            embed_success = embed_cover_m4a(temp_output, cover_path, output_name)
        
        if embed_success:
            for f in [temp_output, temp_cover, cover_path]:
                if f and f != cover_path and Path(f).exists():
                    os.remove(f)
            if cover_path == temp_cover and Path(temp_cover).exists():
                os.remove(temp_cover)
        else:
            print(f"  FAIL: Cover embedding failed, using raw file")
            os.rename(temp_output, output_name)
            if cover_path == temp_cover and Path(temp_cover).exists():
                os.remove(temp_cover)
    else:
        os.rename(temp_output, output_name)
    
    valid, result = verify_output(output_name, fmt)
    info = result if isinstance(result, dict) else {}
    if valid:
        print(f"  SUCCESS: {output_name} ({fmt.upper()}: {info.get(fmt)}, Cover: {info.get('cover')})")
        return True, output_name
    else:
        print(f"  FAIL: Verification failed - {result}")
        save_result_json(wav_path, metadata, loudness, output_name, False, bool(info.get('cover')), fmt)
        return False, None


def _convert_file_wrapper(args):
    """Wrapper for parallel processing."""
    wav_path, fmt = args
    success, output = convert_file(wav_path, fmt)
    return (wav_path, success, output)


def convert_batch(file_paths, fmt='mp3', parallel=True, max_workers=MAX_PARALLEL_PROCESSES):
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
    
    print(f"Converting {len(file_paths)} files in parallel (max {max_workers} workers)...")
    
    with ProcessPoolExecutor(max_workers=min(max_workers, len(file_paths))) as executor:
        futures = {executor.submit(_convert_file_wrapper, (fp, fmt)): fp for fp in file_paths}
        for future in as_completed(futures):
            results.append(future.result())
    
    return results


def parse_args():
    """Parse command line arguments."""
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
    parser.add_argument('--format', choices=['mp3', 'm4a'], default='mp3',
                       help='Output format (default: mp3)')
    parser.add_argument('files', nargs='+', help='WAV file(s) to convert')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    
    wav_files = [f for f in args.files if f.endswith('.wav') or f.endswith('.WAV')]
    
    if not wav_files:
        print("Error: No WAV files found")
        sys.exit(1)
    
    if args.m4a:
        fmt = 'm4a'
    else:
        fmt = args.format
    
    print(f"Output format: {fmt.upper()}")
    
    if len(wav_files) == 1:
        success, output = convert_file(wav_files[0], fmt)
        sys.exit(0 if success else 1)
    
    results = convert_batch(wav_files, fmt)
    
    success_count = sum(1 for _, s, _ in results if s)
    print(f"\nBatch complete: {success_count}/{len(results)} succeeded")
    
    sys.exit(0 if success_count == len(results) else 1)

#!/usr/bin/env python3
"""WAV to AAC converter with loudness normalization, metadata, and cover art."""

import subprocess
import json
import sys
import os
import re
from pathlib import Path

def run_cmd(cmd, capture_output=True):
    """Run shell command and return output."""
    result = subprocess.run(cmd, shell=True, capture_output=capture_output, text=True)
    return result.returncode == 0, result.stdout, result.stderr

def analyze_loudness(wav_path):
    """Analyze loudness of WAV file."""
    cmd = f'ffmpeg -i "{wav_path}" -af loudnorm=print_format=json -f null - 2>&1'
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

def search_deezer_cover(artist, title):
    """Search Deezer API for cover art."""
    query = f"{artist}+{title}".replace(' ', '+')
    cmd = f'curl -sL "https://api.deezer.com/search/album?q={query}"'
    success, stdout, _ = run_cmd(cmd)
    if not success:
        return None
    try:
        data = json.loads(stdout)
        if data.get('data') and len(data['data']) > 0:
            return data['data'][0].get('cover_big')
    except json.JSONDecodeError:
        pass
    return None

def search_bandcamp_cover(artist, title):
    """Search Bandcamp for cover art via web search."""
    if not artist and not title:
        return None
    query = f"{artist} {title}".strip()
    if not query:
        return None
    url = f"https://bandcamp.com/search?q={query.replace(' ', '+')}"
    cmd = f'curl -sL -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" "{url}"'
    success, stdout, _ = run_cmd(cmd)
    if not success:
        return None
    match = re.search(r'https?://[^\s"\'<>]*\.bandcamp\.com/track/[^\s"\'<>]*', stdout)
    if not match:
        match = re.search(r'https?://[^\s"\'<>]*\.bandcamp\.com/album/[^\s"\'<>]*', stdout)
    if not match:
        return None
    bandcamp_url = match.group(0).split('"')[0].split('&')[0]
    cmd = f'curl -sL -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" "{bandcamp_url}"'
    success, stdout, _ = run_cmd(cmd)
    if success:
        img_match = re.search(r'"og:image"\s+content="([^"]+)"', stdout)
        if img_match:
            return img_match.group(1)
    return None

def search_soundcloud(artist, title):
    """Search SoundCloud for track info and cover art."""
    if not artist and not title:
        return None, None
    query = f"{artist} {title}".strip()
    if not query:
        return None, None
    url = f"https://api.soundcloud.com/tracks?q={query.replace(' ', '%20')}&client_id=YOUR_CLIENT_ID"
    return None, None

def search_soundcloud_web(artist, title, filename=""):
    """Search SoundCloud via web for track info and cover art."""
    if not artist and not title and not filename:
        return None, None
    
    sc_handles = re.findall(r'\[([a-z0-9_]+)\]', (filename or "").lower())
    
    cleaned_title = title
    for handle in sc_handles:
        cleaned_title = re.sub(r'\[' + handle + r'\]', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = re.sub(r'\([^)]*\)', '', cleaned_title)
    cleaned_title = re.sub(r'\[[^\]]*\]', '', cleaned_title)
    cleaned_title = re.sub(r'[_-]+', '-', cleaned_title)
    track_base = cleaned_title.lower().replace('(', '-').replace(')', '').replace(' ', '-')
    for kw in ['remix', 'edit', 'mix', 'master', 'loud', 'dub', 'clean', 'explicit', 'instrumental', 'acappella', 'radio', 'original', 'free', 'download']:
        track_base = re.sub(rf'-{kw}-?', '-', track_base)
    track_base = re.sub(r'-+', '-', track_base).strip('-')
    
    artist_slug = artist.lower().replace(' ', '-') if artist else ''
    
    searched = set()
    
    for handle in sc_handles:
        if len(handle) >= 3:
            for slug in [f"{artist_slug}-{track_base}-{handle}", f"{handle}-{track_base}", f"{track_base}-{handle}"]:
                slug = re.sub(r'-+', '-', slug).strip('-')
                if slug and len(slug) >= 3:
                    for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                        sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                        if sc_url not in searched:
                            searched.add(sc_url)
                            img_url = fetch_soundcloud_cover(sc_url)
                            if img_url:
                                return (artist, title), img_url
    
    for handle in sc_handles:
        if len(handle) >= 3:
            sc_url = f"https://soundcloud.com/{handle}"
            if sc_url not in searched:
                searched.add(sc_url)
                img_url = fetch_soundcloud_cover(sc_url)
                if img_url:
                    return (artist, title), img_url
    
    if not sc_handles and (artist or title):
        potential_handles = []
        if artist:
            artist_clean = re.sub(r'[^\w]', '', artist).lower()
            if len(artist_clean) >= 3:
                potential_handles.append(artist_clean)
            parts = artist.split()
            for part in parts:
                part_clean = re.sub(r'[^\w]', '', part).lower()
                if len(part_clean) >= 4:
                    potential_handles.append(part_clean)
        
        for handle in potential_handles:
            for slug in [f"{artist_slug}-{track_base}", f"{track_base}"]:
                slug = re.sub(r'-+', '-', slug).strip('-')
                if slug and len(slug) >= 3:
                    for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                        full_slug = f"{slug}{suffix}"
                        sc_url = f"https://soundcloud.com/{handle}/{full_slug}"
                        if sc_url not in searched:
                            searched.add(sc_url)
                            img_url = fetch_soundcloud_cover(sc_url)
                            if img_url:
                                return (artist, title), img_url
    
    if not sc_handles and (artist or title):
        common_handles = ['gsfreedls', 'freedldownload', 'freedownload', 'free download', 'mp3', 'zippyshare', 'mediafire', 'downloadfree', 'freedls']
        for slug in [f"{artist_slug}-{track_base}", f"{track_base}"]:
            slug = re.sub(r'-+', '-', slug).strip('-')
            if slug and len(slug) >= 3:
                for suffix in ['', '-free-download', '-free', '-download', '-dub', '-loud', '-master']:
                    for handle in common_handles:
                        sc_url = f"https://soundcloud.com/{handle}/{slug}{suffix}"
                        if sc_url not in searched:
                            searched.add(sc_url)
                            img_url = fetch_soundcloud_cover(sc_url)
                            if img_url:
                                return (artist, title), img_url
    
    return None, None

def fetch_soundcloud_cover(sc_url):
    """Fetch cover art from a SoundCloud page."""
    headers = '-A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" -H "Accept-Language: en-US,en;q=0.5"'
    cmd = f'curl -sL {headers} "{sc_url}"'
    success, stdout, _ = run_cmd(cmd)
    if success:
        img_match = re.search(r'"og:image"\s+content="([^"]+)"', stdout)
        if img_match:
            return img_match.group(1)
        img_match = re.search(r'(https?://i1\.sndcdn\.com/artworks-[\w-]+\.png|https?://i1\.sndcdn\.com/artworks-[\w-]+\.jpg)', stdout)
        if img_match:
            return img_match.group(0)
    return None

def search_all_sources(artist, title):
    """Search all online sources for track metadata and cover art.
    Returns: (metadata dict, cover_url)
    """
    result_metadata = {}
    cover_url = None
    
    if not artist and not title:
        return result_metadata, cover_url
    
    sources = [
        ("Dezer", lambda a, t: (None, search_deezer_cover(a, t))),
        ("Bandcamp", lambda a, t: (None, search_bandcamp_cover(a, t))),
    ]
    
    for source_name, search_func in sources:
        found_artist, found_cover = search_func(artist, title)
        if found_cover and not cover_url:
            cover_url = found_cover
            print(f"  {source_name} cover found")
    
    return result_metadata, cover_url

def extract_metadata_from_filename(filename):
    """Extract artist and title from filename.
    
    Rules:
    - First " - " separates Artist from Title
    - Everything after first " - " is the Title (remix, edit, feat, etc.)
    - No artist info in filename? Return empty artist
    """
    name = Path(filename).stem.strip()
    
    if ' - ' in name:
        parts = name.split(' - ', 1)
        artist = parts[0].strip()
        title = parts[1].strip()
        return artist, title
    
    return '', name.strip()

def clean_title_for_search(title):
    """Remove remix/edit/etc. info from title for cover art search.
    
    Removes any bracket (with nested content) if it contains remix/edit/etc. keywords.
    """
    import re
    
    keywords = r'(?:remix|edit|mix|flip|rework|cover|feat|ft\.|featuring|radio|clean|explicit|instrumental|acappella)'
    
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
                    if text[idx] == opener:
                        end = find_matching_paren(text, idx)
                        if end > idx:
                            content = text[idx+1:end]
                            if re.search(keywords, content, re.IGNORECASE):
                                text = text[:idx] + text[end+1:]
                                removed_something = True
                                break
                    idx += 1
        return text.strip()
    
    return strip_brackets(title)

def download_cover(url, output_path):
    """Download cover art from URL."""
    cmd = f'curl -sL "{url}" -o "{output_path}"'
    success, _, _ = run_cmd(cmd)
    return success

def process_cover(cover_path, output_path):
    """Process cover art to 600x600."""
    cmd = f'ffmpeg -y -i "{cover_path}" -vf "scale=600:600:force_original_aspect_ratio=decrease,pad=600:600:(ow-iw)/2:(oh-ih)/2" -frames:v 1 -q:v 2 "{output_path}" 2>/dev/null'
    success, _, _ = run_cmd(cmd)
    return success

def encode_aac(wav_path, output_path, metadata, gain_db):
    """Encode WAV to AAC with metadata."""
    cmd = f'ffmpeg -y -i "{wav_path}" -map 0:a -af "volume={gain_db}dB" -c:a aac -b:a 320k'
    for key, value in metadata.items():
        if value and isinstance(value, str):
            cmd += f' -metadata {key}="{value}"'
    cmd += f' -movflags +use_metadata_tags "{output_path}"'
    success, _, stderr = run_cmd(cmd)
    return success

def embed_cover(m4a_path, cover_path, final_path):
    """Embed cover art into M4A."""
    cmd = f'ffmpeg -y -i "{m4a_path}" -i "{cover_path}" -c:a copy -c:v copy -map 0:a -map 1:v -disposition:1 attached_pic "{final_path}"'
    success, _, _ = run_cmd(cmd)
    return success

def verify_output(m4a_path) -> tuple[bool, dict[str, bool] | str]:
    """Verify M4A output."""
    cmd = f'ffprobe -v quiet -show_format -show_streams "{m4a_path}"'
    success, stdout, _ = run_cmd(cmd)
    if not success:
        return False, "Failed to read file"
    
    has_aac = 'codec_name=aac' in stdout
    has_cover = 'attached_pic=1' in stdout
    info: dict[str, bool] = {"aac": has_aac, "cover": has_cover}
    return True, info

def save_result_json(wav_path, metadata, loudness, output_name, success, has_cover=False):
    """Save conversion result to JSON file."""
    result = {
        "source_wav": str(wav_path),
        "output_m4a": output_name if success else None,
        "success": success,
        "metadata": metadata,
        "loudness": loudness,
        "has_cover": has_cover
    }
    json_path = Path(wav_path).with_suffix('.json')
    with open(json_path, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"  Result saved to: {json_path}")

def convert_file(wav_path):
    """Convert a single WAV file to AAC."""
    print(f"Processing: {wav_path}")
    
    wav_path = str(wav_path)
    base_name = Path(wav_path).stem
    output_name = base_name + '.m4a'
    
    file_hash = hash(wav_path) % 1000000
    temp_cover = f'cover_{file_hash}.jpg'
    temp_output = f'output_{file_hash}.m4a'
    
    # Step 1: Loudness analysis
    loudness = analyze_loudness(wav_path)
    if not loudness:
        print(f"  FAIL: Loudness analysis failed")
        return False, None
    print(f"  Loudness: {loudness.get('input_i', 'N/A')} LUFS, True Peak: {loudness.get('input_tp', 'N/A')} dB")
    
    # Calculate gain (reduce if true peak would clip)
    input_tp = float(loudness.get('input_tp', -10))
    gain_db = min(0, -0.1 - input_tp)
    
    # Step 2: Extract metadata
    metadata = extract_metadata(wav_path)
    print(f"  Metadata: {metadata}")
    
    # Step 3: If no metadata, try to extract from filename
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
    
    # Clean metadata - keep only string fields
    metadata = {k: v for k, v in metadata.items() if isinstance(v, str)}
    
    # Step 4: Extract cover art from source first, then search online if not found
    cover_path = temp_cover
    web_metadata = None
    
    # Try extracting cover from source first
    cmd = f'ffmpeg -y -i "{wav_path}" -map 0:v -map -0:a -c:v copy "{cover_path}" 2>/dev/null'
    success, _, _ = run_cmd(cmd)
    if Path(cover_path).exists():
        print(f"  Cover: Extracted from source")
    else:
        # Source has no cover - search online
        search_title_clean = clean_title_for_search(search_title)
        
        # Try Deezer
        cover_url = search_deezer_cover(search_artist, search_title_clean)
        if cover_url:
            download_cover(cover_url, temp_cover)
            print(f"  Cover: Downloaded from Deezer")
        # Try Bandcamp if Deezer failed
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
        
        # Check if online search succeeded
        if not Path(cover_path).exists():
            cover_path = None
            print(f"  Cover: Not found")
    
    # Step 5: Encode to AAC
    success = encode_aac(wav_path, temp_output, metadata, gain_db)
    if not success:
        print(f"  FAIL: Encoding failed")
        save_result_json(wav_path, metadata, loudness, output_name, False, False)
        for f in [temp_output, temp_cover]:
            if f and Path(f).exists():
                os.remove(f)
        return False, None
    
    # Step 6: Embed cover art
    if cover_path and Path(cover_path).exists():
        embed_success = embed_cover(temp_output, cover_path, output_name)
        if embed_success:
            if Path(cover_path).exists():
                os.remove(cover_path)
            if Path(temp_output).exists():
                os.remove(temp_output)
        else:
            print(f"  FAIL: Cover embedding failed")
            save_result_json(wav_path, metadata, loudness, output_name, False, False)
            for f in [temp_output, temp_cover]:
                if f and Path(f).exists():
                    os.remove(f)
            return False, None
    else:
        os.rename(temp_output, output_name)
    
    # Step 7: Verify
    valid, result = verify_output(output_name)
    info = result if isinstance(result, dict) else {}
    if valid:
        print(f"  SUCCESS: {output_name} (AAC: {info.get('aac')}, Cover: {info.get('cover')})")
        return True, output_name
    else:
        print(f"  FAIL: Verification failed - {result}")
        save_result_json(wav_path, metadata, loudness, output_name, False, bool(info.get('cover')))
        return False, None

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python convert.py <wav_file>")
        sys.exit(1)
    
    wav_path = sys.argv[1]
    success, output = convert_file(wav_path)
    sys.exit(0 if success else 1)
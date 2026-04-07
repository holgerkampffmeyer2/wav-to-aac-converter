#!/usr/bin/env python3
"""Audio processing functions (FFmpeg, encoding, loudness) for wav-to-aac-converter."""

import subprocess
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from src.utils import (
    ENCODE_TIMEOUT,
    DEFAULT_BITRATE,
    COVER_DIMENSIONS,
    run_cmd as util_run_cmd,
    to_ascii_filename
)

logger = logging.getLogger(__name__)


def run_cmd(cmd: str, capture_output: bool = True, timeout: int = ENCODE_TIMEOUT) -> Tuple[bool, str, str]:
    """Run shell command and return output."""
    return util_run_cmd(cmd, capture_output, timeout)


def analyze_loudness(wav_path: str) -> Optional[Dict[str, Any]]:
    """Analyze loudness of WAV file using first 5 minutes for speed."""
    import json
    cmd = f'ffmpeg -t 300 -i "{wav_path}" -af loudnorm=print_format=json -f null - 2>&1'
    success, stdout, stderr = run_cmd(cmd)
    if not success:
        return None
    output = stdout + stderr
    try:
        start = output.index('{')
        end = output.rindex('}') + 1
        data = output[start:end]
        return json.loads(data)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"Loudness analysis parse error: {e}")
        return None


def encode_audio(wav_path: str, output_path: str, metadata: Dict[str, Any], gain_db: float, fmt: str) -> bool:
    """Encode WAV to MP3/M4A with metadata."""
    if fmt == 'mp3':
        codec = 'libmp3lame'
        extra_args = ''
    elif fmt == 'm4a':
        codec = 'aac'
        extra_args = '-movflags +use_metadata_tags'
    else:
        raise ValueError(f"Unsupported format: {fmt}")
    
    cmd = f'ffmpeg -y -i "{wav_path}" -map 0:a -af "volume={gain_db}dB" -c:a {codec} -b:a {DEFAULT_BITRATE}'
    for key, value in metadata.items():
        if value and isinstance(value, str):
            cmd += f' -metadata {key}="{value}"'
    if extra_args:
        cmd += f' {extra_args}'
    cmd += f' "{output_path}"'
    success, _, stderr = run_cmd(cmd)
    return success


def process_cover(cover_path: str, output_path: str) -> bool:
    """Process cover art to 600x600."""
    cmd = f'ffmpeg -y -i "{cover_path}" -vf "scale={COVER_DIMENSIONS}:{COVER_DIMENSIONS}:force_original_aspect_ratio=decrease,pad={COVER_DIMENSIONS}:{COVER_DIMENSIONS}:(ow-iw)/2:(oh-ih)/2" -frames:v 1 -q:v 2 "{output_path}" 2>/dev/null'
    success, _, _ = run_cmd(cmd)
    return success


def embed_cover(input_path: str, cover_path: str, final_path: str, fmt: str) -> bool:
    """Embed cover art into audio file."""
    logger.info(f"embed_cover called: input={input_path}, cover={cover_path}, final={final_path}, fmt={fmt}")
    if fmt == 'mp3':
        cmd = f'ffmpeg -y -i "{input_path}" -i "{cover_path}" -map 0:a -map 1:v -c copy -id3v2_version 3 -metadata:s:v title="Album cover" -metadata:s:v comment="Cover (front)" "{final_path}" 2>/dev/null'
    elif fmt == 'm4a':
        cmd = f'ffmpeg -y -i "{input_path}" -i "{cover_path}" -c copy -map 0:a -map 1:v -disposition:v:0 attached_pic "{final_path}" 2>/dev/null'
    else:
        return False
    
    logger.info(f"Running embed command: {cmd[:100]}...")
    result = run_cmd(cmd)
    logger.info(f"run_cmd result: {result}, type: {type(result)}")
    
    success, stdout, stderr = result
    logger.info(f"success: {success}, stdout: {stdout[:100] if stdout else 'empty'}, stderr: {stderr[:100] if stderr else 'empty'}")
    
    return success


def find_local_cover(wav_path: str) -> Optional[str]:
    """Find cover art in local folder with fuzzy matching.
    
    Priority: cover.png/jpg -> exact filename -> fuzzy match -> any image
    """
    from pathlib import Path
    import re
    
    wav_dir = Path(wav_path).parent
    wav_stem = Path(wav_path).stem
    
    def normalize(s: str) -> str:
        return re.sub(r'[-_\s]+', '', s.lower())
    
    normalized = normalize(wav_stem)
    
    for ext in ('.png', '.jpg', '.jpeg'):
        candidates = [
            wav_dir / f"cover{ext}",
            wav_dir / f"{wav_stem}{ext}",  # exact
        ]
        for cand in candidates:
            if cand.exists():
                return str(cand)
        
        for img in wav_dir.glob(f"*{ext}"):
            if normalize(img.stem) == normalized:
                return str(img)
    
    for ext in ('.png', '.jpg', '.jpeg'):
        for img in wav_dir.glob(f"*{ext}"):
            return str(img)
    
    return None


def download_cover(url: str, output_path: str) -> bool:
    """Download cover art from URL using curl for binary data."""
    cmd = f'curl -sL -m 30 -o "{output_path}" "{url}"'
    success, _, _ = run_cmd(cmd)
    return success and Path(output_path).exists()
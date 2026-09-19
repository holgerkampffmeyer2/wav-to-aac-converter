#!/usr/bin/env python3
"""WAV/AIFF/FLAC to MP3/M4A converter with loudness normalization, metadata, and cover art."""

import argparse
import logging
import shutil
import sys
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

# Import from modules
try:
    from . import __version__
except ImportError:
    __version__ = "unknown"
from .utils import (
    logger,
    load_config,
    to_ascii_filename,
    clean_title_for_search,
    validate_soundcloud_client_id,
    DEFAULT_TIMEOUT,
    DEFAULT_BITRATE,
    ENCODE_TIMEOUT,
    RETRY_ATTEMPTS,
    SEARCH_TIMEOUT,
    fetch_url,
    run_cmd
)

from .audio_processing import (
    analyze_loudness,
    measure_output_true_peak,
    encode_audio,
    process_cover,
    embed_cover as audio_embed_cover,
    find_local_cover,
    download_cover,
    run_cmd as audio_run_cmd
)

from .metadata import (
    extract_metadata,
    lookup_online_metadata,
    extract_metadata_from_filename,
    run_cmd as metadata_run_cmd
)

from .cover_art import (
    search_deezer_cover,
    search_musicbrainz_cover,
    search_bandcamp_cover,
    search_all_sources,
    enrich_and_search_cover
)


def save_result_json(wav_path: str, metadata: Dict[str, Any], loudness: Optional[Dict[str, Any]], output_name: str, success: bool, has_cover: bool = False, fmt: str = 'mp3', warning: str = ''):
    """Save conversion result to JSON."""
    import json
    from pathlib import Path
    
    result = {
        "wav_file": wav_path,
        "output_file": output_name,
        "success": success,
        "format": fmt,
        "has_cover": has_cover,
        "metadata": metadata,
    }
    if loudness:
        result["loudness"] = loudness
    if warning:
        result["warning"] = warning
    
    json_path = Path(output_name).with_suffix('.json')
    with open(json_path, 'w') as f:
        json.dump(result, f, indent=2)


def verify_output(output_path: str, fmt: str) -> Tuple[bool, Dict[str, bool]]:
    """Verify output file."""
    if not Path(output_path).exists():
        return False, {"error": "File not found"}
    
    cmd = f'ffprobe -v quiet -show_format -show_streams "{output_path}"'
    success, stdout, _ = run_cmd(cmd)
    
    if not success:
        return False, {"error": "ffprobe failed"}
    
    # Check codec
    is_mp3 = 'codec_name=mp3' in stdout or 'codec_name=libmp3lame' in stdout
    is_m4a = 'codec_name=aac' in stdout
    
    if fmt == 'mp3':
        codec_ok = is_mp3
    else:
        codec_ok = is_m4a
    
    # Check for cover
    has_cover = 'attached_pic=1' in stdout or 'Stream' in stdout and 'Video' in stdout
    
    return codec_ok, {"mp3": is_mp3, "m4a": is_m4a, "cover": has_cover}

def compute_loudness_gain(input_tp: float, fmt: str, config: Dict[str, Any],
                          mode: Optional[str] = None) -> Tuple[float, bool]:
    """Compute the volume gain (dB) and clipping-risk flag from the source true peak.

    Returns ``(gain_db, risk)``:
    - ``risk`` is True when the source true peak sits above ``risk_threshold_db``
      (near/over 0 dBFS), i.e. lossy codecs may overshoot the output peak.
    - In ``fast`` mode a per-codec reserve gain is subtracted on the risky path
      (no guarantee) so a warning can be emitted instead of silent clipping.
    - ``verify``/``off`` modes keep the legacy ``input_tp``-based gain; verify
      additionally corrects the output in a measure loop.
    """
    loudness_cfg = config.get('loudness', {}) or {}
    actual_mode = mode or config.get('loudness_mode') or loudness_cfg.get('mode', 'fast')
    risk_threshold = float(loudness_cfg.get('risk_threshold_db', -2.0))
    reserve_key = 'reserve_aac_db' if fmt == 'm4a' else 'reserve_mp3_db'
    reserve = float(loudness_cfg.get(reserve_key, 0.0))

    risk = input_tp > risk_threshold
    base_gain = min(0, -0.1 - input_tp)
    gain_db = (base_gain - reserve) if (actual_mode == 'fast' and risk) else base_gain
    return gain_db, risk


def convert_file(wav_path: str, fmt: str = 'mp3', embed_cover: bool = True, config: Dict[str, Any] = None) -> Tuple[bool, Optional[str]]:
    """Convert a single WAV file to MP3 or M4A."""
    original_wav_path = wav_path
    temp_dir = None
    
    if config is None:
        config = load_config()
    
    try:
        path_obj = Path(wav_path)
        ascii_stem = to_ascii_filename(path_obj.stem)
        
        if ascii_stem:
            temp_dir = tempfile.mkdtemp(prefix='wav2aac_')
            ascii_filename_path = Path(temp_dir) / (ascii_stem + path_obj.suffix)
            shutil.copy2(original_wav_path, ascii_filename_path)
            wav_path = str(ascii_filename_path)
            if ascii_stem != path_obj.stem:
                logger.info(f"  Using ASCII filename: {ascii_filename_path.name}")
            else:
                logger.info(f"  Using filename: {ascii_filename_path.name} (already ASCII)")
        
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
        
        target_tp = float((config.get('loudness', {}) or {}).get('target_tp', -0.5))
        max_retries = int((config.get('loudness', {}) or {}).get('max_retries', 2))

        input_tp = float(loudness.get('input_tp', -10))
        loudness_mode = config.get('loudness_mode') or (config.get('loudness', {}) or {}).get('mode', 'fast')
        gain_db, risk = compute_loudness_gain(input_tp, fmt, config, loudness_mode)
        if risk:
            logger.info(f"  Loudness mode: {loudness_mode} (Risiko: Quell-TP {input_tp:.2f} dBTP über Schwelle)")
        
        metadata, cover_source = enrich_and_search_cover(wav_path, base_name, config, original_wav_path)
        
        search_artist = metadata.get('artist', '')
        search_title = metadata.get('title', '')
        
        logger.info(f"  Metadata: {search_artist} – {search_title}")
        
        metadata = {k: v for k, v in metadata.items() if isinstance(v, str)}
        
        success = encode_audio(wav_path, temp_output, metadata, gain_db, fmt)
        
        if success and loudness_mode == 'verify':
            measured_tp = None
            for _attempt in range(max_retries + 1):
                measured_tp = measure_output_true_peak(temp_output)
                if measured_tp is None or measured_tp <= target_tp:
                    break
                adjust = target_tp - measured_tp
                gain_db = gain_db + adjust
                logger.info(f"  Verify: Ausgabe-TP {measured_tp:.2f} dBTP > Ziel {target_tp} dBTP, korrigiere Gain um {adjust:.2f} dB → {gain_db:.2f} dB")
                success = encode_audio(wav_path, temp_output, metadata, gain_db, fmt)
                if not success:
                    break
            if success and measured_tp is not None and measured_tp > target_tp:
                logger.warning(f"  ⚠ Ausgabe true peak rel. {measured_tp:.2f} dBTP konnte auch nach {max_retries} Korrektur(en) nicht unter {target_tp} dBTP gebracht werden")
        
        if not success:
            logger.error(f"  Encoding failed")
            save_result_json(wav_path, metadata, loudness, output_name, False, False, fmt)
            for f in [temp_output, temp_cover]:
                if f and Path(f).exists():
                    os.remove(f)
            return False, None
        
        cover_path = None
        
        if embed_cover and cover_source:
            if cover_source.startswith('http'):
                from .audio_processing import download_cover
                if download_cover(cover_source, temp_cover):
                    cover_path = temp_cover
                    logger.info(f"  Cover: Downloaded from online source")
            elif Path(cover_source).exists():
                cover_path = cover_source
                logger.info(f"  Cover: Using local/extracted cover")
        
        if not cover_path:
            logger.debug(f"  Cover: Not found")
        
        if cover_path and Path(cover_path).exists():
            logger.info(f"  Embedding cover: {cover_path}")
            try:
                embed_success = audio_embed_cover(temp_output, cover_path, output_name, fmt)
                logger.info(f"  Embed result: {embed_success}, type: {type(embed_success)}")
            except Exception as e:
                logger.error(f"  Embed exception: {e}")
                embed_success = False
            
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
            if risk and loudness_mode != 'verify':
                measured_tp = measure_output_true_peak(output_name)
                if measured_tp is not None and measured_tp > target_tp:
                    logger.warning(
                        f"  ⚠ Ausgabe true peak: {measured_tp:.2f} dBTP > Ziel {target_tp} dBTP "
                        f"(Quell-TP {input_tp:.2f} dBTP) — Quelle liegt nahe/über 0 dBFS und überschwingt "
                        f"im {fmt.upper()}-Codec; für garantierten Peak: --loudness verify"
                    )
            if temp_dir and Path(temp_dir).exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            return True, output_name
        else:
            logger.error(f"  FAIL: Verification failed - {result}")
            save_result_json(wav_path, metadata, loudness, output_name, False, bool(info.get('cover')), fmt)
            if temp_dir and Path(temp_dir).exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            return False, None
            
    except Exception as e:
        logger.error(f"  Conversion error: {e}")
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        return False, None


def _convert_file_wrapper(args):
    """Wrapper for parallel processing."""
    wav_path, fmt, embed_cover, config = args
    success, output = convert_file(wav_path, fmt, embed_cover, config)
    return (wav_path, success, output)


def convert_batch(file_paths, fmt='mp3', parallel=True, max_workers=5, embed_cover=True, config=None):
    """Convert multiple WAV files."""
    if config is None:
        config = load_config()
    
    results = []
    
    if not parallel or len(file_paths) < 4:
        for wav_path in file_paths:
            results.append(_convert_file_wrapper((wav_path, fmt, embed_cover, config)))
        return results
    
    logger.info(f"Converting {len(file_paths)} files in parallel (max {max_workers} workers)...")
    
    with ProcessPoolExecutor(max_workers=min(max_workers, len(file_paths))) as executor:
        futures = {executor.submit(_convert_file_wrapper, (fp, fmt, embed_cover, config)): fp for fp in file_paths}
        for future in as_completed(futures):
            results.append(future.result())
    
    return results


def parse_args():
    """Parse command line arguments."""
    config = load_config()
    
    parser = argparse.ArgumentParser(
        description='Convert WAV to MP3/M4A with metadata and cover art',
        epilog='Author: Holger Kampffmeyer (DJ Hulk) — https://holger-kampffmeyer.de'
    )
    parser.add_argument('--version', action='version', version=f'audioconvert {__version__}')
    parser.add_argument('files', nargs='+', help='WAV/AIFF/FLAC file(s) to convert')
    parser.add_argument('--format', default=config.get('output_format', 'mp3'), choices=['mp3', 'm4a'], help='Output format')
    parser.add_argument('--m4a', action='store_true', help='Output to M4A format')
    parser.add_argument('--max-workers', type=int, default=config.get('max_parallel_processes', 5), help='Max parallel processes')
    parser.add_argument('--no-cover', action='store_false', default=config.get('embed_cover', True), dest='embed_cover', help='Disable cover art embedding')
    parser.add_argument('--no-loudnorm', action='store_false', default=config.get('loudnorm', True), dest='loudnorm', help='Disable loudness normalization')
    parser.add_argument('--loudness', choices=['fast', 'verify', 'off'], default=config.get('loudness', {}).get('mode', 'fast'),
                        help='Loudness mode: fast (single-pass + warning when verify is needed), verify (checks and corrects output true peak), off (legacy input_tp gain only)')
    parser.add_argument('--retry-attempts', type=int, default=config.get('retry_attempts', 3), help='Retry attempts')
    parser.add_argument('--timeout', type=int, default=config.get('timeout_seconds', 30), help='Timeout in seconds')
    
    metadata_default = config.get('metadata', {}).get('enabled', True)
    parser.add_argument('--no-metadata', action='store_false', default=metadata_default, dest='metadata_lookup', help='Disable online metadata lookup and enrichment')
    parser.add_argument('--offline', action='store_true', default=config.get('metadata', {}).get('offline', False), help='Offline mode: no online lookups, local cover only')
    
    return parser.parse_args()


def main():
    """Main entry point for the converter."""
    logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
    
    args = parse_args()
    
    config = load_config()
    if 'metadata' not in config:
        config['metadata'] = {}
    if not args.metadata_lookup:
        config['metadata']['enabled'] = False
    if args.offline:
        config['metadata']['enabled'] = False
        config['metadata']['offline'] = True
    if 'loudness' not in config:
        config['loudness'] = {}
    config['loudness_mode'] = 'off' if not args.loudnorm else args.loudness
    
    if not args.offline and config['metadata'].get('enabled', True):
        validate_soundcloud_client_id()
    
    audio_extensions = ('.wav', '.WAV', '.aif', '.aiff', '.AIF', '.AIFF', '.flac', '.FLAC')
    audio_files = [f for f in args.files if f.lower().endswith(audio_extensions)]
    
    if not audio_files:
        logger.error("Error: No WAV/AIFF/FLAC files found")
        sys.exit(1)
    
    if args.m4a:
        fmt = 'm4a'
    else:
        fmt = args.format
    
    embed_cover = args.embed_cover
    
    logger.info(f"Output format: {fmt.upper()}")
    
    if len(audio_files) == 1:
        success, output = convert_file(audio_files[0], fmt, embed_cover, config)
        sys.exit(0 if success else 1)
    
    results = convert_batch(audio_files, fmt, parallel=(len(audio_files) >= 4), max_workers=args.max_workers, embed_cover=embed_cover, config=config)
    
    success_count = sum(1 for _, s, _ in results if s)
    logger.info(f"\nBatch complete: {success_count}/{len(results)} succeeded")
    
    sys.exit(0 if success_count == len(results) else 1)
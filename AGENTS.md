# Audio Conversion: WAV/AIFF/FLAC to MP3/M4A

AI agent workflow for converting WAV/AIFF/FLAC files to MP3 or M4A with loudness normalization, metadata, and cover art. Designed for AI coding assistants like [opencode](https://opencode.ai) or Claude Code.

## Agent Instructions

When an AI agent encounters this project, it should:
1. Read this file to understand the conversion workflow
2. Check prerequisites (Pre-flight Check below)
3. Execute `convert.py` with appropriate arguments
4. Monitor for errors and handle retries
5. Verify results and report to user

## Pre-flight Check

Before starting, verify all requirements are met:

```bash
# Check ffmpeg installation
ffmpeg -version || echo "ERROR: ffmpeg not installed"

# Check ffprobe installation  
ffprobe -version || echo "ERROR: ffprobe not installed"

# Check Python installation
python3 --version || echo "ERROR: python3 not installed"
```

If any tool is missing, install with:
```bash
sudo apt update && sudo apt install ffmpeg python3
```

## Quick Start

```bash
# MP3 output (default)
python3 convert.py <file.wav>              # Single file
python3 convert.py *.wav                   # Batch (auto-parallel for 4+ files)
python3 convert.py *.aiff                 # AIFF files also supported
python3 convert.py *.flac                 # FLAC files also supported

# M4A output
python3 convert.py --m4a <file.wav>        # Single file to M4A
python3 convert.py --m4a *.wav             # Batch to M4A
python3 convert.py --m4a *.aiff *.wav     # Mixed WAV/AIFF/FLAC batch
python3 convert.py --m4a *.flac           # FLAC to M4A

# Offline mode (no online lookups, local cover only)
python3 convert.py --offline <file.wav>    # Single file offline
python3 convert.py --offline *.wav         # Batch offline

# Loudness control
python3 convert.py --loudness verify <file.wav>   # Measure output, guarantee no clipping
python3 convert.py --loudness fast <file.wav>     # Single pass + warning when verify is needed
python3 convert.py --loudness off <file.wav>      # Legacy gain only (no clipping protection)
```

## Output Format Selection

| Flag | Output | Codec |
|------|--------|-------|
| (default) | MP3 | libmp3lame, 320kbps |
| `--m4a` | M4A | AAC, 320kbps |
| `--offline` | Current | No online lookups, local cover only |
| `--loudness <mode>` | Any | `fast` (default) · `verify` · `off` |

Loudness modes work with any output format and are configured in the `loudness` block of `config.json` (see Technical Details).

## Workflow Steps

### Single File (Sequential)
```
Loudness Analysis → Enrich Metadata + Cover Search (combined) → Encoding → Embed Artwork → Verify
```

### Metadata Extraction Strategy
1. **Source tags**: Extract artist/title from embedded metadata via ffprobe
2. **Online lookup**: If tags missing, query sources in config order (default: SoundCloud → iTunes → Deezer → Bandcamp → MusicBrainz). Configurable via `metadata.sources` in `config.json`.
3. **Filename parsing**: Fallback to heuristic parsing of the filename (separators, brackets, etc.)

Note: Filename processing uses ASCII-converted versions to ensure compatibility with audio processing tools.

### Metadata Enrichment (configurable)
When `metadata.enabled` is true (default), missing tags are written to the WAV file:
- **label**: Looked up via iTunes (primary) or Bandcamp (fallback)
- **genre**: Looked up via iTunes → Bandcamp → MusicBrainz
- **album, year, track_number**: Looked up via iTunes
- Tags are written in a single ffmpeg call for efficiency
- Caching prevents duplicate API calls for the same track

### Cover Artwork Strategy
1. **Source file**: Extract embedded cover from source (WAV/FLAC/AIFF)
2. **Local folder**: Look for `cover.png`, `cover.jpg`, exact filename match, or a normalized substring match (e.g. `Mix194.png` matches `DJ Hulk - Mix194 - Afrohouse.wav`; longest match wins, min 3 chars). No fallback to arbitrary images.
3. **Web search**: Configurable via `metadata.sources` (default: SoundCloud → iTunes → Deezer → Bandcamp → MusicBrainz, skipped in `--offline` mode)

SoundCloud cover search uses the **SoundCloud API v2** (via `api-v2.soundcloud.com`) with **confidence scoring**. A `SOUNDCLOUD_CLIENT_ID` must be set in `.env`. Results below `soundcloud_confidence_threshold` (default: 0.6) are rejected and the next source is tried.

Remixes: a bracketed remixer in the filename (e.g. `ACTIN' TOUGH (LXRENZ REMIX)`) is extracted as a **hint**. Queries are then built including the uploader handle, and uploader/remix-marker agreement boosts (or penalises) candidates — so the actual remix (usually uploaded by the remixer handle) wins over the plain original release. Without a hint, the previous behavior applies unchanged.

Note: SoundCloud cover search iterates **all** candidate queries and returns the highest-confidence result **that has artwork**; falls back to the next source only if none matches.

### Batch Processing
- **Auto-detected**: 4+ files trigger parallel mode
- **Max workers**: 5 parallel processes
- **Fallback**: <4 files processed sequentially
- **Agent decision**: Check file count first, then choose mode

### Error Recovery

| Error | Recovery Action |
|-------|-----------------|
| Loudnorm fails | Skip loudness correction, encode with -3dB gain |
| Online API rate limited | Wait 60s, then retry or skip to next source |
| No cover found | Accept missing cover, continue encoding |
| Encoding fails | Check WAV file integrity, try with stripped metadata |
| All sources fail | Create output without cover, log warning |
| Online metadata lookup fails | Fallback to filename parsing |
| Enrich metadata fails | Continue without enrichment, log warning |

### Verification Checklist

After conversion, agent should verify:

- [ ] **Correct Codec**: MP3 (`codec_name=mp3`) or M4A (`codec_name=aac`)
- [ ] **True Peak within target**: ≤ `loudness.target_tp` dBTP (default -0.5) when using `--loudness verify`; with `fast` a warning may be emitted if verify is needed
- [ ] **Cover embedded** (if available): Check stream tags in ffprobe output
- [ ] **Metadata present**: Artist/Title visible in ffprobe output

```bash
# Verification command (MP3)
ffprobe -v quiet -show_format -show_streams "output.mp3"

# Verification command (M4A)
ffprobe -v quiet -show_format -show_streams "output.m4a"
```

## Known Filename Patterns

| Pattern | Artist | Title | SC-Handle |
|---------|--------|-------|-----------|
| `Artist - Title.wav` | Artist | Title | - |
| `Title [handle].wav` | (from SC) | Title | handle |
| `Artist - Title (Remix).wav` | Artist | Title (Remix) | - |
| `[handle] Track.wav` | (from SC) | Track | handle |

## Prerequisites

```bash
sudo apt install ffmpeg python3
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No cover found | Check filename has artist/title, local PNG/JPG, or embedded cover |
| API rate limited | Wait 60s, then retry batch |
| Loudnorm fails | Verify ffmpeg supports loudnorm filter |
| Metadata missing | Use "Artist - Title" filename format or ensure online services can find the track |
| Slow batch processing | Normal for 4+ files (parallel mode active) |

## Technical Details

- **Codecs**: MP3 (libmp3lame) or M4A/AAC, 320kbps
- **Loudness**: `loudness` block in `config.json`. `mode` (`fast` default, `verify`, `off`), `target_tp` (-0.5), `max_retries` (2), `risk_threshold_db` (-2.0), `reserve_aac_db` (2.5), `reserve_mp3_db` (1.5). `fast`: single pass; sources with true peak above the risk threshold get a codec-specific reserve gain, and a warning is logged if a follow-up `verify` run is advised. `verify`: measures the output true peak and re-encodes (up to `max_retries`) until ≤ `target_tp`. `off`: legacy gain only (`min(0, -0.1 - input_tp)`), no clipping protection.
- **Cover Sources**: Source (embedded) → Local folder (exact or substring match) → SoundCloud → iTunes → Deezer → Bandcamp → MusicBrainz
- **Retry Logic**: 3 attempts with exponential backoff
- **Metadata Sources**: Source tags → SoundCloud → iTunes → Deezer → Bandcamp → MusicBrainz → filename parsing (order configurable via `metadata.sources`)
- **Enrichment Tags**: label, genre, album, year, track_number (if metadata enabled)

## Testing

```bash
# Run all tests
python3 -m unittest tests.test_convert

# Run specific test class
python3 -m unittest tests.test_convert.TestFilenameParsing

# Run with verbose output
python3 -m unittest tests.test_convert -v
```

### Test Coverage

The test suite covers:
- Filename parsing (artist/title extraction)
- Metadata lookup (iTunes, Deezer, Bandcamp, MusicBrainz, SoundCloud)
- Cover art search (Deezer, SoundCloud, MusicBrainz, Bandcamp, local files)
- Loudness analysis and error handling
- Encoding and verification
- Batch processing (parallel/sequential)
- Edge cases (Unicode, special characters, empty values)
- Metadata enrichment (label, genre, album, year, track_number)

## Release Workflow

To create a new release:

1. **Bump version** in `src/__init__.py` (single source of truth):
   ```python
   __version__ = "1.1.0"
   ```

2. **Commit changes**:
   ```bash
   git add -A && git commit -m "chore: bump version to 1.1.0"
   git push
   ```

3. **Create tag and push**:
   ```bash
   git tag v1.1.0
   git push --tags
   ```

This triggers the GitHub Actions `release.yml` workflow which:
- Builds standalone binaries for Linux (amd64) and macOS (arm64, x86_64)
- Bundles static ffmpeg in each binary
- Creates a GitHub Release with all 3 archives

The version is defined only in `src/__init__.py`. `pyproject.toml` reads it dynamically via `[tool.setuptools.dynamic]`.

## OpenSpec Feature Development

This project uses OpenSpec for spec-driven development. To define and implement future features:

1. **Create a new change**:
   ```bash
   openspec new change "<feature-name>"
   ```
2. **Define artifacts**: Fill in `proposal.md`, `design.md`, `tasks.md`, and delta specs under `openspec/changes/<feature-name>/specs/`.
3. **Apply & Implement**: Implement the feature according to the specs and tasks.
4. **Archive & Sync**:
   ```bash
   openspec archive <feature-name> -y
   ```


## File Structure

```
wav-to-aac-converter/
├── .git/                  # Git repository
├── .github/               # GitHub workflows
├── .gitignore             # Git ignore rules
├── .opencode/             # OpenSpec agent workflows & commands
├── openspec/              # OpenSpec specifications & changes
├── assets/                # Images and static assets
├── src/                   # Source code
│   ├── __init__.py
│   ├── audio_processing.py    # Loudness analysis & encoding
│   ├── convert.py              # Main CLI script
│   ├── cover_art.py           # Cover art extraction & embedding
│   ├── metadata.py            # Metadata lookup & enrichment
│   └── utils.py              # Utilities
├── tests/                  # Test files
│   └── test_convert.py
├── AGENTS.md               # AI agent workflow instructions
├── README.md               # This file
├── LICENSE                # MIT license
├── config.json            # Configuration file
├── convert.py            # CLI entry point (wrapper)
├── install.sh            # One-line install script
├── pyproject.toml        # Python project config
├── *.wav / *.flac         # Source files
└── *.mp3 / *.m4a        # Converted output
```
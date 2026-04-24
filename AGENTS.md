# Audio Conversion: WAV to MP3/M4A

AI agent workflow for converting WAV files to MP3 or M4A with loudness normalization, metadata, and cover art. Designed for AI coding assistants like [opencode](https://opencode.ai) or Claude Code.

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

# M4A output
python3 convert.py --m4a <file.wav>        # Single file to M4A
python3 convert.py --m4a *.wav             # Batch to M4A
```

## Output Format Selection

| Flag | Output | Codec |
|------|--------|-------|
| (default) | MP3 | libmp3lame, 320kbps |
| `--m4a` | M4A | AAC, 320kbps |

## Workflow Steps

### Single File (Sequential)
```
Loudness Analysis → Enrich Metadata + Cover Search (combined) → Encoding → Embed Artwork → Verify
```

### Metadata Extraction Strategy
1. **WAV tags**: Extract artist/title from embedded metadata via ffprobe
2. **Online lookup**: If tags missing, query iTunes → Deezer → Bandcamp → MusicBrainz
3. **Filename parsing**: Fallback to heuristic parsing of the filename (separators, brackets, etc.)

Note: Filename processing uses ASCII-converted versions to ensure compatibility with audio processing tools.

### Metadata Enrichment (configurable)
When `enrich_metadata.enabled` is true (default), missing tags are written to the WAV file:
- **label**: Looked up via iTunes (primary) or Bandcamp (fallback)
- **genre**: Looked up via iTunes → Bandcamp → MusicBrainz
- **album, year, track_number**: Looked up via iTunes
- Tags are written in a single ffmpeg call for efficiency
- Caching prevents duplicate API calls for the same track

### Cover Artwork Strategy
1. **Source file**: Extract embedded cover from WAV
2. **Local folder**: Look for `cover.png`, `cover.jpg`, or matching image files
3. **Web search**: Deezer → MusicBrainz → Bandcamp

Note: Cover search stops at first successful match (early exit).

### Batch Processing
- **Auto-detected**: 4+ files trigger parallel mode
- **Max workers**: 5 parallel processes
- **Fallback**: <4 files processed sequentially
- **Agent decision**: Check file count first, then choose mode

### Error Recovery

| Error | Recovery Action |
|-------|-----------------|
| Loudnorm fails | Skip loudness correction, encode with -3dB gain |
| Deezer API rate limited | Wait 60s, then retry or skip to Bandcamp |
| No cover found | Accept missing cover, continue encoding |
| Encoding fails | Check WAV file integrity, try with stripped metadata |
| All sources fail | Create output without cover, log warning |
| Online metadata lookup fails | Fallback to filename parsing |
| Enrich metadata fails | Continue without enrichment, log warning |

### Verification Checklist

After conversion, agent should verify:

- [ ] **Correct Codec**: MP3 (`codec_name=mp3`) or M4A (`codec_name=aac`)
- [ ] **True Peak ≤ -0.1 dBTP**: Check with loudnorm analysis
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
- **Loudness**: True Peak ≤ -0.1 dBTP (auto-calculated gain)
- **Cover Sources**: Source (embedded) → Local folder → Deezer → MusicBrainz → Bandcamp
- **Retry Logic**: 3 attempts with exponential backoff
- **Metadata Sources**: WAV tags → iTunes → Deezer → Bandcamp → MusicBrainz → filename parsing
- **Enrichment Tags**: label, genre, album, year, track_number (if enrich_metadata enabled)

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
- Metadata lookup (iTunes, Deezer, Bandcamp, MusicBrainz)
- Cover art search (Deezer, MusicBrainz, Bandcamp, local files)
- Loudness analysis and error handling
- Encoding and verification
- Batch processing (parallel/sequential)
- Edge cases (Unicode, special characters, empty values)
- Metadata enrichment (label, genre, album, year, track_number)

## File Structure

```
wav-to-aac-converter/
├── .git/                  # Git repository
├── .github/               # GitHub workflows
├── .gitignore             # Git ignore rules
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
├── pyproject.toml        # Python project config
├── *.wav                 # Source files
└── *.mp3 / *.m4a        # Converted output
```
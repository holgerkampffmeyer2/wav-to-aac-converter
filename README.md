# wav-to-mp3-converter

![AI-Powered Audio Conversion](assets/ai-powered.png)

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://github.com/holgerkampffmeyer2/wav-to-aac-converter)
[![License](https://img.shields.io/github/license/holgerkampffmeyer2/wav-to-aac-converter)](https://github.com/holgerkampffmeyer2/wav-to-aac-converter)

AI-agent driven WAV to MP3/M4A conversion with loudness normalization, metadata extraction, and cover art embedding.

## How It Works

An AI agent reads `AGENTS.md` and executes the conversion workflow:

```
AI Agent reads AGENTS.md → Pre-flight Check → Executes convert.py → Monitors results → Verifies output
```

The agent handles:
- Prerequisites check (ffmpeg, python3)
- File discovery and batch processing decisions
- Loudness analysis and gain calculation
- Metadata extraction from files, online lookup (iTunes → Deezer → Bandcamp → MusicBrainz), or filename parsing
- Cover art search: embedded → local folder → Deezer → MusicBrainz → Bandcamp
- Error recovery and retries
- Verification of output quality

## Configuration

The converter can be configured using a `config.json` file in the same directory as `convert.py`. Command-line arguments override config values.

### Default config.json:
```json
{
  "output_format": "mp3",
  "max_parallel_processes": 5,
  "loudnorm": true,
  "embed_cover": true,
  "retry_attempts": 3,
  "timeout_seconds": 30,
  "fuzzy_threshold": 0.8,
  "metadata": {
    "enabled": true,
    "sources": ["itunes", "bandcamp", "musicbrainz", "deezer"],
    "fallback_to_filename": true,
    "enrich_tags": ["label", "genre", "album", "year", "track_number"],
    "label_source_tag": "label"
  }
}
```

### Configuration Options:
- `output_format`: Output format - "mp3" or "m4a" (default: mp3)
- `max_parallel_processes`: Maximum parallel processes (default: 5)
- `loudnorm`: Enable loudness normalization (default: true)
- `embed_cover`: Embed cover art (default: true)
- `retry_attempts`: Retry attempts for failed operations (default: 3)
- `timeout_seconds`: Timeout in seconds for operations (default: 30)
- `fuzzy_threshold`: Similarity threshold for fuzzy matching (0.0-1.0, default: 0.8)
- `metadata.enabled`: Enable online metadata lookup and enrichment (default: true)
- `metadata.sources`: Online sources to use (default: itunes, bandcamp, musicbrainz, deezer)
- `metadata.fallback_to_filename`: Fallback to filename parsing if no metadata found (default: true)
- `metadata.enrich_tags`: Tags to write when enriching (default: label, genre, album, year, track_number)
- `metadata.label_source_tag`: Tag name for label (default: label)

Note: Unicode filename to ASCII conversion is now automatic and always applied to ensure compatibility with audio processing tools.

## Usage

### Via AI Agent (Recommended)

Open an AI coding assistant in this directory and prompt:

```
Convert all WAV files to MP3 using the workflow from AGENTS.md.
```

Or for M4A output:

```
Convert all WAV files to M4A using the workflow from AGENTS.md.
```

Example for opencode:
```bash
opencode
# Then paste: Convert all WAV files to MP3 using the workflow from AGENTS.md.
```

### Via Command Line

```bash
# MP3 output (default)
python3 convert.py <file.wav>              # Single file
python3 convert.py *.wav                   # Batch (auto-parallel for 4+ files)

# M4A output
python3 convert.py --m4a <file.wav>        # Single file to M4A
python3 convert.py --m4a *.wav            # Batch to M4A

# Alternative format specification
python3 convert.py --format m4a file.wav

# Metadata options
python3 convert.py --no-online-lookup file.wav    # Disable online metadata lookup and enrichment (default: enabled)
```

## Unicode Filename Handling

The converter automatically handles Unicode filenames by converting them to ASCII equivalents for processing. This ensures compatibility with audio processing tools like ffmpeg that may not handle Unicode filenames correctly. The conversion happens transparently:

1. Unicode characters in filenames are converted to ASCII equivalents (e.g., "Agapás" → "Agapas")
2. Processing occurs on the ASCII filename copy in a temporary directory
3. Output files use the ASCII filename (with appropriate extension)
4. Temporary files are cleaned up after processing

This avoids issues with ffmpeg and other tools that may not handle Unicode filenames correctly.

## Examples

Convert a single file with Unicode characters to MP3:
```bash
python3 convert.py "Грег Эленис - Αγάπης Ti Fotiá.wav"
```

Convert all WAV files in directory to M4A:
```bash
python3 convert.py --m4a *.wav
```

Convert with custom parallel processing and disabled cover art:
```bash
python3 convert.py --max-workers 2 --no-cover *.wav
```

## Prerequisites

```bash
sudo apt update
sudo apt install ffmpeg python3
```

## Technical Details

| Setting | Value |
|---------|-------|
| Codec | MP3 (libmp3lame) or M4A/AAC, 320kbps |
| Loudness | True Peak ≤ -0.1 dBTP |
| Cover Size | 600x600 px |

### Output Formats

- **MP3** (default): Universal compatibility, great for streaming
- **M4A/AAC**: Better quality at same bitrate, Apple ecosystem

## Cover Artwork Strategy

1. **Source file**: Extract embedded cover from WAV
2. **Local folder**: Look for `cover.png`, `cover.jpg`, or matching image files
3. **Online search**: Deezer → MusicBrainz → Bandcamp

## Metadata Strategy

### Metadata Lookup Sources (in priority order)
1. **WAV tags**: Extract artist/title from embedded metadata via ffprobe
2. **Online lookup**: iTunes → Deezer → Bandcamp → MusicBrainz
3. **Filename parsing**: Fallback to heuristic parsing of filename ("Artist - Title")

### Metadata Enrichment
When `metadata.enabled` is true, missing metadata tags are written to the WAV file:
- `label` (or custom tag via `label_source_tag`)
- `genre`
- `album`
- `year`
- `track_number`

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

## Testing

```bash
# Run all tests
python3 -m unittest tests.test_convert

# Run with verbose output
python3 -m unittest tests.test_convert -v
```

## For AI Agents

See [AGENTS.md](AGENTS.md) for complete workflow instructions including:
- Pre-flight Check
- Error Recovery strategies
- Verification Checklist
- Batch Processing rules

## License

MIT

---

**Holger Kampffmeyer** (DJ Hulk)

- Website: [holger-kampffmeyer.de](https://holger-kampffmeyer.de)
- Email: holger.kampffmeyer+dj@gmail.com
- Instagram: [@djhulk_de](https://instagram.com/djhulk_de)
- YouTube: [@djhulk_de](https://youtube.com/@djhulk_de)
- Mixcloud: [holger-kampffmeyer](https://mixcloud.com/holger-kampffmeyer)
- LinkedIn: [holger-kampffmeyer](https://linkedin.com/in/holger-kampffmeyer-390b6789)

**Note**: This tool is designed to be used with AI coding assistants but can also be run manually via the command line.
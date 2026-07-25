# audioconvert

![AI-Powered Audio Conversion](assets/ai-powered.png)

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)](https://github.com/holgerkampffmeyer2/wav-to-aac-converter)
[![License](https://img.shields.io/github/license/holgerkampffmeyer2/wav-to-aac-converter)](https://github.com/holgerkampffmeyer2/wav-to-aac-converter)
[![Tests](https://github.com/holgerkampffmeyer2/wav-to-aac-converter/actions/workflows/test.yml/badge.svg)](https://github.com/holgerkampffmeyer2/wav-to-aac-converter/actions/workflows/test.yml)

WAV/AIFF/FLAC to MP3/M4A conversion with loudness normalization, metadata extraction, and cover art embedding.

## Installation

### Option 1: One-Line Install (Recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/holgerkampffmeyer2/wav-to-aac-converter/main/install.sh | bash
```

Detects your platform (Linux/macOS), downloads the matching binary with bundled ffmpeg, and installs to `/usr/local/bin`.

Custom install directory:
```bash
INSTALL_DIR=~/bin curl -fsSL https://raw.githubusercontent.com/holgerkampffmeyer2/wav-to-aac-converter/main/install.sh | bash
```

### Option 2: Standalone Binary (Manual)

Download the latest release for your platform from [GitHub Releases](https://github.com/holgerkampffmeyer2/wav-to-aac-converter/releases):

```bash
# Linux (amd64)
tar xzf audioconvert-linux-amd64.tar.gz
./audioconvert --version

# macOS (Apple Silicon)
tar xzf audioconvert-macos-arm64.tar.gz
./audioconvert --version

# macOS (Intel)
tar xzf audioconvert-macos-x86_64.tar.gz
./audioconvert --version
```

No Python or ffmpeg installation required — everything is bundled.

### Option 3: pip Install

```bash
pip install audioconvert
```

Requires `ffmpeg` and `ffprobe` to be installed:
```bash
# Debian/Ubuntu
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

### Option 4: From Source

```bash
git clone https://github.com/holgerkampffmeyer2/wav-to-aac-converter.git
cd wav-to-aac-converter
pip install -e .
```

## How It Works

An AI agent reads `AGENTS.md` and executes the conversion workflow:

```
AI Agent reads AGENTS.md → Pre-flight Check → Executes convert.py → Monitors results → Verifies output
```

The agent handles:
- Prerequisites check (ffmpeg, python3)
- File discovery and batch processing decisions
- Loudness analysis and gain calculation
- Metadata extraction from files, online lookup (configurable sources), or filename parsing
- Cover art search: embedded → local folder → configurable online sources
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
    "offline": false,
    "sources": ["soundcloud", "itunes", "deezer", "bandcamp", "musicbrainz"],
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
- `metadata.offline`: Skip all online lookups and cover search (default: false)
- `metadata.sources`: Online sources (order = priority). Available: itunes, deezer, bandcamp, soundcloud, musicbrainz (default: all)
- `metadata.fallback_to_filename`: Fallback to filename parsing if no metadata found (default: true)
- `metadata.enrich_tags`: Tags to write when enriching (default: label, genre, album, year, track_number)
- `metadata.label_source_tag`: Tag name for label (default: label)
- `soundcloud_confidence_threshold`: Minimum confidence score (0.0-1.0) for SoundCloud web search results (default: 0.6)

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
audioconvert <file.wav>              # Single file
audioconvert *.wav                   # Batch (auto-parallel for 4+ files)

# M4A output
audioconvert --m4a <file.wav>        # Single file to M4A
audioconvert --m4a *.wav            # Batch to M4A

# FLAC support
audioconvert --m4a *.flac            # Convert FLAC files to M4A
audioconvert *.wav *.flac            # Mixed batch

# AIFF support
audioconvert --m4a *.aiff            # Convert AIFF files to M4A
audioconvert *.wav *.aiff *.flac     # Mixed batch

# Alternative format specification
audioconvert --format m4a file.wav

# Metadata options
audioconvert --no-metadata file.wav    # Disable online metadata lookup and enrichment (default: enabled)
audioconvert --offline file.wav        # Offline mode: no online lookups, local cover only
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
audioconvert "Грег Эленис - Αγάπης Ti Fotiá.wav"
```

Convert all WAV/AIFF/FLAC files in directory to M4A:
```bash
audioconvert --m4a *.wav *.aiff *.flac
```

Convert with custom parallel processing and disabled cover art:
```bash
audioconvert --max-workers 2 --no-cover *.wav
```

## SoundCloud Client ID

The SoundCloud search requires a `client_id`. It is loaded automatically from the `.env` file in the project directory (`SOUNDCLOUD_CLIENT_ID`).

To find your SoundCloud Client ID (step-by-step):

1. **Log in to SoundCloud** (with your account)
2. **Start a song/radio** (a track should be playing)
3. **Open DevTools**: `Ctrl + Shift + I` (or `F12`)
4. **Select the Network tab**
5. **Reload the page** (`Ctrl + R`)
6. **Search for requests** containing `?client_id=` (e.g., `api-v2.soundcloud.com`)
7. **Click the request** → open the Headers section
8. **Copy the `client_id` from the URL** (the value after `client_id=` and before the next `&`)

Then create a `.env` file in the project directory with:

```bash
SOUNDCLOUD_CLIENT_ID=your_client_id_here
```

The `.env` file is loaded automatically and listed in `.gitignore` to prevent accidentally committing your client ID.

Without a valid client ID, SoundCloud search is skipped. The converter validates the client ID at startup and logs a warning with remediation steps if it is invalid or expired.

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

1. **Source file**: Extract embedded cover from source (WAV/FLAC/AIFF)
2. **Local folder**: Look for `cover.png`, `cover.jpg`, or exact filename match. No fallback to arbitrary images in the folder.
3. **Online search**: Configurable order via `metadata.sources` (default: SoundCloud → iTunes → Deezer → Bandcamp → MusicBrainz, skipped in `--offline` mode)

## Metadata Strategy

### Metadata Lookup Sources (configurable order)
1. **Source tags**: Extract artist/title from embedded metadata via ffprobe
2. **Online lookup**: Configurable via `metadata.sources` (default: SoundCloud → iTunes → Deezer → Bandcamp → MusicBrainz)
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
├── *.wav / *.flac         # Source files
└── *.mp3 / *.m4a        # Converted output
```

## Testing

```bash
# Run all tests
python3 -m unittest tests.test_convert

# Run with verbose output
python3 -m unittest tests.test_convert -v
```

## Building from Source

```bash
# Install build dependencies
pip install pyinstaller

# Build standalone binary
pyinstaller pyinstaller/convert.spec

# Binary is in dist/audioconvert/
./dist/audioconvert/audioconvert --version
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
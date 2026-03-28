# wav-to-mp3-converter

![AI-Powered Audio Conversion](assets/ai-powered.png)

AI-agent driven WAV to MP3/M4A conversion with loudness normalization, metadata extraction, and cover art embedding. Designed to be controlled by AI coding assistants like [opencode](https://opencode.ai) or Claude Code.

## How It Works

An AI agent reads `AGENTS.md` and executes the conversion workflow:

```
AI Agent reads AGENTS.md → Pre-flight Check → Executes convert.py → Monitors results → Verifies output
```

The agent handles:
- Prerequisites check (ffmpeg, python3)
- File discovery and batch processing decisions
- Loudness analysis and gain calculation
- Metadata extraction from files or web search
- Cover art search: embedded → local folder → Deezer → Bandcamp → SoundCloud
- Error recovery and retries
- Verification of output quality

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
3. **Web search**: Deezer → Bandcamp → SoundCloud

## File Structure

```
wav-to-mp3-converter/
├── assets/            # Images and static assets
├── AGENTS.md          # AI agent workflow instructions
├── README.md          # This file
├── convert.py         # Python converter script
├── pyproject.toml     # Python project config
├── tests/             # Test files
├── *.wav              # Source files
└── *.mp3 / *.m4a      # Converted output
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
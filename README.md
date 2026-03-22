# wav-to-aac-converter

![AI-Powered Audio Conversion](ai-powered.png)

AI-agent driven WAV to AAC conversion with loudness normalization, metadata extraction, and cover art embedding. Designed to be controlled by AI coding assistants like [opencode](https://opencode.ai) or Claude Code.

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
- Cover art download from Deezer/Bandcamp/SoundCloud
- Error recovery and retries
- Verification of output quality

## Usage

### Via AI Agent (Recommended)

Open an AI coding assistant in this directory and prompt:

```
Convert all WAV files to AAC using the workflow from AGENTS.md.
```

Example for opencode:
```bash
opencode
# Then paste: Convert all WAV files to AAC using the workflow from AGENTS.md.
```

### Via Command Line

```bash
python convert.py <file.wav>              # Single file
python convert.py *.wav                   # Batch (auto-parallel for 4+ files)
python convert.py file1.wav file2.wav    # Multiple files
```

## Prerequisites

```bash
sudo apt update
sudo apt install ffmpeg python3
```

## Technical Details

| Setting | Value |
|---------|-------|
| Codec | AAC-LC, 320kbps |
| Loudness | True Peak ≤ -0.1 dBTP |
| Cover Size | 600x600 px |

## File Structure

```
wav-to-aac-converter/
├── AGENTS.md          # AI agent workflow instructions
├── README.md          # This file
├── convert.py         # Python converter script
├── pyproject.toml     # Python project config
├── tests/             # Test files
├── *.wav              # Source files
└── *.m4a              # Converted output
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

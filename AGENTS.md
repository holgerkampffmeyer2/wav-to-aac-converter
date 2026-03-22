# Audio Conversion: WAV to AAC

AI agent workflow for converting WAV files to high-quality AAC with loudness normalization and metadata. Designed for AI coding assistants like [opencode](https://opencode.ai) or Claude Code.

## Agent Instructions

When an AI agent encounters this project, it should:
1. Read this file to understand the conversion workflow
2. Execute `convert.py` with appropriate arguments
3. Monitor for errors and handle retries
4. Report results to the user

## Quick Start

```bash
python convert.py <file.wav>              # Single file
python convert.py *.wav                   # Batch (auto-parallel for 4+ files)
python convert.py file1.wav file2.wav    # Multiple files
```

## Workflow Steps

### Single File (Sequential)
```
Loudness Analysis → Metadata Extraction → Cover Search → AAC Encoding → Embed Artwork → Verify
```

### Batch Processing (Parallel)
- **Auto-detected**: 4+ files trigger parallel mode
- **Max workers**: 5 parallel processes
- **Fallback**: <4 files processed sequentially

## Prerequisites

```bash
sudo apt install ffmpeg python3
```

## Known Filename Patterns

| Pattern | Artist | Title | SC-Handle |
|---------|--------|-------|-----------|
| `Artist - Title.wav` | Artist | Title | - |
| `Title [handle].wav` | (from SC) | Title | handle |
| `Artist - Title (Remix).wav` | Artist | Title (Remix) | - |
| `[handle] Track.wav` | (from SC) | Track | handle |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No cover found | Check filename has artist/title or embedded cover |
| API rate limited | Wait 60s, then retry batch |
| Loudnorm fails | Verify ffmpeg supports loudnorm filter |
| Metadata missing | Use "Artist - Title" filename format |

## Technical Details

- **Codec**: AAC-LC, 320kbps
- **Loudness**: True Peak ≤ -0.1 dBTP (auto-calculated gain)
- **Cover Sources**: Deezer → Bandcamp → SoundCloud
- **Retry Logic**: 3 attempts with exponential backoff

# Audio Conversion: WAV to AAC

AI agent workflow for converting WAV files to high-quality AAC with loudness normalization and metadata. Designed for AI coding assistants like [opencode](https://opencode.ai) or Claude Code.

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
python convert.py <file.wav>              # Single file
python convert.py *.wav                   # Batch (auto-parallel for 4+ files)
python convert.py file1.wav file2.wav    # Multiple files
```

## Workflow Steps

### Single File (Sequential)
```
Loudness Analysis → Metadata Extraction → Cover Search → AAC Encoding → Embed Artwork → Verify
```

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
| All sources fail | Create M4A without cover, log warning |

### Verification Checklist

After conversion, agent should verify:

- [ ] **AAC Codec**: `ffprobe` shows `codec_name=aac`
- [ ] **True Peak ≤ -0.1 dBTP**: Check with loudnorm analysis
- [ ] **Cover embedded** (if available): `attached_pic=1` in stream
- [ ] **Metadata present**: Artist/Title visible in ffprobe output

```bash
# Verification command
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
| No cover found | Check filename has artist/title or embedded cover |
| API rate limited | Wait 60s, then retry batch |
| Loudnorm fails | Verify ffmpeg supports loudnorm filter |
| Metadata missing | Use "Artist - Title" filename format |
| Slow batch processing | Normal for 4+ files (parallel mode active) |

## Technical Details

- **Codec**: AAC-LC, 320kbps
- **Loudness**: True Peak ≤ -0.1 dBTP (auto-calculated gain)
- **Cover Sources**: Deezer → Bandcamp → SoundCloud
- **Retry Logic**: 3 attempts with exponential backoff

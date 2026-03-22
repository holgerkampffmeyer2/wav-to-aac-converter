# Audio Conversion: WAV to MP3

AI agent workflow for converting WAV files to high-quality MP3 with loudness normalization and metadata. Designed for AI coding assistants like [opencode](https://opencode.ai) or Claude Code.

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
python3 convert.py <file.wav>              # Single file
python3 convert.py *.wav                   # Batch (auto-parallel for 4+ files)
python3 convert.py file1.wav file2.wav    # Multiple files
```

## Workflow Steps

### Single File (Sequential)
```
Loudness Analysis → Metadata Extraction → Cover Search → MP3 Encoding → Embed Artwork → Verify
```

### Cover Artwork Strategy
1. **Source file**: Check for embedded cover in WAV
2. **Local folder**: Look for `cover.png`, `cover.jpg`, or matching image files
3. **Web search**: Deezer → Bandcamp → SoundCloud

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
| All sources fail | Create MP3 without cover, log warning |

### Verification Checklist

After conversion, agent should verify:

- [ ] **MP3 Codec**: `ffprobe` shows `codec_name=mp3` or `codec_name=libmp3lame`
- [ ] **True Peak ≤ -0.1 dBTP**: Check with loudnorm analysis
- [ ] **Cover embedded** (if available): Check stream tags in ffprobe output
- [ ] **Metadata present**: Artist/Title visible in ffprobe output

```bash
# Verification command
ffprobe -v quiet -show_format -show_streams "output.mp3"
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
| Metadata missing | Use "Artist - Title" filename format |
| Slow batch processing | Normal for 4+ files (parallel mode active) |

## Technical Details

- **Codec**: MP3 (libmp3lame), 320kbps
- **Loudness**: True Peak ≤ -0.1 dBTP (auto-calculated gain)
- **Cover Sources**: Source → Local folder → Deezer → Bandcamp → SoundCloud
- **Retry Logic**: 3 attempts with exponential backoff

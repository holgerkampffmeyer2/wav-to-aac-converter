# Audio Conversion: WAV to AAC

Automated workflow for converting WAV files to high-quality AAC with loudness normalization and metadata.

## Quick Start

```bash
python convert.py <file.wav>              # Single file
python convert.py *.wav                   # Batch (auto-parallel for 4+ files)
python convert.py file1.wav file2.wav    # Multiple files
```

## Workflow Types

### Single File (Sequential)
```
Loudness Analysis → Metadata Extraction → Cover Search → AAC Encoding → Embed Artwork → Verify
```

### Batch Processing (Parallel)
- **Auto-detected**: 4+ files trigger parallel mode
- **Max workers**: 5 parallel processes
- **Fallback**: <4 files processed sequentially

## Usage

```bash
# Prerequisites
sudo apt install ffmpeg python3

# Single conversion
python convert.py "Artist - Title.wav"

# Batch conversion (auto-parallel)
python convert.py *.wav

# Run tests
python3 test_convert.py
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

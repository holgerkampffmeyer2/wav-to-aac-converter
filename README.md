# optimize-music-prompts

Automated WAV to AAC conversion with loudness normalization, metadata extraction, and cover art embedding.

## What This Does

Converts WAV audio files to high-quality AAC (.m4a) format with:

- **Loudness normalization** — Analyzes true peak and integrated loudness, applies gain to prevent clipping
- **Metadata extraction** — Pulls existing tags from source files
- **Web lookup** — Searches MusicBrainz/Discogs/Beatport for missing metadata
- **Cover art** — Extracts or downloads album artwork, embeds into final file
- **Verification** — Confirms metadata and artwork are properly embedded

## Quick Start

```bash
# Install dependencies (Ubuntu/WSL)
sudo apt update
sudo apt install ffmpeg ffprobe

# Run conversion (see AGENTS.md for full workflow)
ffmpeg -i "input.wav" -af loudnorm=print_format=json -f null - 2>&1 | grep -A 20 '^\{$'
```

## Tech Stack

| Component | Recommendation |
|-----------|----------------|
| OS | **WSL2** (Ubuntu 22.04+) |
| AI Assistant | **opencode** |
| Audio Tools | `ffmpeg`, `ffprobe` |
| Web Search | Built into opencode |

### Install FFmpeg on WSL

```bash
sudo apt update
sudo apt install ffmpeg
```

Verify installation:

```bash
ffmpeg -version
ffprobe -version
```

## Documentation

See [AGENTS.md](AGENTS.md) for complete workflow instructions.

## File Structure

```
optimize-music-prompts/
├── AGENTS.md                    # Agent instructions
├── README.md                    # This file
audio files
├── *.wav                        # Source
└── *.m4a                        # Converted output
```

## License

MIT

---

## Contact

**Holger Kampffmeyer** (DJ Hulk)

- Website: [holger-kampffmeyer.de](https://holger-kampffmeyer.de)
- Email: holger.kampffmeyer+dj@gmail.com
- Instagram: [@djhulk_de](https://instagram.com/djhulk_de)
- YouTube: [@djhulk_de](https://youtube.com/@djhulk_de)
- Mixcloud: [holger-kampffmeyer](https://mixcloud.com/holger-kampffmeyer)
- LinkedIn: [holger-kampffmeyer](https://linkedin.com/in/holger-kampffmeyer-390b6789)

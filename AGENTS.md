# Audio Conversion: WAV to AAC

Automated workflow for converting WAV files to high-quality AAC with loudness normalization and metadata.

## Workflow

```
Loudness Analysis → Metadata Extraction → [Web Search if needed] → AAC Encoding → Embed Artwork → Verify
```

## Prerequisites

- `ffmpeg` with AAC encoding support
- `ffprobe` for metadata extraction
- Internet access for metadata lookup (optional)

---

## Step 1: Loudness Analysis

```bash
ffmpeg -i "input.wav" -af loudnorm=print_format=json -f null - 2>&1 | grep -A 20 '^\{$'
```

### Key Metrics

| Metric | Source Field | Target | Action if Violated |
|--------|--------------|--------|-------------------|
| True Peak | `input_tp` | ≤ -0.1 dBTP | Calculate gain reduction |
| Integrated Loudness | `input_i` | -14 to -24 LUFS | Informational only |

### Clipping Prevention

Calculate gain reduction if `input_tp > -0.1`:

```
gain_db = input_tp - (-0.1)
```

Example: `input_tp = 1.50` → `gain_db = -2.0`

**Error handling**: If analysis fails, check if ffmpeg supports loudnorm filter (`ffmpeg -filters | grep loudnorm`).

---

## Step 2: Extract Source Metadata

```bash
ffprobe -v quiet -print_format json -show_format -show_streams "input.wav"
```

Extract and store:
- Title, artist, album, genre, date, track number
- Embedded artwork (if present)

### Extract Cover Art

```bash
ffmpeg -y -i "input.wav" -vf "scale=600:600:force_original_aspect_ratio=decrease,pad=600:600:(ow-iw)/2:(oh-ih)/2" -frames:v 1 -q:v 2 "cover.jpg" 2>/dev/null
```

| Property | Value | Reason |
|----------|-------|--------|
| Max dimension | 600x600 | Standard for audio players |
| Quality | `q:v 2` (~95% JPEG quality) | Balance quality/size |
| Max file size | ~50-100KB | Avoids bloat in audio container |

**Error handling**: If no artwork extracted, proceed to Step 3 (web search).

---

## Step 3: Decision Gate — Metadata Status

```
Source metadata complete? ──YES──> Proceed to Step 5
          │
          NO
          │
          ▼
    Web Search Needed
```

### Metadata Complete?
- Has title, artist, genre, year? → **Skip to Step 5**
- Missing critical fields (title/artist)? → **Search online**

### Online Search Priority

1. **MusicBrainz** (coverartarchive.org) — Authoritative, includes ISRC
2. **Discogs** — Physical release data
3. **Beatport** — Official digital releases
4. **SoundCloud/Spotify** — Lower confidence (may be remixes/covers)

| Source | Confidence | Notes |
|--------|------------|-------|
| MusicBrainz | High | Best for metadata accuracy |
| Discogs | High | Reliable for releases |
| Beatport | High | Official digital |
| SoundCloud | Medium | May differ from original |
| Spotify | Medium | Verify carefully |

### Track Not Found Online?

1. Use filename to extract artist/title if formatted clearly
2. Search by partial title or known artist only
3. Mark metadata as "Unknown Artist - {filename}" with confidence: low
4. Document what was attempted in comments

---

## Step 4: AAC Encoding

```bash
ffmpeg -y -i "input.wav" \
  -map 0:a \
  -af "volume={gain_db}dB" \
  -c:a aac -b:a 320k \
  -metadata title="Track Title" \
  -metadata artist="Artist Name" \
  -metadata album="Album Name" \
  -metadata genre="Genre" \
  -metadata date="YYYY" \
  -movflags +use_metadata_tags \
  "output.m4a"
```

| Parameter | Value | Notes |
|-----------|-------|-------|
| Bitrate | 320k | High quality minimum |
| Sample Rate | Inherited | From source |
| Codec | AAC-LC | Best compatibility |
| Gain | Calculated | Prevents clipping |

**Error handling**: If encoding fails, verify `-map 0:a` excludes non-audio streams.

---

## Step 5: Embed Cover Art

```bash
ffmpeg -y -i "output.m4a" \
  -i "cover.jpg" \
  -c:a copy \
  -c:v copy \
  -map 0:a \
  -map 1:v \
  -disposition:1 attached_pic \
  "final.m4a"
```

**Error handling**: 
- No cover art? Skip this step entirely (optional metadata).
- "codec not supported"? Ensure `-map 0:a` is used.

---

## Step 6: Verification

```bash
# Verify metadata
ffprobe -v quiet -show_format "final.m4a" | grep -E "title|artist|album|genre|date|size"

# Verify streams + artwork
ffprobe -v quiet -show_streams "final.m4a" | grep -E "codec_name|attached_pic"
```

Expected output:
```
codec_name=aac
DISPOSITION:attached_pic=0
codec_name=mjpeg
DISPOSITION:attached_pic=1
```

**Error handling**: If `attached_pic=1` missing, cover art failed — re-run Step 5.

---

## File Naming

```
{Artist} - {Title}.m4a
```
For remixes:
```
{Title} ({Remixer} Remix).m4a
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "codec not supported in container" | Add `-map 0:a` |
| Cover art not embedding | Use `-disposition:1 attached_pic` |
| Clipping after encoding | Increase gain reduction by 0.5-1.0 dB |
| Loudnorm analysis fails | Check ffmpeg version supports filter |
| No metadata found online | Use filename extraction, mark confidence low |

---

## Cleanup

After successful conversion, remove temporary files:

```bash
rm -f cover.jpg output.m4a analysis.json
```

**Preserve**:
- Source WAV files (do not delete)
- Final `.m4a` output

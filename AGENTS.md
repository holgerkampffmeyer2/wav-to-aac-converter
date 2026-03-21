# Audio Conversion: WAV to AAC

Automated workflow for converting WAV files to high-quality AAC with loudness normalization and metadata.

## Workflow Types

### Single File (Sequential)
```
Loudness Analysis → Metadata Extraction → [Web Search if needed] → AAC Encoding → Embed Artwork → Verify
```

### Batch Processing (Parallel with Subagents)
```
┌─────────────────────────────────────────────────────────────┐
│                    MAIN AGENT (Orchestrator)                 │
│  1. Scan WAV files                                          │
│  2. Launch N subagents in parallel (1 per file)             │
│  3. Collect results, verify outputs                          │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
   ┌─────────────┐      ┌─────────────┐     ┌─────────────┐
   │ SUBAGENT 1  │      │ SUBAGENT 2  │     │ SUBAGENT N  │
   │ File A      │      │ File B      │     │ File N      │
   └─────────────┘      └─────────────┘     └─────────────┘
```

**Benefits**: Process N files in parallel instead of sequentially. 10 files take ~1x time instead of 10x.

## Batch Execution with Subagents

### Main Agent (Orchestrator)

```bash
# 1. List all WAV files
ls *.wav

# 2. Launch subagent for each file
# Use task tool with 'general' subagent_type
```

### Subagent Prompt Template

```
Convert "{filename}" to AAC:
1. Loudness analysis: ffmpeg -i "{filename}" -af loudnorm=print_format=json -f null - 2>&1 | grep -A 20 '^\{$'
2. Extract metadata: ffprobe -v quiet -print_format json -show_format -show_streams "{filename}"
3. Search Deezer API for cover art: curl -sL "https://api.deezer.com/search/album?q={query}"
4. Encode with metadata and embed cover
5. Verify output with ffprobe
6. Return result: SUCCESS/FAILED + output filename
```

### Parallelization Strategy

| Files | Sequential | Parallel (N subagents) | Speedup |
|-------|------------|-------------------------|---------|
| 1     | 1x         | 1x                      | 1x      |
| 5     | 5x         | ~1x                     | 5x      |
| 10    | 10x        | ~1x                     | 10x     |
| 20    | 20x        | ~1-2x                   | 10-20x  |

**Recommended**: Use 5-10 subagents maximum to avoid rate limiting on metadata APIs.

## Prerequisites

- `python3` for running convert.py
- `ffmpeg` with AAC encoding support
- `ffprobe` for metadata extraction
- Internet access for metadata lookup

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
gain_db = min(0, -0.1 - input_tp)
```

Example: `input_tp = 1.50` → `gain_db = -1.60`

**Error handling**: If analysis fails, check if ffmpeg supports loudnorm filter (`ffmpeg -filters | grep loudnorm`).

---

## Step 2: Extract Source Metadata

```bash
ffprobe -v quiet -print_format json -show_format -show_streams "input.wav"
```

Extract and store:
- Title, artist, album, genre, date, track number
- Embedded artwork (if present)

### Extract Cover Art from Source

```bash
ffmpeg -y -i "input.wav" -map 0:v -map -0:a -c:v copy "cover.jpg" 2>/dev/null
```

**RULE: Always extract cover from source FIRST before searching online.**

| Property | Value | Reason |
|----------|-------|-------|
| Method | Copy video stream | Preserves quality |
| Max dimension | Inherited | From source |
| Fallback | Online search | If no source cover |

**Error handling**: If no artwork extracted, proceed to Step 3 (web search for cover art).

---

## Step 3: Online Cover Art Search

If source WAV has no embedded artwork, search online:

```bash
# Deezer API (fast, reliable)
curl -sL "https://api.deezer.com/search/album?q={artist}+{title}" | jq -r '.data[0].cover_big'

# Bandcamp (requires web search for URL, then scrape page)
curl -sL "https://{bandcamp_url}" | grep -oP 'og:image" content="\K[^"]+'

# SoundCloud (scraped from page og:image)
curl -sL "https://soundcloud.com/{user}/{track}" | grep -oP 'og:image" content="\K[^"]+'
```

**Download priority**: Deezer → Bandcamp → SoundCloud → MusicBrainz → Discogs

| Source | URL | Notes |
|--------|-----|-------|
| Deezer | api.deezer.com/search/album | Fast JSON API, direct image URLs |
| Bandcamp | bandcamp.com | High quality artwork, scrape from page |
| SoundCloud | soundcloud.com | Extract handle from brackets (e.g., [COPPADOS]), try common free download handles |
| MusicBrainz | coverartarchive.org | Authoritative, needs release ID |
| Discogs | discogs.com | Image scraping required |

**SoundCloud Search Strategy**:
1. Extract handle from brackets in filename: `Track [handle]` → `soundcloud.com/handle/...`
2. If no brackets, try artist name as handle
3. Fallback: Try common free download handles (`gsfreedls`, `freedls`, etc.)
4. Strip remix/edit/master/loud/dub keywords from track slug

**Error handling**: If no cover found online, skip artwork embedding (optional metadata).

---

## Step 4: Decision Gate — Metadata Status

```
Source metadata complete? ──YES──> Proceed to Step 5
          │
          NO
          │
          ▼
    Web Search Needed
```

### Metadata Complete?
- Has title, artist, genre, year? → **Proceed to Step 5**
- Missing critical fields (title/artist)? → **Search online**

### Online Search Priority

1. **Deezer** — Fast API, direct image URLs
2. **Bandcamp** — High quality artwork, official releases
3. **SoundCloud** — Extract handle from filename (e.g., [COPPADOS]), scrape cover from track page
4. **MusicBrainz** (coverartarchive.org) — Authoritative, includes ISRC
5. **Discogs** — Physical release data
6. **Beatport** — Official digital releases

| Source | Confidence | Notes |
|--------|------------|-------|
| Bandcamp | High | Best artwork quality, official releases |
| MusicBrainz | High | Best for metadata accuracy |
| Discogs | High | Reliable for releases |
| Beatport | High | Official digital |
| Deezer | High | Fast JSON API, reliable |
| SoundCloud | Medium | Best for remixes/edits from SC creators |

### Track Not Found Online?

1. Use filename to extract artist/title if formatted clearly
2. Search by partial title or known artist only
3. **Use web search**: The agent's `websearch` tool can find tracks on SoundCloud, Bandcamp, etc. when API searches fail
4. Mark metadata as "Unknown Artist - {filename}" with confidence: low
5. Document what was attempted in comments

### Using Web Search for Track Discovery

When Deezer/Bandcamp API returns no results, use the agent's web search:

```
/search <artist> <title> site:bandcamp.com
/search <artist> <title> site:soundcloud.com
```

Found URLs can be used to extract cover art via:
```bash
curl -sL "https://bandcamp.com/artist/track" | grep -oP 'og:image" content="\K[^"]+'
```

---

## Step 5: AAC Encoding

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
| Bitrate | 320k target | Actual may vary (VBR) - document real bitrate |
| Sample Rate | Inherited | From source |
| Codec | AAC-LC | Best compatibility |
| Gain | Calculated | Prevents clipping |

**Error handling**: If encoding fails, verify `-map 0:a` excludes non-audio streams.

---

## Step 6: Embed Cover Art

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

## Step 7: Verification

```bash
# Verify metadata (must show title, artist, album, genre)
ffprobe -v quiet -show_format "final.m4a" | grep -E "TAG:title|TAG:artist|TAG:album|TAG:genre"

# Verify streams + artwork
ffprobe -v quiet -show_streams "final.m4a" | grep -E "codec_name|attached_pic"
```

Expected output:
```
TAG:title=Track Title
TAG:artist=Artist Name
TAG:album=Album Name
TAG:genre=Genre
codec_name=aac
DISPOSITION:attached_pic=0
codec_name=mjpeg
DISPOSITION:attached_pic=1
```

**CRITICAL**: If ANY metadata is missing, the file is CORRUPTED. Re-run from Step 5.

### Verification Checklist

| Check | Command | Pass Condition |
|-------|---------|----------------|
| Has audio | `codec_name=aac` | Must exist |
| Has artwork | `attached_pic=1` | Must exist for mjpeg stream |
| Has title | `TAG:title=` | Must not be empty |
| Has artist | `TAG:artist=` | Must not be empty |
| Has album | `TAG:album=` | Recommended |
| Has genre | `TAG:genre=` | Recommended |

**Error handling**:
- `attached_pic=1` missing → Cover art failed. Delete file, re-run Steps 5-6
- Metadata missing → Delete file, re-run Steps 5-6 with correct metadata
- File size < 1MB for >1min audio → Likely corrupted, re-convert

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
| Metadata disappeared after re-muxing | Re-encode from source WAV, do not copy from existing M4A |
| Artwork disappeared after re-muxing | Re-run embed step, ensure `-disposition:1 attached_pic` |

### Critical Rules

1. **ALWAYS verify output after encoding** — Check metadata AND artwork BEFORE deleting source WAV
2. **Never modify M4A in-place** — Always re-encode from source WAV, never copy streams from a broken M4A
3. **Delete and retry** — If verification fails, delete the bad file and start over from Step 5
4. **Preserve source** — Source WAV files are the master; M4A is derived

---

## Cleanup

After successful conversion, temporary files are automatically removed:

```bash
rm -f cover_*.jpg output_*.m4a
```

**JSON result files** are only created if conversion fails (for debugging).

**Preserve**:
- Source WAV files (do not delete)
- Final `.m4a` output

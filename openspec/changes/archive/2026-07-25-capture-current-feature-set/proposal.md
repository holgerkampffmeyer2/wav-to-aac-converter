## Why

The project currently implements audio conversion from WAV/AIFF/FLAC to MP3/M4A with loudness normalization, metadata lookup, and cover art embedding, but lacks formal OpenSpec specifications documenting this feature set. Capturing the current features as OpenSpec specifications enables structured versioning, requirement tracking, and reliable delta spec synchronization.

## What Changes

- Introduce formal OpenSpec specifications for the audio conversion project.
- Document existing capabilities: audio conversion, loudness normalization, metadata extraction & enrichment, cover art embedding, and batch processing.

## Capabilities

### New Capabilities
- `audio-conversion`: Core conversion workflow from WAV/AIFF/FLAC to MP3 or M4A with Unicode-to-ASCII filename sanitization.
- `loudness-normalization`: True Peak ≤ -0.1 dBTP normalization and error fallback.
- `metadata-management`: Extraction, online lookup (SoundCloud, iTunes, Deezer, Bandcamp, MusicBrainz), and tag enrichment.
- `cover-art`: Embedded, local, and online cover art search and embedding.
- `batch-processing`: Parallel and sequential batch processing.

### Modified Capabilities
<!-- None -->

## Impact
- No changes to application code; purely documentation and formal specification of existing behavior.

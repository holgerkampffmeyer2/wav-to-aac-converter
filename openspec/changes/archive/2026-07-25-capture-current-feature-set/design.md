## Context

The repository is an established Python CLI tool and Python package for converting WAV/AIFF/FLAC audio files to MP3 or M4A with loudness normalization, metadata enrichment, and cover art embedding. It has robust testing (`tests/test_convert.py`) and clean modular architecture (`src/`).

## Goals / Non-Goals

**Goals:**
- Formalize the existing feature set into OpenSpec specifications (`specs/`).
- Document all core modules: audio processing, metadata lookup, cover art strategy, batch processing, and Unicode-to-ASCII filename handling.

**Non-Goals:**
- Refactoring existing implementation code as part of this specification proposal.

## Decisions

- **Modular Specifications**: Divide specs into separate capability files (`audio-conversion`, `loudness-normalization`, `metadata-management`, `cover-art`, `batch-processing`) mirroring the modular structure in `src/`.
- **OpenSpec Convention**: Follow spec-driven development standards with standard ADDED requirements and scenarios.

## Risks / Trade-offs

- [Out of sync documentation] → Mitigation: Ensure specs accurately reflect current implementation and test coverage.

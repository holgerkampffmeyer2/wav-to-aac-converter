# Audio Conversion Specification

## Purpose
Defines the core audio conversion workflow supporting WAV, AIFF, and FLAC inputs to MP3 or M4A outputs with Unicode filename sanitization.

## Requirements

### Requirement: Supported Input Formats
The system SHALL support WAV, AIFF, and FLAC audio files as input sources.

#### Scenario: Convert WAV file
- **WHEN** user passes a .wav file to the converter
- **THEN** the system processes and converts the file successfully

#### Scenario: Convert FLAC file
- **WHEN** user passes a .flac file to the converter
- **THEN** the system processes and converts the file successfully

### Requirement: Output Format Selection
The system SHALL output MP3 (libmp3lame, 320kbps) by default or M4A (AAC, 320kbps) when requested via flag.

#### Scenario: Default MP3 output
- **WHEN** user runs conversion without format flags
- **THEN** output file is encoded as MP3 at 320kbps

#### Scenario: M4A output flag
- **WHEN** user runs conversion with `--m4a` or `--format m4a`
- **THEN** output file is encoded as M4A/AAC at 320kbps

### Requirement: Unicode Filename Handling
The system SHALL automatically convert Unicode filenames to ASCII equivalents during processing to ensure compatibility with audio processing tools.

#### Scenario: Unicode filename sanitization
- **WHEN** input file contains non-ASCII characters in filename
- **THEN** system processes file via temporary ASCII-named copy and outputs sanitized filename

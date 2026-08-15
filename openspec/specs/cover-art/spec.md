# Cover Art Specification

## Purpose
Defines cover art discovery from embedded metadata, local folder files, and online providers with confidence scoring.

## Requirements

### Requirement: Cover Art Discovery and Embedding
The system SHALL search for cover art from embedded sources, local folder files, and online providers, and embed artwork into output files.

#### Scenario: Embedded cover extraction
- **WHEN** source audio file contains embedded cover artwork
- **THEN** system extracts and re-embeds the cover art

#### Scenario: Local cover folder search
- **WHEN** no embedded cover exists
- **THEN** system checks local directory for `cover.png`, `cover.jpg`, or exact filename match

#### Scenario: Local cover substring match
- **WHEN** no `cover.*` file, exact filename match, or normalized equal match exists in the local directory
- **THEN** system matches an image whose normalized name is a substring of the normalized WAV filename (e.g. `Mix194.png` for `DJ Hulk - Mix194 - Afrohouse.wav`), selecting the longest match with a minimum of 3 characters

#### Scenario: Online cover search
- **WHEN** local and embedded covers are absent and online lookup is enabled
- **THEN** system searches online providers with confidence scoring

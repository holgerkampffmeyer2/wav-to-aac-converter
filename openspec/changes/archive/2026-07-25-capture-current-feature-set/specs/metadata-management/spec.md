## ADDED Requirements

### Requirement: Metadata Extraction and Lookup
The system SHALL extract embedded tags, query online metadata sources in configured priority order, and fallback to filename parsing.

#### Scenario: Source embedded tags
- **WHEN** input file contains embedded artist and title tags
- **THEN** system uses embedded metadata

#### Scenario: Online metadata lookup
- **WHEN** embedded tags are missing and online lookup is enabled
- **THEN** system queries configured sources (SoundCloud, iTunes, Deezer, Bandcamp, MusicBrainz)

#### Scenario: Filename parsing fallback
- **WHEN** embedded tags and online lookup yield no results
- **THEN** system parses artist and title from filename using heuristic patterns

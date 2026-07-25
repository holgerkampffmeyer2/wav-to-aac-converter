## ADDED Requirements

### Requirement: Cover Art Discovery and Embedding
The system SHALL search for cover art from embedded sources, local folder files, and online providers, and embed artwork into output files.

#### Scenario: Embedded cover extraction
- **WHEN** source audio file contains embedded cover artwork
- **THEN** system extracts and re-embeds the cover art

#### Scenario: Local cover folder search
- **WHEN** no embedded cover exists
- **THEN** system checks local directory for `cover.png`, `cover.jpg`, or exact filename match

#### Scenario: Online cover search
- **WHEN** local and embedded covers are absent and online lookup is enabled
- **THEN** system searches online providers with confidence scoring

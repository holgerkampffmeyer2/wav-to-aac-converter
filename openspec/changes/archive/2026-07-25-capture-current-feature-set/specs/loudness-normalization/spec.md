## ADDED Requirements

### Requirement: Loudness Normalization
The system SHALL normalize audio to target True Peak ≤ -0.1 dBTP using FFmpeg loudnorm filter by default.

#### Scenario: Standard loudness normalization
- **WHEN** loudness normalization is enabled (default)
- **THEN** audio is analyzed and encoded with calculated gain to maintain True Peak ≤ -0.1 dBTP

#### Scenario: Loudnorm failure fallback
- **WHEN** loudness normalization analysis fails
- **THEN** system skips loudness correction and encodes with -3dB safety gain

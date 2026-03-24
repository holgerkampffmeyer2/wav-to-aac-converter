# Filename Parsing Improvements for WAV to AAC/MP3 Converter

## Summary of Changes Made

I've enhanced the filename parsing logic in `convert.py` to make it more robust against various real-world naming conventions found in music collections.

### Key Improvements:

1. **Enhanced `extract_metadata_from_filename()` function**:
   - Added support for multiple separator types:
     - Standard: " - " (hyphen with spaces) 
     - En dash: " – " 
     - Em dash: " — "
     - Underscore: "_"
     - Period: "." (when used as separator)
   - Added special pattern recognition for SoundCloud-style filenames:
     - "[handle] Title.wav" 
     - "Title [handle].wav"
   - Improved track number detection and skipping:
     - "01 - Artist - Title.wav" → Artist: "Artist", Title: "Title"
     - Works with all separator types
   - Better filtering to avoid misinterpreting descriptive terms (like "Remix", "Edit") as artist names

2. **Updated `HANDLE_RE` regex**:
   - Changed from `r'\[([a-z0-9_]+)\]'` to `r'\[([^\]]+)\]'`
   - Now supports dashes, dots, and other characters in SoundCloud handles
   - Updated corresponding test in `tests/test_convert.py`

3. **Added descriptive term filtering**:
   - Created a set of terms that should NOT be treated as artists even when found in brackets
   - Includes: remix, edit, mix, feat, radio, clean, explicit, instrumental, etc.

### Validation:

- All existing unit tests continue to pass (56/56 OK)
- New functionality tested with custom test script showing:
  - ✓ Standard "Artist - Title" format still works
  - ✓ New separator types (en dash, em dash, underscore, period) work
  - ✓ SoundCloud patterns "[handle] Title" and "Title [handle]" work
  - ✓ Track number skipping works with all separator types
  - ✓ Descriptive terms in brackets are correctly ignored as artists
  - ✓ Real-world examples from music library work correctly

### Remaining Limitations:

The current implementation still has one edge case that could be improved:
- Filenames like "ATTRACTION_Demo_G_125.wav" get parsed as Artist="ATTRACTION", Title="Demo_G_125"
- This happens because the underscore is treated as a separator
- A more sophisticated approach would need to detect when underscore-separated parts don't look like reasonable artist/title pairs

### Files Modified:

1. `convert.py` - Enhanced filename parsing logic
2. `tests/test_convert.py` - Updated test for handle-with-dash expectation
3. Created documentation files:
   - `filename_examples.txt` - Examples from actual music library
   - `filename_improvements.txt` - Technical analysis of improvements
   - `test_new_patterns.py` - Validation script for new patterns
   - `IMPROVEMENTS_SUMMARY.md` (this file)

### Usage:

The converter will now automatically handle a wider variety of filename formats when extracting artist and title metadata for WAV to MP3/M4A conversion, reducing the need for manual filename preprocessing.

To use:
```bash
# MP3 output (default)
python3 convert.py <file.wav>
python3 convert.py *.wav

# M4A output  
python3 convert.py --m4a <file.wav>
python3 convert.py --m4a *.wav
```
# Code Quality Improvements for wav-to-aac-converter

## Issues Fixed

### 1. DRY Violation in `search_soundcloud_web` Function
**Problem:** The `search_soundcloud_web` function contained massive code duplication - the same logic was repeated 3-4 times with only minor variations (different variable names like `slug` vs `sg`).

**Solution:** Removed the duplicated code blocks, keeping only one clean implementation of the SoundCloud search logic.

## Additional Improvement Opportunities

### 2. Configuration Management
**Issue:** Configuration loading has redundant code and unclear precedence.
**Improvement:** 
- Simplify `load_config()` to reduce nesting
- Add validation for configuration values
- Consider using a dedicated configuration library like `pydantic` or `dataclasses`

### 3. Error Handling Consistency
**Issue:** Inconsistent error handling patterns throughout the codebase.
**Improvement:**
- Standardize on either returning `(success, data)` tuples or raising exceptions
- Use more specific exception types instead of generic `Exception`
- Add more informative error messages with context

### 4. Function Decomposition
**Issue:** Several functions are overly long and handle multiple responsibilities.
**Improvement:**
- Break down `search_soundcloud_web` into smaller helper functions
- Extract the URL generation and searching logic into separate functions
- Consider creating a `SoundCloudSearcher` class to encapsulate related functionality

### 5. Magic Numbers and Strings
**Issue:** Hard-coded values scattered throughout the code.
**Improvement:**
- Define constants for values like:
  - Default bitrate (320k)
  - Cover art dimensions (600x600)
  - Timeout values
  - Retry attempt counts
- Move string literals like API endpoints to constants

### 6. Type Hints
**Issue:** Lack of type annotations makes code harder to understand and maintain.
**Improvement:**
- Add type hints to function signatures
- Use `TypedDict` for complex return values like metadata dictionaries
- Add type hints for class attributes and return types

### 7. Logging vs Print Statements
**Issue:** Mixed use of `print()` statements and proper logging.
**Improvement:**
- Replace debug print statements with proper logging using Python's `logging` module
- Allow configurable log levels via command line or configuration
- Remove commented-out debug code

### 8. Unit Test Coverage
**Issue:** Some complex functions lack adequate test coverage.
**Improvement:**
- Add tests for edge cases in filename parsing
- Test error conditions in network functions
- Add integration tests for the full conversion pipeline
- Mock external dependencies (API calls, subprocess) in tests

### 9. Code Organization
**Issue:** Some functions could be better organized.
**Improvement:**
- Group related functions together (e.g., all SoundCloud-related functions)
- Consider separating concerns into modules:
  - `audio_processing.py` for FFmpeg interactions
  - `metadata.py` for tag handling and online lookups
  - `cover_art.py` for cover art searching and processing
  - `utils.py` for helper functions

### 10. Performance Optimization
**Issue:** Some operations may be inefficient.
**Improvement:**
- Cache results of expensive operations (like filename ASCII conversion)
- Consider async/await for I/O bound operations (network requests)
- Optimize regex patterns that are used frequently
- Add early returns to avoid unnecessary computation

## Specific Code Examples

### Before (after fix):
```python
def search_soundcloud_web(artist, title, filename=""):
    # Clean, single implementation
    # ... (clean implementation without duplication)
```

### After (further improvements could include):
```python
def search_soundcloud_web(artist: str, title: str, filename: str = "") -> Tuple[Optional[Tuple[str, str]], Optional[str]]:
    """Search SoundCloud via web for track info and cover art."""
    if not artist and not title and not filename:
        return None, None
    
    # Extract and prepare search components
    filename_handles = extract_handles(filename or "")
    artist_handles = _generate_soundcloud_handles_from_artist(artist)
    all_handles = list(set(filename_handles + artist_handles))
    
    # Clean title for search
    cleaned_title = _clean_title_for_search(title, filename_handles)
    track_base_from_title = _generate_track_base(cleaned_title)
    track_base_from_filename = _extract_track_base_from_filename(filename)
    
    # Search using prepared components
    return _search_soundcloud_with_components(
        artist, title, filename, 
        all_handles, 
        track_base_from_title, 
        track_base_from_filename
    )
```

## Priority Recommendations

1. **High Priority:** Add comprehensive type hints throughout the codebase
2. **High Priority:** Replace debug prints with proper logging
3. **Medium Priority:** Extract SoundCloud search logic into smaller functions
4. **Medium Priority:** Add more unit tests for edge cases
5. **Low Priority:** Consider refactoring into separate modules for better organization

These improvements will make the code more maintainable, readable, and robust while preserving all existing functionality.
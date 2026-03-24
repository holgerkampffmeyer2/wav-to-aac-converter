#!/usr/bin/env python3
"""Test script to validate new filename parsing patterns."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from convert import extract_metadata_from_filename

def test_new_patterns():
    """Test the new filename patterns we're supporting."""
    
    test_cases = [
        # Original format still works
        ("Artist - Title.wav", ("Artist", "Title")),
        
        # New separator types
        ("Artist – Title.wav", ("Artist", "Title")),  # en dash
        ("Artist — Title.wav", ("Artist", "Title")),  # em dash
        ("Artist_Title.wav", ("Artist", "Title")),    # underscore
        ("Artist.Title.wav", ("Artist", "Title")),    # dot
        
        # SoundCloud patterns
        ("[gsfreedls] Track Name.wav", ("gsfreedls", "Track Name")),
        ("Track Name [gsfreedls].wav", ("gsfreedls", "Track Name")),
        ("[user-name] Song Title.wav", ("user-name", "Song Title")),  # with dash
        ("Song Title [user_name].wav", ("user_name", "Song Title")),  # with underscore
        
        # Track number skipping
        ("01 - Artist - Title.wav", ("Artist", "Title")),
        ("02 – Artist – Title.wav", ("Artist", "Title")),  # en dash
        ("03 — Artist — Title.wav", ("Artist", "Title")),  # em dash
        
        # Edge cases that should not be mistaken as artists
        ("[Remix] Track Name.wav", ("", "Track Name [Remix]")),  # descriptive term not artist
        ("[Edit] Song Title.wav", ("", "Song Title [Edit]")),    # descriptive term not artist
        ("[123] Track.wav", ("", "Track [123]")),               # numbers only not artist
        
        # Complex real-world examples from our search
        ("50 Cent ft J Timberlake - Ayo Technology Acapella.wav", 
         ("50 Cent ft J Timberlake", "Ayo Technology Acapella")),
         
        ("ATTRACTION_Demo_G_125.wav", 
         ("", "ATTRACTION_Demo_G_125")),  # No clear artist separator
         
        ("[gsfreedls] 60s Classic Rock Hits.wav", 
         ("gsfreedls", "60s Classic Rock Hits")),
    ]
    
    passed = 0
    failed = 0
    
    for filename, expected in test_cases:
        result = extract_metadata_from_filename(filename)
        if result == expected:
            print(f"✓ {filename} -> {result}")
            passed += 1
        else:
            print(f"✗ {filename} -> {result} (expected {expected})")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0

if __name__ == "__main__":
    success = test_new_patterns()
    sys.exit(0 if success else 1)
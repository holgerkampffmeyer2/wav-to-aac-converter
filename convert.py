#!/usr/bin/env python3
"""WAV to MP3/M4A converter - Entry point."""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.convert import main

if __name__ == '__main__':
    main()
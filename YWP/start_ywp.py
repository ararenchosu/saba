# -*- coding: utf-8 -*-
"""YWPぷにぷにBot 単体起動用"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
YWP_DIR = BASE_DIR / "YWP"
sys.path.insert(0, str(YWP_DIR))

from YWP.bot import main

if __name__ == "__main__":
    main()

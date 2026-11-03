"""Compatibility launcher: this program is now called Tamer (tamer.py).

Kept so that shortcuts, the startup entry and an already-installed background
service that still point at ark_manager.py keep working. You can run tamer.py directly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import tamer
    tamer.main()

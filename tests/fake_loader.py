#!/usr/bin/env python3
"""Pretends to be AsaApiLoader.exe: starts the ArkAscendedServer.exe next to it with the same args and waits."""
import os, subprocess, sys
frozen = getattr(sys, "frozen", False)  # the Windows test exe (see fakes.py)
here = os.path.dirname(os.path.abspath(sys.executable if frozen else sys.argv[0]))
server = os.path.join(here, "ArkAscendedServer.exe")
child = subprocess.Popen(([server] if frozen else [sys.executable, server]) + sys.argv[1:])
sys.exit(child.wait())

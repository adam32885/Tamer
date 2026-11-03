#!/usr/bin/env python3
"""Pretends to be AsaApiLoader.exe: starts the ArkAscendedServer.exe next to it with the same args and waits."""
import os, subprocess, sys
here = os.path.dirname(os.path.abspath(sys.argv[0]))
child = subprocess.Popen([sys.executable, os.path.join(here, "ArkAscendedServer.exe")] + sys.argv[1:])
sys.exit(child.wait())

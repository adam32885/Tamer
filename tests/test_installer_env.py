"""After "Download and install", the new Tamer.exe must not inherit the old one's PyInstaller variables, or it fails
with "Failed to load Python DLL". Checks Tamer's side (clean_child_env) and the installer's (clean_env.iss), by
building a test installer with the same code and running it with the leftovers set. The installer part needs
Windows and Inno Setup 6, and is skipped without them."""
import os, shutil, subprocess, sys, tempfile
sys.path.insert(0, sys.argv[1]); import tamer as am
HERE = os.path.dirname(os.path.abspath(__file__))
LEFTOVERS = {"_PYI_ARCHIVE_FILE": r"C:\old\Tamer.exe", "_PYI_APPLICATION_HOME_DIR": r"C:\gone\_MEI12345",
             "_PYI_PARENT_PROCESS_LEVEL": "1", "_MEIPASS2": r"C:\gone\_MEI12345"}

os.environ.update(LEFTOVERS)
env = am.clean_child_env()
assert not any(k in env for k in LEFTOVERS) and env["PYINSTALLER_RESET_ENVIRONMENT"] == "1", env
assert env.get("PATH") == os.environ.get("PATH"), "everything else is passed on"
print("Tamer starts the installer without the leftovers")

iscc = next((p for p in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
                         os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
                         os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe")) if os.path.isfile(p)), None)
if os.name != "nt" or not iscc:
    print("installer part skipped (needs Windows and Inno Setup 6)"); print("ALL OK"); sys.exit(0)
tmp = tempfile.mkdtemp()
r = subprocess.run([iscc, "/Q", f"/DOutDir={tmp}", os.path.join(HERE, "installer_env_test.iss")], capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
out = os.path.join(tmp, "env.txt")
run_env = dict(os.environ, **LEFTOVERS)  # started by an old Tamer that still passes them on
r = subprocess.run([os.path.join(tmp, "envtest.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", f"/out={out}"], env=run_env, timeout=120)
assert r.returncode == 0 and os.path.isfile(out), r.returncode
seen = {line.split("=", 1)[0].upper(): line.split("=", 1)[1] for line in open(out, encoding="mbcs", errors="replace").read().splitlines() if "=" in line}
assert not any(k in seen for k in LEFTOVERS), {k: seen[k] for k in LEFTOVERS if k in seen}
assert seen.get("PYINSTALLER_RESET_ENVIRONMENT") == "1" and "PATH" in seen, sorted(seen)
shutil.rmtree(tmp, ignore_errors=True)
print("the installer opens programs without the leftovers")
print("ALL OK")

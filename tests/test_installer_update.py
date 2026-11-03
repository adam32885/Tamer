"""Updating over a Tamer.exe that's still running (a question left open, the tray, the background service) used to
fail with "DeleteFile failed; code 5. Access is denied". The installer now closes a Tamer.exe running from its own
folder - and only there - before copying. Uses a test name, ID and task name, so it can't touch a real install or
service. Needs Windows, Inno Setup 6 and a built dist\\Tamer.exe; skipped otherwise."""
import os, shutil, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
iscc = next((p for p in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
                         os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
                         os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe")) if os.path.isfile(p)), None)
built = os.path.join(ROOT, "dist", "Tamer.exe")
if os.name != "nt" or not iscc or not os.path.isfile(built):
    print("skipped (needs Windows, Inno Setup 6 and a built dist\\Tamer.exe)"); print("ALL OK"); sys.exit(0)

tmp = tempfile.mkdtemp(prefix="tamer_inst_")
r = subprocess.run([iscc, "/Q", "/DAppVersion=0.0.0", "/DAppIdValue={{6A1D2C3B-0000-4000-8000-7E57E57E57E5}",
                    "/DAppTitle=TamerInstallTest", "/DTaskName=TamerNoSuchTaskForTests", f"/O{tmp}",
                    os.path.join(ROOT, "installer", "tamer.iss")], capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
setup = os.path.join(tmp, "Tamer-Setup-0.0.0.exe")
app, other = os.path.join(tmp, "app"), os.path.join(tmp, "other")
ping = os.path.join(os.environ["SystemRoot"], "System32", "PING.EXE")
procs = []
for d in (app, other):  # stand-ins: a "Tamer.exe" that just keeps running
    os.makedirs(d)
    shutil.copy(ping, os.path.join(d, "Tamer.exe"))
    procs.append(subprocess.Popen([os.path.join(d, "Tamer.exe"), "-n", "600", "127.0.0.1"], stdout=subprocess.DEVNULL,
                                  creationflags=0x08000000))
time.sleep(1)
assert all(p.poll() is None for p in procs)
log = os.path.join(tmp, "setup.log")
try:
    r = subprocess.run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={app}", "/TASKS=", f"/LOG={log}"],
                       timeout=180)
    assert r.returncode == 0, f"installer failed ({r.returncode}):\n" + open(log, encoding="utf-8", errors="replace").read()[-1500:]
    assert os.path.getsize(os.path.join(app, "Tamer.exe")) == os.path.getsize(built), "replaced with the real Tamer.exe"
    time.sleep(1)
    assert procs[0].poll() is not None, "the stand-in in the install folder was closed"
    assert procs[1].poll() is None, "a Tamer.exe somewhere else is left alone"
    text = open(log, encoding="utf-8", errors="replace").read()
    print("installer log:", next((l.strip() for l in text.splitlines() if "Closed 1 Tamer.exe" in l), "(closed by Windows' Restart Manager)"))
    print("installed over a running Tamer.exe; another copy left alone")
finally:
    for p in procs:
        if p.poll() is None:
            p.kill()
    unins = os.path.join(app, "unins000.exe")
    if os.path.isfile(unins):
        subprocess.run([unins, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=120)
        time.sleep(2)
    shutil.rmtree(tmp, ignore_errors=True)
print("ALL OK")

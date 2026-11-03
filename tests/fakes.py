"""Puts the pretend ARK server and AsaApi loader in place, on any OS.

On Linux/macOS the scripts run as they are. Windows needs a real .exe, so the first use builds one with
PyInstaller (test-only: pip install pyinstaller) into the temp folder, and rebuilds it only when the scripts
change. One exe plays both parts: see fake_entry.py. It's built as a folder, not --onefile, because a onefile
exe runs as two processes and the tests need the pid Tamer sees to be the fake server itself.
"""
import hashlib, os, shutil, signal, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = ("fake_entry.py", "fake_ark_server.py", "fake_loader.py")
BUILD = os.path.join(tempfile.gettempdir(), "tamer_fakes")
WIN = os.name == "nt"


def _built_dir():
    h = hashlib.sha256()
    for f in SOURCES:
        with open(os.path.join(HERE, f), "rb") as fh:
            h.update(fh.read())
    return os.path.join(BUILD, h.hexdigest()[:12])


def ensure_built():
    """Build the Windows exe if it isn't there yet. Returns its folder (None on other systems)."""
    if not WIN:
        return None
    out = _built_dir()
    if os.path.isfile(os.path.join(out, "dist", "fake", "fake.exe")):
        return os.path.join(out, "dist", "fake")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--console", "--name", "fake",
                        "--distpath", os.path.join(out, "dist"), "--workpath", os.path.join(out, "work"),
                        "--specpath", out, "--paths", HERE, "--hidden-import", "tempfile",
                        os.path.join(HERE, "fake_entry.py")], capture_output=True, text=True, timeout=300)
    if r.returncode:
        shutil.rmtree(out, ignore_errors=True)
        raise SystemExit("Couldn't build the test exe. Is PyInstaller installed? (pip install pyinstaller)\n" + r.stderr[-1500:])
    return os.path.join(out, "dist", "fake")


def _copy_runtime(dest_dir):
    src = os.path.join(ensure_built(), "_internal")
    shutil.copytree(src, os.path.join(dest_dir, "_internal"), dirs_exist_ok=True)


def install_server(exe):
    """Put the pretend server at `exe` (the path of ArkAscendedServer.exe)."""
    if WIN:
        _copy_runtime(os.path.dirname(exe))
        shutil.copy(os.path.join(ensure_built(), "fake.exe"), exe)
    else:
        shutil.copy(os.path.join(HERE, "fake_ark_server.py"), exe)
        os.chmod(exe, 0o755)


def loader_bytes():
    """The contents of a pretend AsaApiLoader.exe, for the fake AsaApi release zip."""
    path = os.path.join(ensure_built(), "fake.exe") if WIN else os.path.join(HERE, "fake_loader.py")
    with open(path, "rb") as f:
        return f.read()


def crash(pid):
    """Kill a process the way a crash would."""
    if WIN:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    else:
        os.kill(pid, signal.SIGKILL)


def cpu_settings(pid):
    """(below_normal, set of allowed core numbers) for a running process."""
    if not WIN:
        return os.getpriority(os.PRIO_PROCESS, pid) == 10, os.sched_getaffinity(pid)
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.GetPriorityClass.argtypes = (wintypes.HANDLE,)
    k32.GetProcessAffinityMask.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    assert h, f"can't open process {pid}"
    mask, system = ctypes.c_size_t(), ctypes.c_size_t()
    assert k32.GetProcessAffinityMask(h, ctypes.byref(mask), ctypes.byref(system))
    below = k32.GetPriorityClass(h) == 0x4000  # BELOW_NORMAL_PRIORITY_CLASS
    k32.CloseHandle(h)
    return below, {i for i in range(64) if mask.value >> i & 1}

"""Run Tamer's test suite.

    python tests/run_tests.py            # every test that can run on this OS
    python tests/run_tests.py gui_passive test_cfkey   # just these
    python tests/run_tests.py --all      # include the slow background-service test
    python tests/run_tests.py --show     # Windows: show the test windows (they're hidden by default)

On Windows the tests run on a hidden desktop of their own, so their windows (Tamer's, and the pretend server's
console windows) never appear on your screen or take your keyboard while you work.

Each test is a standalone script: python <test>.py <app folder> <screenshot folder> [extra args].
On Linux, GUI tests need a display (run under xvfb-run). Screenshots are only taken when
ImageMagick's `import` is installed; otherwise they are skipped.
"""
import os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)  # tests/ sits inside the Tamer folder
# Tests run against a throwaway copy of the app, because Tamer keeps its data (manager_data, servers,
# backups, cluster) next to tamer.py - running them in your real folder would wipe your real setup.
APP = os.path.join(tempfile.gettempdir(), "tamer_test_app")
APP_FILES = ("tamer.py", "ark_manager.py", "tamer.ico", "tamer.png")
SHOTS = os.path.join(tempfile.gettempdir(), "tamer_shots")

# Logic and GUI tests: run anywhere.
PORTABLE = ["test_core", "test_urls", "test_import", "test_installer_env", "test_installer_update", "test_bm", "test_cfkey", "test_mods", "test_crash_details", "test_rate_events", "test_status_board", "test_cluster_dir", "test_check_safety", "test_update_when_empty",
            "gui_dark", "gui_tasks", "gui_perf", "gui_diag", "gui_f4", "gui_updall", "gui_cmdline",
            "gui_plugins", "gui_passive", "gui_cfkey", "gui_copy", "gui_scroll", "gui_kofi", "gui_update", "gui_welcome", "gui_import", "gui_no_servers", "gui_mod_names", "gui_mod_settings", "gui_bug_report", "gui_reorder", "gui_text_size", "gui_admins", "gui_events", "gui_read_only", "gui_progress", ("gui_small", "1100", "700", "1.25"), ("gui_small", "1366", "728", "1.0")]
# These start a pretend ArkAscendedServer.exe. On Windows that's a real exe built by fakes.py, which needs
# PyInstaller (pip install pyinstaller). Tamer itself doesn't.
PROCESS =["test_cmdline", "test_crash_countdown", "test_automation", "test_diag_net",
           "test_update_all", "test_f4", "test_asaapi", "test_mod_wait", "test_log_window"]
SLOW = ["test_tasks_service"]  # ~4 minutes


HIDDEN_FLAG = "TAMER_TESTS_HIDDEN"  # set in the copy of this runner that runs on the hidden desktop


def run_on_hidden_desktop():
    """Windows: run this same command on a new, never-shown desktop and pass its output through.
    Every window a test opens goes there too (child processes inherit the desktop), so nothing pops up.
    Returns the exit code, or None if the desktop couldn't be made (then the tests run here as usual)."""
    import ctypes, msvcrt
    from ctypes import wintypes
    u32, k32 = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    u32.CreateDesktopW.restype = wintypes.HANDLE
    u32.CreateDesktopW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
                                   wintypes.DWORD, ctypes.c_void_p)
    u32.CloseDesktop.argtypes = (wintypes.HANDLE,)
    name = f"TamerTests{os.getpid()}"
    desk = u32.CreateDesktopW(name, None, None, 0, 0x10000000, None)  # GENERIC_ALL
    if not desk:
        print(f"(Couldn't make a hidden desktop, error {ctypes.get_last_error()} - showing the test windows.)")
        return None

    class STARTUPINFO(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                    ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    k32.CreateProcessW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                   wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                   ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION))
    k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)

    out_path = os.path.join(tempfile.gettempdir(), f"tamer_tests_{os.getpid()}.txt")
    out = open(out_path, "wb")
    handle = msvcrt.get_osfhandle(out.fileno())
    os.set_handle_inheritable(handle, True)
    si = STARTUPINFO(cb=ctypes.sizeof(STARTUPINFO), lpDesktop=f"WinSta0\\{name}", dwFlags=0x100,  # USESTDHANDLES
                     hStdOutput=handle, hStdError=handle)
    pi = PROCESS_INFORMATION()
    cmd = subprocess.list2cmdline([sys.executable, "-u", os.path.abspath(__file__)] + sys.argv[1:])
    env = dict(os.environ, **{HIDDEN_FLAG: "1", "PYTHONIOENCODING": "utf-8"})
    block = ctypes.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in env.items()) + "\0")
    ok = k32.CreateProcessW(None, cmd, None, None, True, 0x08000400,  # CREATE_NO_WINDOW | UNICODE_ENVIRONMENT
                            block, os.getcwd(), ctypes.byref(si), ctypes.byref(pi))
    out.close()
    if not ok:
        print(f"(Couldn't start the tests on a hidden desktop, error {ctypes.get_last_error()} - showing them.)")
        u32.CloseDesktop(desk)
        return None
    print("Running the tests on a hidden desktop, so no windows pop up (use --show to see them).", flush=True)
    code = wintypes.DWORD()
    with open(out_path, "rb") as f:  # pass the output through as it comes
        while True:
            done = k32.WaitForSingleObject(pi.hProcess, 500) == 0
            chunk = f.read()
            if chunk:
                sys.stdout.write(chunk.decode("utf-8", "replace").replace("\r\n", "\n"))
                sys.stdout.flush()
            if done:
                break
    k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    for h in (pi.hProcess, pi.hThread):
        k32.CloseHandle(h)
    u32.CloseDesktop(desk)
    try:
        os.remove(out_path)
    except OSError:
        pass
    return code.value


def main():
    if os.name == "nt" and "--show" not in sys.argv and not os.environ.get(HIDDEN_FLAG):
        code = run_on_hidden_desktop()
        if code is not None:
            sys.exit(code)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    plan = PORTABLE + PROCESS + (SLOW if "--all" in sys.argv and os.name != "nt" else [])
    if args:
        plan = [t for t in plan if (t[0] if isinstance(t, tuple) else t) in args] or args
    if any(t in PROCESS or t in SLOW for t in plan):
        sys.path.insert(0, HERE)
        import fakes
        fakes.ensure_built()  # up front, so a slow build can't use up one test's time limit
    os.makedirs(SHOTS, exist_ok=True)
    results = []
    for t in plan:
        name, extra = (t[0], list(t[1:])) if isinstance(t, tuple) else (t, [])
        # Fresh copy of the app for every test, so each starts from a clean slate.
        shutil.rmtree(APP, ignore_errors=True)
        os.makedirs(APP)
        for f in APP_FILES:
            if os.path.exists(os.path.join(SRC, f)):
                shutil.copy2(os.path.join(SRC, f), APP)
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, os.path.join(HERE, name + ".py"), APP, SHOTS] + extra,
                               cwd=HERE, capture_output=True, text=True, timeout=420)
            ok = p.returncode == 0
            out = (p.stdout + p.stderr).strip().splitlines()
        except subprocess.TimeoutExpired:
            ok, out = False, ["timed out (a dialog may be waiting for input)"]
        results.append((name, ok))
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({time.time() - t0:.0f}s)")
        if not ok:
            print("      " + "\n      ".join(out[-12:]))
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f" - failed: {', '.join(failed)}" if failed else ""))
    if os.name == "nt" and not args:
        print("(test_tasks_service isn't run on Windows yet.)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

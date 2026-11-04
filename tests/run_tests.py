"""Run Tamer's test suite.

    python tests/run_tests.py            # every test that can run on this OS
    python tests/run_tests.py gui_passive test_cfkey   # just these
    python tests/run_tests.py --all      # include the slow background-service test

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
PORTABLE = ["test_core", "test_urls", "test_import", "test_installer_env", "test_installer_update", "test_bm", "test_cfkey", "test_mods",
            "gui_dark", "gui_tasks", "gui_perf", "gui_diag", "gui_f4", "gui_updall", "gui_cmdline",
            "gui_plugins", "gui_passive", "gui_cfkey", "gui_copy", "gui_scroll", "gui_kofi", "gui_update", "gui_welcome", "gui_import", "gui_no_servers", "gui_mod_names", "gui_mod_settings", "gui_bug_report", "gui_reorder", "gui_text_size", ("gui_small", "1100", "700", "1.25"), ("gui_small", "1366", "728", "1.0")]
# These start a pretend ArkAscendedServer.exe. On Windows that's a real exe built by fakes.py, which needs
# PyInstaller (pip install pyinstaller). Tamer itself doesn't.
PROCESS =["test_cmdline", "test_crash_countdown", "test_automation", "test_diag_net",
           "test_update_all", "test_f4", "test_asaapi", "test_mod_wait", "test_log_window"]
SLOW = ["test_tasks_service"]  # ~4 minutes


def main():
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

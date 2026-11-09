"""Install / update progress: Tamer reads SteamCMD's "Update state ... progress:" lines and shows a bar with the
stage, percent and GB under the server's build info, plus "Installing 45%" in the server list. Before SteamCMD
gives numbers the bar just moves; after it finishes the bar goes away. A pretend SteamCMD (a Python script that
waits for go-files) plays each stage."""
import os, sys, tempfile, time
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk

assert am.parse_steam_progress(
    "Update state (0x61) downloading, progress: 45.23 (6012345678 / 13293847562)") == \
    ("Downloading", 45.23, 6012345678, 13293847562)
assert am.parse_steam_progress("Update state (0x81) verifying update, progress: 99.10 (5 / 10)")[0] == "Checking files"
assert am.parse_steam_progress("Update state (0x5) validating, progress: 3.00 (3 / 100)")[0] == "Validating"
assert am.parse_steam_progress("Update state (0x3) reconfiguring, progress: 0.00 (0 / 0)") == ("Getting ready", None, 0, 0)
assert am.parse_steam_progress("[ 45%] Downloading update (1,234 of 5,678 KB)...") is None

work = tempfile.mkdtemp(prefix="tamer_progress_")
go1, go2 = os.path.join(work, "go1"), os.path.join(work, "go2")
fake = os.path.join(work, "fake_steamcmd.py")
with open(fake, "w", encoding="utf-8") as f:
    f.write(f"""import os, sys, time
def say(t):
    print(t, flush=True)
def wait(p):
    while not os.path.exists(p):
        time.sleep(0.05)
say("Redirecting stderr to 'logs/stderr.txt'")
say(" Update state (0x61) downloading, progress: 45.23 (6012345678 / 13293847562)")
wait({go1!r})
say(" Update state (0x101) committing, progress: 99.99 (13293847562 / 13293847562)")
wait({go2!r})
exe = os.path.join(sys.argv[1], {am.SERVER_EXE_REL!r})
os.makedirs(os.path.dirname(exe), exist_ok=True)
open(exe, "w").close()
say("Success! App '2430930' fully installed.")
""")

cfg = am.AppConfig(); cfg.data.update(theme="dark", tamer_update_check=False, backup_before_update=False)
cfg.data["servers"] = []
s = am.default_server(1, cfg.servers); s.update(name="Alpha", install_dir=os.path.join(work, "Alpha"))
cfg.servers.append(s); cfg.save()

am.Manager.ensure_steamcmd = lambda self, srv: "steamcmd"
real_run = am.Manager._run_streamed
am.Manager._run_streamed = lambda self, srv, cmd, on_progress=None: real_run(
    self, srv, [sys.executable, fake, srv["install_dir"]], on_progress)
am.messagebox.showinfo = am.messagebox.showerror = lambda *a, **k: None
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())


def wait_for(cond, what, secs=20):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.05)
        if cond():
            return
    raise AssertionError(f"timed out waiting for {what}: label={app.prog_lbl.cget('text')!r} "
                         f"status={app.tree.item(s['id'], 'values')}")


def status():
    return app.tree.item(s["id"], "values")[1]


def a():
    app.tree.selection_set(s["id"]); root.update()
    assert not app.prog_row.winfo_manager()  # no bar when nothing is installing
    app.mgr.run_op(s, "Updating", app.mgr.op_update, False)
    wait_for(lambda: "45%" in app.prog_lbl.cget("text"), "the download stage")
    assert app.prog_row.winfo_manager() == "pack"
    assert app.prog_lbl.cget("text") == "Installing: Downloading... 45% (5.6 of 12.4 GB)", app.prog_lbl.cget("text")
    assert float(app.prog_bar.cget("value")) == 45.23 and str(app.prog_bar.cget("mode")) == "determinate"
    assert status() == "Installing 45%", status()
    open(go1, "w").close()
    wait_for(lambda: "Putting files in place" in app.prog_lbl.cget("text"), "the commit stage")
    assert "sit still for a while" in app.prog_lbl.cget("text") and status() == "Installing 100%", status()
    open(go2, "w").close()
    wait_for(lambda: not app.mgr.runtime(s["id"]).busy and not app.prog_row.winfo_manager(), "the end")
    root.update()
    assert app.mgr.is_installed(s) and app.mgr.runtime(s["id"]).progress is None
    assert status() not in ("", "Installing 100%"), status()
    # the "no numbers yet" state is a moving bar
    app.mgr.runtime(s["id"]).progress = ("Updating", "Getting ready", None, 0, 0); app._refresh_header(); root.update()
    assert str(app.prog_bar.cget("mode")) == "indeterminate" and app.prog_lbl.cget("text") == "Updating: Getting ready..."
    app.mgr.runtime(s["id"]).progress = None; app._refresh_header(); root.update()
    assert not app.prog_row.winfo_manager()
    print("progress: parsed stages, bar + label + list percent, moving bar without numbers, hidden after")
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")

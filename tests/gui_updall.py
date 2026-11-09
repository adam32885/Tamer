"""Update all window: a run carries on when the window is closed (Close or the X), and a window opened again
mid-run shows each server's status, can Cancel remaining, and can't start a second run. Ends with a screenshot."""
import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
import os, subprocess, sys, threading, time
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
cfg = am.AppConfig(); cfg.data["theme"] = "dark"
while len(cfg.servers) < 3: cfg.servers.append(am.default_server(len(cfg.servers) + 1, cfg.servers))
cfg.save()
am.messagebox.askyesno = lambda *a, **k: True
runs, release = [], threading.Event()


def fake_update_all(servers, progress=lambda s, st: None, cancel=None, **opts):
    """Updates the first server until released or cancelled; the rest are cancelled or done."""
    runs.append(opts)
    progress(servers[0], "Updating")
    while not release.is_set() and not cancel.is_set():
        time.sleep(0.05)
    for s in servers[1:]:
        progress(s, "Cancelled" if cancel.is_set() else "Done")
    progress(servers[0], "Done - build 41293817")


root = tk.Tk(); app = am.App(root); errors = []; root.report_callback_exception = lambda *a: errors.append(a)
app.mgr.update_all = fake_update_all


def wait_for(cond, what, secs=10):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.05)
        if cond():
            return
    raise AssertionError(f"timed out waiting for {what}")


def statuses(w):
    return [w.ua_tree.set(i, "status") for i in w.ua_tree.get_children()]


def go():
    app._update_all_dialog(); w = app._update_all_win
    w.ua_start.invoke()
    wait_for(lambda: statuses(w) == ["Updating", "Waiting for its turn", "Waiting for its turn"], "the run to start")
    assert str(w.ua_start.cget("state")) == "disabled" and str(w.ua_cancel.cget("state")) == "normal"
    # the X hides the window (like Close) - the run carries on
    root.tk.call(w.protocol("WM_DELETE_WINDOW")); root.update()
    assert w.winfo_exists() and w.state() == "withdrawn", w.state()
    app._update_all_dialog(); root.update()
    assert app._update_all_win is w and w.state() != "withdrawn"
    # even a brand-new window (the old one gone) knows about the run
    w.destroy(); root.update()
    app._update_all_dialog(); w2 = app._update_all_win
    assert w2 is not w and statuses(w2) == ["Updating", "Waiting for its turn", "Waiting for its turn"], statuses(w2)
    assert str(w2.ua_start.cget("state")) == "disabled", "a second run must not start"
    assert str(w2.ua_cancel.cget("state")) == "normal"
    w2.ua_start.invoke(); root.update()
    assert len(runs) == 1, runs
    # Cancel remaining from the new window stops the run
    w2.ua_cancel.invoke()
    wait_for(lambda: str(w2.ua_start.cget("state")) == "normal", "the run to finish")
    assert statuses(w2) == ["Done - build 41293817", "Cancelled", "Cancelled"], statuses(w2)
    assert w2.ua_start.cget("text") == "Run again" and str(w2.ua_cancel.cget("state")) == "disabled"
    # and a new run can start afterwards
    release.set(); w2.ua_start.invoke()
    wait_for(lambda: statuses(w2) == ["Done - build 41293817", "Done", "Done"] and
             str(w2.ua_start.cget("state")) == "normal", "the second run")
    assert len(runs) == 2
    print("update all: X hides, reopened window shows the run, cancel works, no second run while busy")
    tree = w2.ua_tree; ids = tree.get_children()
    tree.set(ids[0], "status", "Done - build 41293817"); tree.set(ids[1], "status", "Waiting for it to come back online (2m 14s)"); tree.set(ids[2], "status", "Waiting for its turn")
    root.after(900, lambda: (_shot(["import", "-window", "root", "-crop", "1280x820+0+0", sys.argv[2] + "/updall.png"]), app.mgr.stop_event.set(), root.destroy()))
root.after(1500, go); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")

"""Tamer's own update check, against a pretend GitHub: the "Update to ..." link, the update window, downloading and
starting the installer (only for the installer's copy), "you have the latest", and no releases yet."""
import json, os, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

state = {"release": None}  # what the pretend GitHub answers; None = 404


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path.endswith("/download/slow.exe"):     # 2 MB, slowly: time to watch the progress and cancel
            self.send_response(200); self.send_header("Content-Length", str(2 * 1024 * 1024)); self.end_headers()
            try:
                for _ in range(32):
                    self.wfile.write(b"x" * 65536); __import__("time").sleep(0.15)
            except OSError:
                pass
            return
        if self.path.endswith("/download/Tamer-Setup-99.0.0.exe"):
            body = b"pretend installer"
        elif self.path.endswith("/releases/latest") and state["release"]:
            body = json.dumps(state["release"]).encode()
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ["ASM_TAMER_API"] = base + "/repos/x/Tamer/releases/latest"
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk

assert am.version_tuple("v1.15.10") > am.version_tuple("1.15.9") > am.version_tuple("1.15") and \
    am.version_tuple("1.16.0") == (1, 16, 0), "versions compare as numbers"
assert am.plain_notes("## New\n- **Welcome** for `new` users, see [the README](https://x)\n* more") == \
    "New\n• Welcome for new users, see the README\n• more", "release notes shown as plain text"
NEWER = {"tag_name": "v99.0.0", "body": "- **Something new**", "html_url": base + "/releases/tag/v99.0.0",
         "assets": [{"name": "Tamer-Setup-99.0.0.exe", "browser_download_url": base + "/download/Tamer-Setup-99.0.0.exe"}]}

cfg = am.AppConfig(); cfg.data.update(theme="dark", tamer_update_check=False); cfg.save()  # no automatic check
am.Manager.ensure_steamcmd = lambda self, s: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
asked, infos, opened, started = [], [], [], []
am.messagebox.askyesno = lambda t, m, **k: asked.append(m) or answer[0]
am.messagebox.showinfo = lambda t, m, **k: infos.append(m)
am.webbrowser.open = opened.append
real_popen = am.subprocess.Popen
am.subprocess.Popen = lambda cmd, *a, **k: started.append(cmd) if "Tamer-Setup" in str(cmd) else \
    real_popen(cmd, *a, **k)  # never run an installer in tests; Tamer's other commands still run
answer = [True]
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())
exited = []
app._exit = lambda: exited.append(True)


def after(cond, then, tries=60):
    root.update()
    if cond(): then()
    elif tries: root.after(100, lambda: after(cond, then, tries - 1))
    else: raise SystemExit(f"timed out before {then.__name__}")


def a():  # no releases published yet - checked by clicking the top-bar link
    root.update()
    assert app.check_link.winfo_ismapped() and app.check_link.cget("text") == "Check for updates"
    assert app.check_link.winfo_rootx() < app.kofi_link.winfo_rootx(), "left of the Ko-fi link"
    app.check_link.event_generate("<Button-1>"); root.update()
    assert app.check_link.cget("text") == "Checking...", "shows it's checking"
    after(lambda: infos, b)


def b():
    assert "No Tamer releases" in infos[-1] and not app.update_link.winfo_ismapped(), infos
    assert app.check_link.winfo_ismapped() and app.check_link.cget("text") == "Check for updates"
    state["release"] = NEWER                           # a newer version comes out
    app._tamer_update_check()
    after(lambda: app.tamer_update, c)


def c():
    root.update()
    assert app.update_link.winfo_ismapped() and app.update_link.cget("text") == "⬆ Update to 99.0.0"
    assert app.update_link.winfo_rootx() < app.kofi_link.winfo_rootx(), "left of the Ko-fi link"
    assert not app.check_link.winfo_ismapped(), "the green update link takes its place"
    assert not am.tamer_installed_copy(), "tests run from source"
    app.update_link.event_generate("<Button-1>"); root.update()   # not the installer's copy: release page only
    assert "wasn't set up with the installer" in asked[-1] and "• Something new" in asked[-1], asked[-1]
    assert "**" not in asked[-1], "no Markdown markers in the update window"
    assert opened == [NEWER["html_url"]] and not started, (opened, started)
    am.tamer_installed_copy = lambda: True             # now pretend this is the installed copy
    app._tamer_update_dialog()
    assert "Download and install it now?" in asked[-1], asked[-1]
    after(lambda: started, d)


def d():
    path = started[0][0]
    assert os.path.basename(path) == "Tamer-Setup-99.0.0.exe" and open(path, "rb").read() == b"pretend installer"
    assert exited, "Tamer closes so the installer can replace it"
    log = open(os.path.join(am.DATA_DIR, "logs", "update.log"), encoding="utf-8").read()
    assert "downloading" in log and "Installer started" in log, log
    os.remove(path)
    # a slow download: the window shows how far it's got, and Cancel stops it cleanly
    slow = {"version": "98.0.0", "name": "Tamer-Setup-98.0.0.exe", "url": base + "/download/slow.exe", "page": base + "/p"}
    app._tamer_update_install(slow)
    after(lambda: " of 2.0 MB" in label_text(), lambda: cancel_it(slow), tries=80)


def cancel_it(slow):
    assert "Downloading Tamer 98.0.0..." in label_text() and " of 2.0 MB" in label_text(), label_text()
    next(b for b in app.update_win.winfo_children()[0].winfo_children()
         if isinstance(b, am.ttk.Button) and b.cget("text") == "Cancel").invoke()
    after(lambda: not app.update_win.winfo_exists(), lambda: cancelled(slow), tries=80)


def label_text():
    return " ".join(w.cget("text") for w in app.update_win.winfo_children()[0].winfo_children()
                    if isinstance(w, am.ttk.Label))


def cancelled(slow):
    target = os.path.join(tempfile.gettempdir(), slow["name"])
    assert not os.path.exists(target) and not os.path.exists(target + ".part"), "nothing left behind"
    assert len(started) == 1 and len(exited) == 1, "not run, Tamer not closed"
    # a download that fails: say why, offer the release page
    asked.clear(); opened.clear()
    app._tamer_update_install(dict(slow, url=base + "/download/missing.exe"))
    after(lambda: asked, failed, tries=80)


def failed():
    assert "Couldn't download the update" in asked[-1] and "release page" in asked[-1], asked
    assert opened == [base + "/p"] and len(started) == 1, (opened, started)
    print("progress shown, Cancel cleans up, failures explained")
    state["release"] = dict(NEWER, tag_name=am.APP_VERSION)  # caught up: nothing newer
    infos.clear()
    app._tamer_update_check(manual=True)
    after(lambda: infos, e)


def e():
    assert f"You have the latest Tamer ({am.APP_VERSION})" in infos[-1] and not app.update_link.winfo_ismapped()
    assert app.check_link.winfo_ismapped(), "back to 'Check for updates' once up to date"
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")

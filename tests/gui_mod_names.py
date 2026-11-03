"""Mod details when CurseForge (the free proxy, since 2026) refuses "several mods at once" (POST /mods -> 404) but
answers one mod at a time: names still load, the mod update check still sees a new file, and when a name really
can't be fetched the Mods tab says so instead of showing "(loading...)" forever."""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODS = {111: ("Super Structures", 5001), 222: ("Awesome Spyglass", 6001), 333: ("Dino Storage", 7001)}
calls = {"post": 0, "get": 0}
mode = {"down": False}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def reply(self, code, obj=None):
        body = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_POST(self):  # like the real proxy now: batches are "not found"
        calls["post"] += 1
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.reply(404)

    def do_GET(self):
        calls["get"] += 1
        mid = self.path.rstrip("/").rsplit("/", 1)[-1]
        if mode["down"] or not mid.isdigit() or int(mid) not in MODS:
            return self.reply(404)
        name, file_id = MODS[int(mid)]
        self.reply(200, {"data": {"id": int(mid), "name": name, "mainFileId": file_id, "dateModified": "2026-11-01T00:00:00Z"}})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["ASM_CF_BASE"] = f"http://127.0.0.1:{srv.server_address[1]}/v1"
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk

# ---------- the CurseForge client on its own ----------
cf = am.CurseForge(lambda: "")
mods = cf.get_mods(["333", "111", "999", "222"])
assert [m["id"] for m in mods] == ["333", "111", "222"] and mods[1]["name"] == "Super Structures", mods
assert calls["post"] == 1 and calls["get"] == 4, calls
cf.get_mods(["111"])
assert calls["post"] == 1, "a refused batch isn't asked for again this session"
try:
    cf.get_mods(["999", "998"]); raise AssertionError("must fail when nothing at all can be fetched")
except RuntimeError as e:
    assert "404" in str(e)
print("batch refused: one at a time, unknown mods left out, all-unknown is an error")

# ---------- the mod update check still notices a new file ----------
cfg = am.AppConfig(); cfg.data.update(theme="dark", mod_check_min=0, update_check_min=0)
s = cfg.servers[0]; s["mods"] = "111,222,333"; cfg.data["mod_cache"] = {}; cfg.save()
m = am.Manager(cfg, lambda *a: None)
m.is_running = lambda srv: True
rt = m.runtime(s["id"]); rt.online = True
m.check_mod_updates()
assert rt.mod_files == {"111": "5001", "222": "6001", "333": "7001"}, rt.mod_files
MODS[222] = ("Awesome Spyglass", 6002)                # a new version comes out
m.check_mod_updates()
assert rt.mods_outdated == ["222"], rt.mods_outdated
print("mod update check works without batches")

# ---------- the Mods tab ----------
s["mods"] = "111,999"; cfg.data["mod_cache"] = {}; cfg.save()
am.Manager.ensure_steamcmd = lambda self, srv: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
shown = []
am.messagebox.showerror = lambda t, msg, **k: shown.append(msg)
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())


def names():
    return {i: app.itree.item(i, "values")[0] for i in app.itree.get_children()}


def after(cond, then, tries=80):
    root.update()
    if cond(): then()
    elif tries: root.after(100, lambda: after(cond, then, tries - 1))
    else: raise SystemExit(f"timed out before {then.__name__}: {names()}")


def a():
    app.nb.select(app.mods_tab); app._refresh_installed_mods()
    after(lambda: names().get("111") == "Super Structures", b)


def b():
    assert names()["999"] == "(name not found - click Refresh)", names()  # CurseForge doesn't know it
    mode["down"] = True                                  # now everything fails: say so, don't sit on "(loading...)"
    app.cfg.data["mod_cache"].pop("111"); app._mod_fetch_tried.clear(); app._refresh_installed_mods()
    after(lambda: "(loading...)" not in names().values(), c)


def c():
    assert set(names().values()) == {"(name not found - click Refresh)"}, names()
    assert any("Couldn't load the names of" in line for line in app.mgr.runtime(app.current()["id"]).log)
    mode["down"] = False                                 # Refresh tries again
    app._mod_fetch_info(force=True)
    after(lambda: names().get("111") == "Super Structures", d)


def d():
    print("Mods tab: names load, unknown ones say 'name not found', Refresh retries")
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")

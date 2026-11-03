import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
"""Mock CurseForge API -> test CurseForge client and the Mods tab end-to-end (headless)."""
import json, os, sys, threading, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

MODS = [{"id": 900000 + i, "name": f"Super Structures {i}" if i % 2 == 0 else f"Awesome Spyglass {i}",
         "slug": f"mod-{i}", "summary": f"Summary for mod {i}", "downloadCount": 1500000 - i * 1000,
         "dateModified": "2026-10-2%dT10:00:00Z" % (i % 10), "authors": [{"name": f"Author{i}"}],
         "links": {"websiteUrl": f"https://www.curseforge.com/ark-survival-ascended/mods/mod-{i}"},
         "categories": [{"name": "Maps" if i == 3 else "Structures"}]} for i in range(120)]
seen = []

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj):
        b = json.dumps(obj).encode(); self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        seen.append(("GET", u.path, q))
        assert u.path == "/v1/mods/search" and q["gameId"] == "83374"
        res = [m for m in MODS if q.get("searchFilter", "").lower() in m["name"].lower()]
        i, n = int(q["index"]), int(q["pageSize"])
        self._send({"data": res[i:i + n], "pagination": {"index": i, "pageSize": n, "resultCount": len(res[i:i+n]), "totalCount": len(res)}})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append(("POST", self.path, body))
        self._send({"data": [m for m in MODS if m["id"] in body["modIds"]]})

srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["ASM_CF_BASE"] = f"http://127.0.0.1:{srv.server_address[1]}/v1"
sys.path.insert(0, sys.argv[1])
import tamer as am

cf = am.CurseForge(lambda: "")
mods, total = cf.search("spyglass", "Last updated", 0, 50)
assert total == 60 and len(mods) == 50 and mods[0]["name"].startswith("Awesome") and mods[0]["author"] == "Author1"
assert seen[-1][2]["sortField"] == "3" and seen[-1][2]["sortOrder"] == "desc"
got = cf.get_mods(["900002", "900004", "bad"])
assert [m["id"] for m in got] == ["900002", "900004"]
print("client ok")

# Proxy/official selection
assert am.CurseForge.__init__  # base_override set from env in this test
os.environ.pop("ASM_CF_BASE")
assert am.CurseForge(lambda: "").using_proxy() and not am.CurseForge(lambda: "abc").using_proxy()
os.environ["ASM_CF_BASE"] = f"http://127.0.0.1:{srv.server_address[1]}/v1"

# ---- GUI flow
import tkinter as tk
from tkinter import messagebox
msgs = []
messagebox.showinfo = lambda *a, **k: msgs.append(("info", a[1]))
messagebox.showerror = lambda *a, **k: msgs.append(("error", a[1]))
messagebox.askyesno = lambda *a, **k: True
out = sys.argv[2]
root = tk.Tk()
app = am.App(root)
s = app.cfg.servers[0]
s["mods"] = "900010"          # pre-existing mod not in cache -> should be fetched by name
app.cfg.servers.append(dict(am.default_server(2, app.cfg.servers), cluster=True))
s["cluster"] = True
errors = []
root.report_callback_exception = lambda *a: errors.append(a)

def step1():
    app._load_form(); app._refresh_installed_mods()
    app.nb.select(2)
    app.mod_query.set("structures")
    app._mod_search()
    root.after(1500, step2)

def step2():
    assert len(app.mtree.get_children()) == 50, len(app.mtree.get_children())
    assert "Showing 50 of 60" in app.mod_status.cget("text")
    app._mod_search(more=True)
    root.after(1200, step3)

def step3():
    assert len(app.mtree.get_children()) == 60
    app.mtree.selection_set(["900000", "900002"])
    app._mod_show_details(app.mtree)
    app._mod_install(cluster=True)
    root.after(800, step4)

def step4():
    other = app.cfg.servers[1]
    assert s["mods"] == "900010,900000,900002", s["mods"]
    assert other["mods"] == "900000,900002", other["mods"]
    assert app.form_vars["mods"].get() == s["mods"]
    names = [app.itree.item(i, "text") for i in app.itree.get_children()]
    assert names == ["Super Structures 10", "Super Structures 0", "Super Structures 2"], names
    assert app.mtree.item("900000", "text").startswith("✓")
    assert "-mods=900010,900000,900002" in app.cmd_preview.get("1.0", "end")
    app.itree.selection_set("900002"); app._mod_move(-1)
    assert s["mods"] == "900010,900002,900000", s["mods"]
    app.itree.selection_set("900010"); app._mod_remove()
    assert s["mods"] == "900002,900000"
    app.itree.selection_set("900002"); app._mod_show_details(app.itree)
    root.after(600, shot)

def shot():
    _shot(["import", "-window", "root", os.path.join(out, "mods.png")])
    app.mgr.stop_event.set(); root.destroy()

root.after(1500, step1)
root.mainloop()
print("msgs:", msgs)
print("errors:", errors)
assert not errors
saved = json.load(open(app.cfg.path))
assert "900002" in saved["mod_cache"] and saved["servers"][0]["mods"] == "900002,900000"
print("ALL OK")

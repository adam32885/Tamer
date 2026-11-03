"""Help > Send a bug report: the zip has info, settings and logs (and the game logs if ticked), and not one of the
passwords, keys, tokens or webhook links - not even ones that only appear in a log."""
import json, os, sys, tempfile, zipfile
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
from tkinter import ttk

ADMIN, JOIN, OTHER = "AdminSecret123", "JoinSecret456", "OtherPw999"
CF_KEY = "$2a$10$" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefghijklmnopq"
HOOK = "https://discord.com/api/webhooks/1234567890/abcDEFghiJKL-secret_token"
BM = "bmTokenXYZ789"
SECRETS = [ADMIN, JOIN, OTHER, CF_KEY, HOOK, "abcDEFghiJKL-secret_token", BM]

tmp = tempfile.mkdtemp()
cfg = am.AppConfig(); cfg.data.update(theme="dark", curseforge_api_key=CF_KEY, discord_webhook=HOOK,
                                      battlemetrics_token=BM, tamer_update_check=False)
s = cfg.servers[0]; s.update(name="Island PvE", admin_password=ADMIN, server_password=JOIN,
                             install_dir=os.path.join(tmp, "srv"), mods="111,222")
cfg.save()
logs = os.path.join(am.DATA_DIR, "logs"); os.makedirs(logs, exist_ok=True)
open(os.path.join(logs, "Island_PvE_test.log"), "w").write(
    f"[2026] Starting: ArkAscendedServer.exe TheIsland_WP?listen?ServerAdminPassword={ADMIN}?ServerPassword={JOIN}\n"
    f"[2026] imported: ...?ServerAdminPassword=\\\"{OTHER}\\\" -mods=1\n[2026] Discord failed for {HOOK}\n"
    f"[2026] CurseForge key {CF_KEY} rejected\n[2026] something normal happened\n")
open(os.path.join(logs, "update.log"), "w").write("[2026] Updating from 1.19.0 to 1.20.0\n")
glog = os.path.join(s["install_dir"], am.GAMELOG_REL); os.makedirs(os.path.dirname(glog))
open(glog, "w").write("".join(f"line {i}\n" for i in range(800)) + f"Admin {ADMIN} logged in\n")
m = am.Manager(cfg, lambda *a: None)


def contents(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()}


out = os.path.join(tmp, "report.zip")
names = am.build_bug_report(cfg, m, out)
got = contents(out)
assert set(got) == set(names) and {"info.txt", "config.json", "logs/Island_PvE_test.log", "logs/update.log",
                                   "game_logs/Island_PvE_ShooterGame.log"} <= set(got), sorted(got)
everything = "\n".join(got.values())
leaked = [x for x in SECRETS if x in everything]
assert not leaked, f"secrets in the bug report: {leaked}"
c = json.loads(got["config.json"])
assert c["curseforge_api_key"] == c["discord_webhook"] == c["battlemetrics_token"] == "(removed)", c
assert c["servers"][0]["admin_password"] == c["servers"][0]["server_password"] == "(removed)"
assert f"Tamer {am.APP_VERSION}" in got["info.txt"] and "Island PvE" in got["info.txt"] and "CurseForge key set: yes" in got["info.txt"]
assert "something normal happened" in got["logs/Island_PvE_test.log"], "the rest of the log is kept"
game = got["game_logs/Island_PvE_ShooterGame.log"].splitlines()
assert len(game) == 500 and game[-1] == "Admin (removed) logged in", game[-3:]
print("bug report: right files, last 500 game-log lines, no secrets anywhere")
names = am.build_bug_report(cfg, m, out, game_logs=False)
assert not any(n.startswith("game_logs/") for n in names), "game logs only when ticked"

# ---------- the window ----------
asked, opened, popen = [], [], []
am.messagebox.askyesno = lambda t, msg, **k: asked.append(msg) or True
am.webbrowser.open = opened.append
real = am.subprocess.Popen
am.subprocess.Popen = lambda cmd, *a, **k: popen.append(cmd) if cmd and cmd[0] == "explorer" else real(cmd, *a, **k)
am.Manager.ensure_steamcmd = lambda self, srv: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())


def widgets(w, cls):
    out_ = [w] if isinstance(w, cls) else []
    for ch in w.winfo_children():
        out_ += widgets(ch, cls)
    return out_


def a():
    app._bug_report_dialog(); root.update()
    d = app.bug_win
    entry = widgets(d, ttk.Entry)[0]
    assert entry.get().endswith(".zip") and "Tamer-bug-report-" in entry.get()
    target = os.path.join(tmp, "from the window.zip")
    entry.delete(0, "end"); entry.insert(0, target)
    next(b for b in widgets(d, ttk.Button) if b.cget("text") == "Make the bug report").invoke(); root.update()
    assert os.path.isfile(target) and "game_logs/Island_PvE_ShooterGame.log" in contents(target)
    assert asked and "Bug report saved" in asked[-1] and opened == [am.BUG_REPORT_ISSUE_URL], (asked, opened)
    assert am.BUG_REPORT_ISSUE_URL.endswith("/issues/new?template=bug_report.yml")
    if os.name == "nt":
        assert popen and popen[-1][0] == "explorer" and popen[-1][-1] == os.path.normpath(target), popen
    print("window: saves the zip, shows it in Explorer, opens the GitHub form")
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")

"""Copy to other servers: what's copied, what never is, running servers, and the dialog."""
import glob, os, sys
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
def no_steamcmd(self, s): raise RuntimeError("no SteamCMD in tests")
am.Manager.ensure_steamcmd = no_steamcmd  # never download the real one

GUS_A = """[ServerSettings]
XPMultiplier=5.0
ServerAdminPassword=sourceadmin
ServerPassword=sourcepw
RCONPort=11111
RCONEnabled=True
ActiveMods=1,2
HarvestAmountMultiplier=3

[SessionSettings]
SessionName=Source Server
Port=7777
QueryPort=27015

[MessageOfTheDay]
Message=Welcome to source
"""
GUS_B = """[ServerSettings]
XPMultiplier=1.0
ServerAdminPassword=targetadmin
ServerPassword=targetpw
RCONPort=22222
TargetOnlySetting=gone

[SessionSettings]
SessionName=Target Server
Port=7779
QueryPort=27017
"""
GAME_A = "[/script/shootergame.shootergamemode]\nbUseSingleplayerSettings=True\n"

cfg = am.AppConfig(); cfg.data["theme"] = "dark"
while len(cfg.servers) < 4: cfg.servers.append(am.default_server(len(cfg.servers) + 1, cfg.servers))
a, b, c, e = cfg.servers
a.update(mods="111,222", passive_mods="222", restart_times="04:00", ram_restart_gb=30, backup_keep=7, cluster=True, asaapi=True,
         timed_tasks=[{"id": "t1"}], cmd_flags=["-servergamelog", "-NoWildBabies"], autostart=True, cpu_cores=[0], public_ip="1.2.3.4")
keep_b = {k: b[k] for k in am.COPY_KEEP_SETTINGS - {"mods", "passive_mods"}}
e["install_dir"] = a["install_dir"]
cfg.save()
m = am.Manager(cfg, lambda *x: None)
def ini(s, f): return os.path.join(m.config_dir(s), f)
def text_of(path): return am.read_text_file(path).replace("\r\n", "\n")  # Windows files end lines differently
os.makedirs(m.config_dir(a)); os.makedirs(m.config_dir(b))
am.write_text_file(ini(a, am.GUS), GUS_A); am.write_text_file(ini(a, am.GINI), GAME_A); am.write_text_file(ini(b, am.GUS), GUS_B)

# ---- nothing gets copied unless ticked
m.copy_settings_to(a, b)
assert b["mods"] == "" and b["backup_keep"] != 7

# ---- mods only
m.copy_settings_to(a, b, mods=True)
assert b["mods"] == "111,222" and b["passive_mods"] == "222" and b["backup_keep"] != 7
print("mods ok")

# ---- Tamer settings: identity and per-PC choices stay
m.copy_settings_to(a, b, settings=True)
assert b["restart_times"] == "04:00" and b["ram_restart_gb"] == 30 and b["backup_keep"] == 7
assert "-NoWildBabies" in b["cmd_flags"]
assert all(b[k] == v for k, v in keep_b.items()), {k: b[k] for k, v in keep_b.items() if b[k] != v}
b["cmd_flags"].append("-Foo"); assert "-Foo" not in a["cmd_flags"], "lists mustn't be shared between servers"
print("tamer settings ok")

# ---- game settings
note = m.copy_game_settings_to(a, b)
assert note.startswith("Game settings copied"), note
got = text_of(ini(b, am.GUS)); print(got)
for section, key, want in [("ServerSettings", "XPMultiplier", "5.0"), ("ServerSettings", "HarvestAmountMultiplier", "3"),
                           ("MessageOfTheDay", "Message", "Welcome to source"), ("SessionSettings", "SessionName", "Target Server"),
                           ("SessionSettings", "Port", "7779"), ("SessionSettings", "QueryPort", "27017"),
                           ("ServerSettings", "RCONPort", "22222"), ("ServerSettings", "ServerAdminPassword", "targetadmin"),
                           ("ServerSettings", "ServerPassword", "targetpw")]:
    assert am.ini_get(got, section, key) == want, (key, am.ini_get(got, section, key))
assert "sourceadmin" not in got and "sourcepw" not in got and "ActiveMods" not in got and "TargetOnlySetting" not in got
assert text_of(ini(b, am.GINI)).strip() == GAME_A.strip()
old = glob.glob(ini(b, am.GUS) + ".before-copy-*")
assert len(old) == 1 and text_of(old[0]) == GUS_B, "the old file is kept"
assert text_of(ini(a, am.GUS)) == GUS_A, "the source isn't touched"
print("game settings ok")

# ---- a server that's never been started gets no source passwords either
note = m.copy_game_settings_to(a, c)
assert note.startswith("Game settings copied")
got = text_of(ini(c, am.GUS))
assert "sourceadmin" not in got and "7777" not in got and "Source Server" not in got, got

# ---- skipped cases
before = text_of(ini(b, am.GUS)) + "x"
am.write_text_file(ini(b, am.GUS), before)
m.is_running = lambda s: s is b
assert "the server is running" in m.copy_game_settings_to(a, b)
assert text_of(ini(b, am.GUS)) == before, "a running server's files aren't touched"
del m.is_running
assert "share the same folder" in m.copy_game_settings_to(a, e)
assert text_of(ini(a, am.GUS)) == GUS_A, "a server sharing the folder is left alone"
assert "no game settings files" in m.copy_game_settings_to(b.__class__(c, name="Empty", install_dir=os.path.join(am.BASE_DIR, "servers", "none")), b)
print("skips ok")

# ---- the dialog
a["autostart"] = False  # auto-start would make the app really install the server
cfg.save()
root = tk.Tk(); app = am.App(root); errors = []; root.report_callback_exception = lambda *x: (errors.append(x), __import__("traceback").print_exception(*x), root.destroy())
shown = []
am.messagebox.showinfo = lambda *x, **k: shown.append(x[1]); am.messagebox.askyesno = lambda *x, **k: True
d = cfg.servers[3]
def go():
    app.tree.selection_set(app.cfg.servers[0]["id"]); root.update()
    app._copy_dialog(); root.update(); w = app._copy_win
    boxes = [x for x in w.winfo_children()[0].winfo_children() if x.winfo_class() == "TCheckbutton"]
    assert len(boxes) == 6, len(boxes)                                  # 3 servers, 3 kinds of thing
    w.destroy()
    fresh = app.cfg.servers[2]; fresh["mods"] = ""
    app._copy_run(app.cfg.servers[0], [fresh], True, True, True); wait(0)
def wait(n):
    if shown or n > 100:
        return done()
    root.after(100, wait, n + 1)
def done():
    print(shown); assert shown and shown[0].startswith(app.cfg.servers[2]["name"]) and "Mods and Tamer settings copied." in shown[0]
    assert am.AppConfig().servers[2]["mods"] == "111,222", "saved to disk"
    app.mgr.stop_event.set(); root.destroy()
root.after(1500, go); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")

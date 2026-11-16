"""Read-only server files (often left by another server manager): the Game tab shows a yellow line with
'Make them writable'; saving asks first instead of failing with "Access is denied"; a start leaves the files
alone but says why in the Log; rate events, the admin list and copying settings say what's wrong; Troubleshoot
lists it; and .bak copies of a read-only file are ordinary files."""
import os, stat, sys, tempfile
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk

work = tempfile.mkdtemp(prefix="tamer_ro_")
ro = lambda p: os.chmod(p, stat.S_IREAD)
writable = lambda p: os.access(p, os.W_OK)

# backup_copy and write_text_file on their own
src, dst = os.path.join(work, "a.ini"), os.path.join(work, "a.ini.bak")
with open(src, "w") as f:
    f.write("x=1\n")
ro(src)
am.backup_copy(src, dst)
assert writable(dst) and open(dst).read() == "x=1\n", "a backup of a read-only file must be an ordinary file"
ro(dst); am.backup_copy(src, dst); assert writable(dst)  # and a read-only old backup is replaced
try:
    am.write_text_file(src, "x=2\n")
    raise AssertionError("wrote a read-only file")
except am.ReadOnlyFile as e:
    assert str(e) == "a.ini is read-only" and e.path == src
am.make_writable(src); am.write_text_file(src, "x=2\n"); assert open(src).read() == "x=2\n"

cfg = am.AppConfig(); cfg.data.update(theme="dark", tamer_update_check=False); cfg.data["servers"] = []
for i, name in enumerate(("Alpha", "Bravo"), 1):
    s = am.default_server(i, cfg.servers); s.update(name=name, install_dir=os.path.join(work, name))
    cfg.servers.append(s)
    os.makedirs(os.path.join(s["install_dir"], am.CONFIG_REL))
    with open(os.path.join(s["install_dir"], am.CONFIG_REL, "GameUserSettings.ini"), "w") as f:
        f.write("[ServerSettings]\nTamingSpeedMultiplier=1\n")
    with open(os.path.join(s["install_dir"], am.CONFIG_REL, "Game.ini"), "w") as f:
        f.write("[/script/shootergame.shootergamemode]\n")
    with open(am.admin_file(s), "w") as f:
        f.write("")
    s["admins_imported"] = True
cfg.data["rate_events"] = [{"id": "e", "name": "Always", "enabled": True, "repeat": "weekly", "start_day": 0,
                            "start_time": "00:00", "end_day": 0, "end_time": "00:00", "servers": [cfg.servers[0]["id"]],
                            "settings": [["GameUserSettings.ini", "ServerSettings", "TamingSpeedMultiplier", "3"]]}]
cfg.save()
A = cfg.servers[0]
gus = os.path.join(A["install_dir"], am.CONFIG_REL, "GameUserSettings.ini")
gini = os.path.join(A["install_dir"], am.CONFIG_REL, "Game.ini")
for p in (gus, gini, am.admin_file(A)):
    ro(p)

am.Manager.ensure_steamcmd = lambda self, srv: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
infos, errs, asks, answer = [], [], [], [False]
am.messagebox.showinfo = lambda t, m, **k: infos.append(m)
am.messagebox.showerror = lambda t, m, **k: errs.append(m)
am.messagebox.askyesno = lambda t, m, **k: asks.append(m) or answer[0]
am.simpledialog.askstring = lambda t, m, **k: {"EOS": "0002" + "a" * 28}.get("EOS") if "EOS ID" in m else ""
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())


def srv(name):
    return next(s for s in app.cfg.servers if s["name"] == name)


def a():
    app.tree.selection_set(srv("Alpha")["id"]); root.update()
    assert app.ro_row.winfo_manager() == "pack"
    text = app.ro_lbl.cget("text")
    assert text.startswith("GameUserSettings.ini, Game.ini, AllowedCheaterAccountIDs.txt are read-only"), text
    app.tree.selection_set(srv("Bravo")["id"]); root.update()
    assert not app.ro_row.winfo_manager(), "Bravo's files are fine"
    app.tree.selection_set(srv("Alpha")["id"]); root.update()
    s = srv("Alpha")
    # rate events: nothing changes, and it says why
    state_before = dict(s.get("rate_event_state") or {})
    try:
        am.apply_rate_events(app.cfg, s, app.mgr.config_dir(s))
        raise AssertionError("applied to a read-only file")
    except am.ReadOnlyFile:
        pass
    assert (s.get("rate_event_state") or {}) == state_before
    # a start: files left alone, the Log says why
    app.mgr.is_installed = lambda x: True
    app.mgr.ports_in_use_by_other = lambda x: None
    app.mgr.build_command = lambda x: (_ for _ in ()).throw(RuntimeError("stop here"))
    try:
        app.mgr._start(s)
    except RuntimeError:
        pass
    log = "\n".join(app.mgr.runtime(s["id"]).log)
    assert "are read-only, so Tamer can't update them" in log and "Make them writable" in log, log[-600:]
    assert "The rate events couldn't be applied: GameUserSettings.ini is read-only." in log
    assert "Couldn't write the admin list (AllowedCheaterAccountIDs.txt): AllowedCheaterAccountIDs.txt is read-only" in log
    assert am.ini_get(am.read_text_file(gus), "ServerSettings", "TamingSpeedMultiplier") == "1"
    # Troubleshoot
    finding = next(f for f in am.diagnose_server(app.mgr, s) if "read-only" in f["title"])
    assert finding["severity"] == "warning" and len(finding["evidence"]) == 3 and "Make them writable" in finding["fix"]
    # copying game settings onto it is skipped, with the reason
    msg = app.mgr.copy_game_settings_to(srv("Bravo"), s)
    assert msg.startswith("Game settings skipped: GameUserSettings.ini and Game.ini are read-only on Alpha"), msg
    # the admin list says what to do
    app._admin_add_by_id(); root.update()
    assert "AllowedCheaterAccountIDs.txt is read-only" in errs[-1] and "Make them writable" in errs[-1], errs[-1]
    # saving the Game tab asks; No leaves everything as it was
    app._load_ini(); root.update()
    asks.clear(); app._save_ini(); root.update()
    assert "GameUserSettings.ini and Game.ini are read-only" in asks[-1] and not writable(gus)
    # Yes makes them writable and saves, with ordinary .bak copies
    answer[0] = True; app._save_ini(); root.update()
    assert writable(gus) and writable(gini) and writable(gus + ".bak") and "Saved" in infos[-1], infos[-1:]
    # the button fixes the rest (the admin list)
    assert app.ro_row.winfo_manager() and app.ro_lbl.cget("text").startswith("AllowedCheaterAccountIDs.txt is read-only")
    app._make_writable(); root.update()
    assert writable(am.admin_file(s)) and not app.ro_row.winfo_manager()
    assert not any("read-only" in f["title"] for f in am.diagnose_server(app.mgr, s))
    print("read-only: warning line + button, save asks, start logs, rate events/admins/copy explain, "
          "Troubleshoot finding, ordinary .bak copies")
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")

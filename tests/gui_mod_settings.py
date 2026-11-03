"""Game settings > Mod settings: lists only the mod sections of GameUserSettings.ini (with a best-guess mod name),
edits/adds/removes settings and sections, leaves untouched sections byte for byte, stays in step with the raw
editor and Common settings, and Save writes the file."""
import os, sys
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
from tkinter import ttk

GUS_TEXT = ("[ServerSettings]\nXPMultiplier=2.0\nServerAdminPassword=adm\n\n"
            "[StructuresPlus]\n; tweak S+ here\nDisableHitchingPost=True\nPullRange=3000\n\n"
            "[AwesomeSpyglass]\nAllowedTags=Dino\nAllowedTags=Player\n\n"
            "[/Script/Engine.GameSession]\nMaxPlayers=70\n\n"
            "[SessionSettings]\nSessionName=Test\n")
cfg = am.AppConfig(); cfg.data["theme"] = "dark"
s0 = cfg.servers[0]; s0["mods"] = "731604991,1609138312"
cfg.data["mod_cache"] = {"731604991": {"id": "731604991", "name": "Structures Plus (S+)", "updated": ""},
                         "1609138312": {"id": "1609138312", "name": "Awesome Spyglass!", "updated": ""}}
cfg.save()
cdir = os.path.join(s0["install_dir"], am.CONFIG_REL); os.makedirs(cdir, exist_ok=True)
open(os.path.join(cdir, am.GUS), "w").write(GUS_TEXT)
am.Manager.ensure_steamcmd = lambda self, s: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
asked, shown = [], []
am.messagebox.askyesno = lambda t, m, **k: asked.append(m) or True
am.messagebox.showinfo = lambda t, m, **k: shown.append(m)
am.messagebox.showerror = lambda t, m, **k: shown.append("ERROR " + m)
answers = []
am.simpledialog.askstring = lambda *a, **k: answers.pop(0)
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())


def raw():
    return app.ini_texts[am.GUS].get("1.0", "end-1c")


def press(text):
    frame = app.ini_nb.nametowidget(app.ini_nb.tabs()[1])
    stack = [frame]
    while stack:
        w = stack.pop(); stack.extend(w.winfo_children())
        if isinstance(w, ttk.Button) and w.cget("text") == text:
            w.invoke(); root.update(); return
    raise AssertionError(f"no {text!r} button")


def secs():
    return [(app.ms_secs.item(i, "text"), app.ms_secs.item(i, "values")[0]) for i in app.ms_secs.get_children()]


def keys():
    return [(app.ms_keys.item(i, "text"), str(app.ms_keys.item(i, "values")[0])) for i in app.ms_keys.get_children()]


def a():
    app.nb.select(app.nb.tabs()[2]); app.ini_nb.select(1); root.update()   # Game settings > Mod settings
    assert app.ini_nb.tab(1, "text") == "Mod settings"
    assert secs() == [("StructuresPlus", "Structures Plus (S+)"), ("AwesomeSpyglass", "Awesome Spyglass!")], secs()
    assert keys() == [("DisableHitchingPost", "True"), ("PullRange", "3000")], keys()
    # edit a value
    app.ms_keys.selection_set("0"); root.update()
    assert app.ms_key.get() == "DisableHitchingPost"
    app.ms_val.set("False"); press("Set")
    # add a setting, then remove one
    app.ms_key.set("MaxWalls"); app.ms_val.set("500"); press("Add setting")
    app.ms_keys.selection_set("1"); root.update(); press("Remove setting")
    assert keys() == [("DisableHitchingPost", "False"), ("MaxWalls", "500")], keys()
    # a bad setting name is refused
    app.ms_key.set("bad=name"); press("Add setting")
    assert shown and "no = or" in shown[-1], shown
    # repeated keys stay in order in the second section
    app.ms_secs.selection_set("1"); root.update()
    assert keys() == [("AllowedTags", "Dino"), ("AllowedTags", "Player")], keys()
    # add a section for a mod with no settings yet; ARK's own and duplicates are refused
    answers[:] = ["ServerSettings"]; press("Add section...")
    assert "ARK's own" in shown[-1]
    answers[:] = ["structuresplus"]; press("Add section...")
    assert "already" in shown[-1]
    answers[:] = ["[DinoStorage]"]; press("Add section...")
    app.ms_key.set("Enabled"); app.ms_val.set("True"); press("Add setting")
    app.ini_nb.select(2); root.update()                  # to the raw editor: changes written into the text
    t = raw()
    assert "[StructuresPlus]\n; tweak S+ here\nDisableHitchingPost=False\nMaxWalls=500\n\n[AwesomeSpyglass]" in t, t
    assert "[AwesomeSpyglass]\nAllowedTags=Dino\nAllowedTags=Player\n\n[/Script/Engine.GameSession]\nMaxPlayers=70\n" in t
    assert t.startswith("[ServerSettings]\nXPMultiplier=2.0\nServerAdminPassword=adm\n\n") and t.endswith("[DinoStorage]\nEnabled=True\n"), t
    assert "PullRange" not in t
    # edits in the raw editor show up in Mod settings, and Common settings agrees
    t = t.replace("AllowedTags=Player", "AllowedTags=Structure")
    app.ini_texts[am.GUS].delete("1.0", "end"); app.ini_texts[am.GUS].insert("1.0", t)
    app.ini_nb.select(1); root.update(); app.ms_secs.selection_set("1"); root.update()
    assert keys()[1] == ("AllowedTags", "Structure"), keys()
    app.ini_nb.select(0); root.update()
    assert app.common_vars[(am.GUS, am.SS, "XPMultiplier")].get() == "2.0"
    # remove a section, then save from the Mod settings tab
    app.ini_nb.select(1); root.update(); app.ms_secs.selection_set("1"); root.update()
    press("Remove section")
    assert asked and "Remove the [AwesomeSpyglass] section" in asked[-1]
    app._save_ini(); root.update()
    on_disk = open(os.path.join(cdir, am.GUS)).read()
    assert "[AwesomeSpyglass]" not in on_disk and "MaxWalls=500" in on_disk and "[DinoStorage]" in on_disk, on_disk
    assert "\n\n\n" not in on_disk, "no double gaps left where a section was"
    assert os.path.isfile(os.path.join(cdir, am.GUS + ".bak")), "a .bak copy first"
    print("Mod settings: lists, edits, adds, removes, keeps the rest, stays in step, saves")
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")

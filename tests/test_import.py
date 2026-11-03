"""Importing a server Tamer didn't make: from a launch line, a .bat file, and the folder (INI + saves)."""
import os, sys, tempfile
sys.path.insert(0, sys.argv[1]); import tamer as am

tmp = tempfile.mkdtemp()


def make_server(root, gus="", saves=()):
    exe = os.path.join(root, am.SERVER_EXE_REL)
    os.makedirs(os.path.dirname(exe), exist_ok=True); open(exe, "w").close()
    os.makedirs(os.path.join(root, am.CONFIG_REL), exist_ok=True)
    open(os.path.join(root, am.CONFIG_REL, "GameUserSettings.ini"), "w").write(gus)
    for m in saves:
        os.makedirs(os.path.join(root, am.SAVEDARKS_REL, m), exist_ok=True)
        open(os.path.join(root, am.SAVEDARKS_REL, m, m + ".ark"), "w").write("x")
    return exe


cfg = am.AppConfig(os.path.join(tmp, "c.json"))
root = os.path.join(tmp, "My ARK")
exe = make_server(root, saves=["Ragnarok_WP"])

# ---------- a full launch line ----------
line = (f'"{exe}" "TheIsland_WP?listen?SessionName=My Cool Server?Port=7787?QueryPort=27015?RCONPort=27030?'
        'RCONEnabled=True?MaxPlayers=40?ServerPassword=join?AllowFlyerCarryPvE=True?ServerAdminPassword=adm" '
        '-port=7787 -WinLiveMaxPlayers=40 -mods=111,222 -passivemods=333 -clusterid=abc '
        '-ClusterDirOverride="D:\\cluster dir" -NoBattlEye -servergamelog -ForceAllowCaveFlyers -SomeUnknown '
        '-culture=de -CustomThing="a b" -ActiveEvent=Summer')
s, found, notes = am.import_server(cfg, cmdline=line)
want = {"name": "My Cool Server", "session_name": "My Cool Server", "map": "TheIsland_WP", "port": 7787, "rcon_port": 27030,
        "max_players": 40, "server_password": "join", "admin_password": "adm", "mods": "111,222,333",
        "passive_mods": "333", "battleye": False, "cluster": True, "culture": "de", "active_event": "Summer",
        "extra_options": "AllowFlyerCarryPvE=True", "install_dir": root, "asaapi": False}
assert {k: s[k] for k in want} == want, {k: (s[k], want[k]) for k in want if s[k] != want[k]}
assert s["cmd_flags"] == ["-servergamelog", "-ForceAllowCaveFlyers"], s["cmd_flags"]
assert s["extra_args"] == '-SomeUnknown -CustomThing="a b"', s["extra_args"]
assert found["cluster_id"] == "abc" and found["cluster_dir"] == "D:\\cluster dir", found
assert not any("No map" in n or "Map taken" in n for n in notes), "the launch line's map wins over the saves"
print("launch line: everything picked up")

# ---------- quoting the way Windows reads it (CommandLineToArgvW rules) ----------
assert am.split_cmdline(r'a "b c" d\"e "f\\" g\\\"h "" i""j "k ""l"" m"') == \
    ["a", "b c", 'd"e', "f\\", 'g\\"h', "", "ij", 'k "l" m'], am.split_cmdline(r'a "b c" d\"e "f\\" g\\\"h "" i""j "k ""l"" m"')
# values wrapped in escaped quotes, as some launchers write them - this left \JAG...\ and \TheIsland_WP\ behind
esc = (f'"{exe}" "\\"TheIsland_WP\\"?listen?SessionName=\\"JAG(Just A Game) The Island\\"?Port=7777?RCONPort=27020?'
       'ServerAdminPassword=\\"pw word\\"" -mods=1,2 -ClusterDirOverride="D:\\My Cluster" -clusterid=jag -culture="en"')
q, qf, _ = am.import_server(cfg, cmdline=esc)
assert (q["map"], q["session_name"], q["name"], q["admin_password"], q["port"], q["mods"], q["culture"]) == \
    ("TheIsland_WP", "JAG(Just A Game) The Island", "JAG(Just A Game) The Island", "pw word", 7777, "1,2", "en"), q
assert qf["cluster_dir"] == "D:\\My Cluster" and "\\" not in q["session_name"] + q["map"], qf
q, _f, _n = am.import_server(cfg, cmdline=f'"{exe}" TheIsland_WP?listen?SessionName="Quoted Plain"?Port=7778 -NoBattlEye')
assert q["session_name"] == "Quoted Plain" and q["map"] == "TheIsland_WP" and q["port"] == 7778, q
q, _f, _n = am.import_server(cfg, cmdline=f'"{exe}" "TheIsland_WP?listen?SessionName=He said \\"hi\\"!"')
assert q["session_name"] == 'He said "hi"!', q["session_name"]  # quotes inside a name are kept
print("escaped quotes: no stray backslashes, names with brackets and spaces kept")

# ---------- round trip: Tamer's own launch line for the import says the same things ----------
m = am.Manager(cfg, lambda *a: None)
again, _f, _n = am.import_server(am.AppConfig(os.path.join(tmp, "c2.json")), cmdline=m.to_cmdline(m.build_command(s)))
for k in ("session_name", "map", "port", "rcon_port", "max_players", "server_password", "admin_password",
          "passive_mods", "battleye", "culture", "active_event", "extra_options"):
    assert again[k] == s[k], (k, again[k], s[k])
again["id"], again["install_dir"] = s["id"], s["install_dir"]
assert m.build_command(again) == m.build_command(s), "Tamer would start the re-imported server exactly the same way"
print("round trip ok")

# ---------- a .bat file: set, %~dp0, cd, start, ^ ----------
bat = os.path.join(root, "Start Server.bat")
open(bat, "w").write('@echo off\r\nREM my server\r\nset MAP=Ragnarok_WP\r\nset "NAME=Bat Server"\r\n'
                     'cd /d "%~dp0ShooterGame\\Binaries\\Win64"\r\n'
                     'start "" ArkAscendedServer.exe "%MAP%?listen?SessionName=%NAME%?Port=7790?RCONPort=27040?'
                     'ServerAdminPassword=x" ^\r\n -mods=5 -NoBattlEye\r\n')
s, found, notes = am.import_server(cfg, bat=bat)
assert (s["map"], s["session_name"], s["port"], s["rcon_port"], s["mods"], s["battleye"], s["install_dir"]) == \
    ("Ragnarok_WP", "Bat Server", 7790, 27040, "5", False, root), s
assert os.path.normcase(found["exe"]) == os.path.normcase(exe)
print(".bat file: set, %~dp0, cd, start and ^ handled")
open(os.path.join(tmp, "nothing.bat"), "w").write("@echo off\r\necho hi\r\n")
try:
    am.import_server(cfg, bat=os.path.join(tmp, "nothing.bat")); raise AssertionError("must refuse")
except RuntimeError as e:
    assert "doesn't start ArkAscendedServer" in str(e)

# ---------- AsaApiLoader in the launch line ----------
s, found, _ = am.import_server(cfg, cmdline=f'"{os.path.join(os.path.dirname(exe), "AsaApiLoader.exe")}" TheIsland_WP?listen')
assert s["asaapi"] and s["install_dir"] == root
print("AsaApiLoader launch line: AsaApi on")

# ---------- just the folder: INI + saves ----------
gus = ("[ServerSettings]\nRCONPort=27050\nServerAdminPassword=iniadmin\nServerPassword=inijoin\nActiveMods=77,88\n"
       "[SessionSettings]\nSessionName=From The INI\nPort=7795\n[/Script/Engine.GameSession]\nMaxPlayers=25\n")
make_server(root, gus=gus)
s, found, notes = am.import_server(cfg, folder=os.path.join(root, "ShooterGame"))  # a folder inside it works too
assert (s["session_name"], s["port"], s["rcon_port"], s["admin_password"], s["server_password"], s["max_players"],
        s["mods"], s["map"], s["install_dir"]) == ("From The INI", 7795, 27050, "iniadmin", "inijoin", 25, "77,88",
                                                   "Ragnarok_WP", root), s
assert any("Map taken from the saves" in n for n in notes) and any("folder only" in n for n in notes), notes
print("folder: INI values and the map from the saves")

# ---------- refusals and warnings ----------
try:
    am.import_server(cfg, folder=tmp); raise AssertionError("must refuse a folder with no server")
except RuntimeError as e:
    assert "Couldn't find the server files" in str(e)
cfg.servers[0]["install_dir"] = root
try:
    am.import_server(cfg, folder=root); raise AssertionError("must refuse a folder Tamer already manages")
except RuntimeError as e:
    assert "already manages" in str(e)
cfg.servers[0]["install_dir"] = os.path.join(tmp, "elsewhere"); cfg.servers[0]["port"] = 7795
_s, _f, notes = am.import_server(cfg, folder=root)
assert any("clash" in n for n in notes), notes
print("refusals and warnings ok")
print("ALL OK")

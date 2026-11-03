import os, sys, socket, struct, threading, tempfile, zipfile, datetime as dt, time
sys.path.insert(0, sys.argv[1])
import tamer as am

# ---- INI helpers
t = "[ServerSettings]\nXPMultiplier=2\nFoo=1\n\n[SessionSettings]\nSessionName=x\n"
assert am.ini_get(t, "serversettings", "xpmultiplier") == "2"
t2 = am.ini_set(t, "ServerSettings", "XPMultiplier", "3")
assert am.ini_get(t2, "ServerSettings", "XPMultiplier") == "3" and "SessionName=x" in t2
t3 = am.ini_set(t2, "ServerSettings", "TamingSpeedMultiplier", "5")
lines = t3.splitlines()
assert lines.index("TamingSpeedMultiplier=5") < lines.index("[SessionSettings]"), t3
t4 = am.ini_set(t3, "ServerSettings", "Foo", None)
assert "Foo=" not in t4
t5 = am.ini_set("", "/script/shootergame.shootergamemode", "EggHatchSpeedMultiplier", "10")
assert t5 == "[/script/shootergame.shootergamemode]\nEggHatchSpeedMultiplier=10\n", repr(t5)
# Game.ini duplicates preserved for other keys
g = "[/script/shootergame.shootergamemode]\nOverrideEngramEntries=(a)\nOverrideEngramEntries=(b)\n"
g2 = am.ini_set(g, "/script/shootergame.shootergamemode", "bAllowUnlimitedRespecs", "True")
assert g2.count("OverrideEngramEntries") == 2
print("ini ok")

# ---- schedule helpers
assert am.parse_times("04:00, 16:30") == [(4, 0), (16, 30)]
try:
    am.parse_times("25:00"); raise SystemExit("bad")
except ValueError:
    pass
now = dt.datetime(2026, 11, 2, 17, 0)
assert am.next_occurrence([(4, 0), (16, 30)], now) == dt.datetime(2026, 11, 3, 4, 0)
assert am.parse_minutes("1,15, 5") == [15, 5, 1]
print("schedule ok")

# ---- fake RCON server
PW = "secret"
def pkt(i, t, body):
    p = struct.pack("<ii", i, t) + body.encode() + b"\0\0"
    return struct.pack("<i", len(p)) + p
def serve(sock):
    while True:
        c, _ = sock.accept()
        def h(c=c):
            authed = False
            try:
                while True:
                    hdr = c.recv(4)
                    if not hdr: return
                    n = struct.unpack("<i", hdr)[0]
                    d = b""
                    while len(d) < n: d += c.recv(n - len(d))
                    i, t = struct.unpack("<ii", d[:8]); body = d[8:-2].decode()
                    if t == 3:
                        c.sendall(pkt(i if body == PW else -1, 2, ""))
                        authed = body == PW
                    elif t == 2 and authed:
                        if body == "ListPlayers":
                            out = "0. Bob Smith, 0002abcdef1234567890abcdef123456\n1. Alice, 00029999\n"
                        elif body == "GetChat":
                            out = "Bob Smith (Bob): hello\n"
                        else:
                            out = "Server received, But no response!! \n"
                        c.sendall(pkt(i, 0, out))
            except OSError:
                pass
        threading.Thread(target=h, daemon=True).start()
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(); port = srv.getsockname()[1]
threading.Thread(target=serve, args=(srv,), daemon=True).start()
rc = am.RconClient("127.0.0.1", port, PW)
players = am.parse_players(rc.command("ListPlayers"))
assert players == [("0", "Bob Smith", "0002abcdef1234567890abcdef123456"), ("1", "Alice", "00029999")], players
assert "no response" in rc.command("SaveWorld")
rc.sock.close()  # simulate dropped connection -> auto reconnect
assert "Alice" in rc.command("ListPlayers")
try:
    am.RconClient("127.0.0.1", port, "wrong").command("ListPlayers"); raise SystemExit("auth should fail")
except am.RconAuthError:
    pass
print("rcon ok")

# ---- manager: command line, poll, backups, restore
tmp = tempfile.mkdtemp()
cfg = am.AppConfig(os.path.join(tmp, "cfg.json"))
cfg.data["cluster_dir"] = os.path.join(tmp, "my cluster")
s = cfg.servers[0]
s.update(install_dir=os.path.join(tmp, "srv"), session_name="My Cool Server", mods="928988,931874",
         cluster=True, rcon_port=port, admin_password=PW, extra_args='-ForceAllowCaveFlyers -Foo="a b"')
events = []
m = am.Manager(cfg, lambda k, sid=None, p=None: events.append((k, p)))
args = m.build_command(s)
cl = m.to_cmdline(args)
print(cl)
assert args[1].endswith(f"ServerAdminPassword={PW}")
assert f'-ClusterDirOverride="{cfg.data["cluster_dir"]}"' in cl
assert '"TheIsland_WP?listen?SessionName=My Cool Server?' in cl
assert '-Foo="a b"' in cl and "-mods=928988,931874" in cl and "-NoBattlEye" in cl
saved_extra = s["extra_args"]
s["extra_args"] = r'''-Path="C:\Ark Data\x" -Win=C:\Ark\y -Name=Bob's -Open="c d'''
extra = m.build_command(s)[-4:]
assert extra == [r"-Path=C:\Ark Data\x", r"-Win=C:\Ark\y", "-Name=Bob's", "-Open=c d"], extra
s["extra_args"] = saved_extra
assert "********" in m.to_cmdline(m.build_command(s, mask=True)) and PW not in m.to_cmdline(m.build_command(s, mask=True))

rt = m.runtime(s["id"]); rt.polling = True
m._poll(s)
assert rt.online and len(rt.players) == 2 and any("[chat] Bob Smith" in l for l in rt.console), rt.console

arks = os.path.join(s["install_dir"], am.SAVEDARKS_REL, "TheIsland_WP")
os.makedirs(arks)
open(os.path.join(arks, "TheIsland_WP.ark"), "w").write("WORLD1")
open(os.path.join(arks, "TheIsland_WP_02.11.2026_04.00.00.ark"), "w").write("ROLLING")
open(os.path.join(arks, "123.arkprofile"), "w").write("P")
os.makedirs(m.config_dir(s))
open(os.path.join(m.config_dir(s), "Game.ini"), "w").write("[x]\na=1\n")
os.makedirs(cfg.data["cluster_dir"]); open(os.path.join(cfg.data["cluster_dir"], "eos1"), "w").write("C")
rt.online = False
s["backup_keep"] = 2
for i in range(3):
    m._backup(s, f"t{i}"); time.sleep(1.1)
bks = m.list_backups(s)
assert len(bks) == 2, bks
names = zipfile.ZipFile(bks[0]).namelist()
print(names)
assert any(n.endswith("TheIsland_WP.ark") for n in names) and not any("04.00.00" in n for n in names)
assert any(n.startswith("Cluster") for n in names) and any(n.endswith("Game.ini") for n in names)
open(os.path.join(arks, "TheIsland_WP.ark"), "w").write("WORLD2")
open(os.path.join(m.config_dir(s), "Game.ini"), "w").write("changed")
m._restore(s, bks[0], True)
assert open(os.path.join(arks, "TheIsland_WP.ark")).read() == "WORLD1"
assert open(os.path.join(m.config_dir(s), "Game.ini")).read() == "[x]\na=1\n"
assert any("before_restore" in d for d in os.listdir(os.path.dirname(os.path.dirname(arks))))
print("backup/restore ok")

# tick on a not-installed server must not crash
m.first_tick = True
cfg.data["update_check_min"] = 0
m._tick()
assert rt.state == "Not installed", rt.state
print("tick ok")
print("ALL OK")

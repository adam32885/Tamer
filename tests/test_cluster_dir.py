"""The cluster data folder: an imported \\"C:\\...\\" path (or a broken one already saved, such as
\\C:\\Users\\Administrator\\Documents\\New ArkData\\) is cleaned, a saved broken value is repaired when Tamer opens
(and logged), the launch line never lets a path's last backslash eat its closing quote, and a folder that can't
work is caught at start and by Troubleshoot. Real case: transfers between maps weren't being saved."""
import json, os, sys, tempfile
sys.path.insert(0, sys.argv[1]); import tamer as am

BROKEN = "\\C:\\Users\\Administrator\\Documents\\New ArkData\\"
GOOD = "C:\\Users\\Administrator\\Documents\\New ArkData"
assert am.clean_path(BROKEN) == GOOD
assert am.clean_path('\\"C:\\Users\\Administrator\\Documents\\New ArkData\\"') == GOOD
assert am.clean_path('"C:\\ARK Data\\"') == "C:\\ARK Data"
assert am.clean_path("  C:\\ARK Data//  ") == "C:\\ARK Data"
assert am.clean_path("C:\\") == "C:\\" and am.clean_path(GOOD) == GOOD
assert am.clean_path("\\\\nas\\share\\cluster\\") == "\\\\nas\\share\\cluster"  # network paths keep their \\

# importing a launch line that uses \" as its quotes throughout (read the way ARK does): this is how the
# broken value above was made, with the backslashes kept
line = ('"C:\\ASA\\Island\\ShooterGame\\Binaries\\Win64\\ArkAscendedServer.exe" '
        '\\"TheIsland_WP?listen?SessionName=JAG(Just A Game) The Island?Port=7777\\" '
        '-clusterid=abc -ClusterDirOverride=\\"C:\\Users\\Administrator\\Documents\\New ArkData\\"')
settings, found = am.parse_server_cmdline(line)
assert settings["session_name"] == "JAG(Just A Game) The Island", settings
assert found["cluster_dir"] == GOOD, found

# the launch line: a value ending in \ keeps its closing quote, and Windows reads it back the same
cmd = am.Manager.to_cmdline(["C:\\a.exe", "TheIsland_WP?listen", "-ClusterDirOverride=C:\\ARK Data\\"])
assert cmd.endswith('-ClusterDirOverride="C:\\ARK Data\\\\"'), cmd
assert am.split_cmdline(cmd)[-1] == "-ClusterDirOverride=C:\\ARK Data\\", am.split_cmdline(cmd)

# a broken value already saved is repaired when Tamer opens, and the log says so
work = tempfile.mkdtemp(prefix="tamer_cdir_")
path = os.path.join(work, "config.json")
srv = am.default_server(1, []); srv.update(name="Island", cluster=True, install_dir=os.path.join(work, "Island"))
with open(path, "w", encoding="utf-8") as f:
    json.dump({"cluster_dir": BROKEN, "cluster_id": "abc", "servers": [srv]}, f)
cfg = am.AppConfig(path)
assert cfg.data["cluster_dir"] == GOOD and cfg.cluster_dir_fixed == (BROKEN, GOOD)
assert json.load(open(path, encoding="utf-8"))["cluster_dir"] == GOOD, "the repair is saved"
mgr = am.Manager(cfg, lambda *a: None)
log = "\n".join(mgr.runtime(cfg.servers[0]["id"]).log)
assert "Fixed the cluster data folder setting" in log and "wasn't saving transfers between maps" in log, log
assert am.AppConfig(path).__dict__.get("cluster_dir_fixed") is None  # only once
# the launch command uses the cleaned folder even if a broken one sneaks in
cfg.data["cluster_dir"] = BROKEN
assert f"-ClusterDirOverride={GOOD}" in mgr.build_command(cfg.servers[0])

# a folder that can't work: caught at start and by Troubleshoot
ok_dir = os.path.join(work, "cluster ok")
assert am.cluster_dir_problem(ok_dir) == "" and os.path.isdir(ok_dir)
assert am.cluster_dir_problem("") and am.cluster_dir_problem('C:\\a"b')
if am.IS_WINDOWS:
    assert am.cluster_dir_problem("relative\\folder") and am.cluster_dir_problem("C:\\a\\C:\\b")
bad = "C:\\a\\C:\\b" if am.IS_WINDOWS else 'bad"dir'
s = cfg.servers[0]
exe = os.path.join(s["install_dir"], am.SERVER_EXE_REL); os.makedirs(os.path.dirname(exe)); open(exe, "w").close()
cfg.data["cluster_dir"] = bad
mgr.clean = None
assert any(f["title"] == "The cluster data folder can't work" for f in am.diagnose_server(mgr, s))
alerts = []
mgr.alert = lambda srv, event, title, desc="", color="info": alerts.append((event, title))
mgr.ports_in_use_by_other = lambda x: None
mgr.build_command = lambda x: (_ for _ in ()).throw(RuntimeError("stop here"))
try:
    mgr._start(s)
except RuntimeError:
    pass
log = "\n".join(mgr.runtime(s["id"]).log)
assert "Transfers between maps won't be saved" in log and ("diagnose", "Cluster folder problem") in alerts, log[-400:]
cfg.data["cluster_dir"] = ok_dir
assert not any("cluster data folder" in f["title"] for f in am.diagnose_server(mgr, s))
mgr.stop_event.set()
print("cluster folder: cleaned on import, repaired on open (logged), launch line keeps its quotes, "
      "bad folders caught at start and by Troubleshoot")

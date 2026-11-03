import json, os, shutil, sys, tempfile, time
sys.path.insert(0, sys.argv[1]); os.environ["FAKE_ARK_LOG"] = __import__("os").path.join(__import__("tempfile").gettempdir(), "fk_cmd.log")
import tamer as am, fakes
tmp = tempfile.mkdtemp()
# old profile without the new keys still gets the game log flag
p = os.path.join(tmp, "c.json"); json.dump({"servers": [{"id": "abc123", "name": "Old"}]}, open(p, "w"))
cfg = am.AppConfig(p); s = cfg.servers[0]
assert s["cmd_flags"] == ["-servergamelog"]
m = am.Manager(cfg, lambda *a: None)
cl = m.to_cmdline(m.build_command(s)); assert " -servergamelog" in cl
s.update(server_platform="ALL", culture="de", public_ip="93.184.216.34", multihome="192.168.1.34",
         cmd_flags=["-servergamelog", "-exclusivejoin", "-NoWildBabies", "-ForceAllowCaveFlyers"],
         extra_args="-ForceAllowCaveFlyers -Foo")
args = m.build_command(s); cl = m.to_cmdline(args); print(cl)
for part in ("-ServerPlatform=ALL", "-culture=de", "-PublicIPForEpic=93.184.216.34", "-MultiHome", "?MultiHome=192.168.1.34",
             "-exclusivejoin", "-NoWildBabies", "-Foo"):
    assert part in cl, part
assert cl.count("ForceAllowCaveFlyers") == 1, "no duplicate when also typed in Extra -arguments"
assert cl.index("?MultiHome=") < cl.index("ServerAdminPassword"), "admin password stays last"
s["multihome_rcon"] = True; m.rcon.__func__  # rcon host switches to the MultiHome address
try: m.rcon(s, "x")
except Exception: pass
assert m.runtime(s["id"]).rcon_key[0] == "192.168.1.34"
s["multihome_rcon"] = False
print("command ok")
# CPU priority + cores on a real process
s.update(install_dir=os.path.join(tmp, "srv"), rcon_port=29701, port=28101, extra_args="", cpu_priority="Below normal", cpu_cores=[0])
exe = os.path.join(s["install_dir"], am.SERVER_EXE_REL); os.makedirs(os.path.dirname(exe)); fakes.install_server(exe)
m._start(s); pid = m.runtime(s["id"]).pid; time.sleep(1)
below, cores = fakes.cpu_settings(pid); print("below normal", below, "cores", cores)
assert below and cores == {0}
s.update(cpu_priority="Normal", cpu_cores=[]); m.apply_cpu(s, force=True)
below, cores = fakes.cpu_settings(pid); assert not below and len(cores) == min(os.cpu_count() or 1, 64)
print(am.describe_cores([0, 1, 2, 5]), "|", am.describe_cores([]))
m._stop(s, graceful=False); print("cpu ok"); print("ALL OK")

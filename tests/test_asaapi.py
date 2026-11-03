import json, os, shutil, signal, sys, tempfile, threading, time, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import fakes
sys.path.insert(0, sys.argv[1]); os.environ["FAKE_ARK_LOG"] = __import__("os").path.join(__import__("tempfile").gettempdir(), "fk_api.log")
tmp = tempfile.mkdtemp()
def mkzip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for n, data in files.items(): z.writestr(n, data)
    return path
release = mkzip(os.path.join(tmp, "AsaApi_1.21.zip"), {
    "AsaApi_1.21/AsaApiLoader.exe": fakes.loader_bytes(), "AsaApi_1.21/ArkApi/AsaApi.dll": "api",
    "AsaApi_1.21/config.json": '{"settings": {"new": 1}}', "AsaApi_1.21/ArkApi/Plugins/Permissions/Permissions.dll": "perm",
    "AsaApi_1.21/ArkApi/Plugins/Permissions/config.json": '{"default": 1}', "AsaApi_1.21/msdia140.dll": "x"})
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/latest":
            b = json.dumps({"tag_name": "1.21", "assets": [{"name": "AsaApi_1.21_pdb.zip", "browser_download_url": "x"},
                     {"name": "AsaApi_1.21.zip", "browser_download_url": f"http://127.0.0.1:{h.server_address[1]}/dl"}]}).encode()
        else:
            b = open(release, "rb").read()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
h = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=h.serve_forever, daemon=True).start()
os.environ["ASM_ASAAPI_API"] = f"http://127.0.0.1:{h.server_address[1]}/latest"
import tamer as am
tag, url, name = am.asaapi_latest(); assert (tag, name) == ("1.21", "AsaApi_1.21.zip"), (tag, name)

cfg = am.AppConfig(os.path.join(tmp, "c.json")); cfg.data.update(update_check_min=0, mod_check_min=0)
s = cfg.servers[0]; s.update(install_dir=os.path.join(tmp, "srv"), rcon_port=29801, port=28201, backup_interval_min=0)
p = am.asaapi_paths(s)
exe = os.path.join(s["install_dir"], am.SERVER_EXE_REL); os.makedirs(os.path.dirname(exe))
fakes.install_server(exe)
assert am.asaapi_status(s)["installed"] is False
# ---- install, user edits, reinstall keeps them, remove keeps plugins
am.asaapi_install_zip(s, release, "1.21")
st = am.asaapi_status(s); assert st["installed"] and st["version"] == "1.21", st
assert os.path.isfile(p["dll"]) and os.path.isfile(os.path.join(p["plugins"], "Permissions", "Permissions.dll"))
open(p["config"], "w").write("MY SETTINGS"); open(os.path.join(p["plugins"], "Permissions", "config.json"), "w").write("MY PERMS")
am.asaapi_install_zip(s, release, "1.22")
assert open(p["config"]).read() == "MY SETTINGS" and os.path.isfile(p["config"] + ".default")
assert open(os.path.join(p["plugins"], "Permissions", "config.json")).read() == "MY PERMS"
assert am.asaapi_status(s)["version"] == "1.22"
am.asaapi_remove(s)
assert not am.asaapi_status(s)["installed"] and os.path.isfile(p["config"]) and os.path.isdir(os.path.join(p["plugins"], "Permissions"))
am.asaapi_install_zip(s, release, "1.21")
print("asaapi install/update/remove ok")
# ---- plugins: folder layout, loose layout, update keeps config, enable/disable
shop = mkzip(os.path.join(tmp, "Shop.zip"), {"ArkShop/ArkShop.dll": "s", "ArkShop/config.json": '{"a":1}',
                                              "ArkShop/PluginInfo.json": '{"FullName":"Ark Shop","Version":1.5,"Description":"Points shop"}'})
loose = mkzip(os.path.join(tmp, "DiscordBridge.zip"), {"DiscordBridge.dll": "d", "libcurl.dll": "c", "config.json": "{}"})
assert am.install_plugin_zip(s, shop) == ["ArkShop"] and am.install_plugin_zip(s, loose) == ["DiscordBridge"]
open(os.path.join(p["plugins"], "ArkShop", "config.json"), "w").write("EDITED")
am.install_plugin_zip(s, shop)
assert open(os.path.join(p["plugins"], "ArkShop", "config.json")).read() == "EDITED"
assert os.path.isfile(os.path.join(p["plugins"], "DiscordBridge", "libcurl.dll"))
am.set_plugin_enabled(s, "DiscordBridge", False)
pl = {x["name"]: x for x in am.list_plugins(s)}; print({k: (v["full_name"], v["version"], v["enabled"]) for k, v in pl.items()})
assert pl["ArkShop"]["full_name"] == "Ark Shop" and pl["ArkShop"]["version"] == 1.5 and not pl["DiscordBridge"]["enabled"]
am.install_plugin_zip(s, loose)  # updating a disabled plugin updates it in place
assert not os.path.isdir(os.path.join(p["plugins"], "DiscordBridge"))
am.set_plugin_enabled(s, "DiscordBridge", True)
print("plugins ok")
# ---- launch through the loader
m = am.Manager(cfg, lambda *a: None); rt = m.runtime(s["id"])
s.update(asaapi=True, cpu_priority="Below normal")
m.start_monitor(); m.run_op(s, "Start", m.op_start)
end = time.time() + 40
while time.time() < end and not (rt.online and rt.stats_pid): time.sleep(0.5)
print("loader pid", rt.pid, "server pid", rt.stats_pid, "online", rt.online)
assert rt.online and rt.stats_pid and rt.stats_pid != rt.pid
assert fakes.cpu_settings(rt.stats_pid)[0], "CPU settings go to the real server, not the loader"
assert any("Starting with AsaApi" in l and "AsaApiLoader.exe" in l for l in rt.log)
end = time.time() + 30
while time.time() < end and not (rt.ram and rt.ram > 50 * 1024 ** 2): time.sleep(0.5)  # the fake grows after 8s
assert rt.ram and rt.ram > 50 * 1024 ** 2, f"monitoring tracks the real server ({rt.ram}, stats pid {rt.stats_pid})\n" + "\n".join(rt.log)
loader = rt.pid
fakes.crash(rt.stats_pid)  # server crashes -> loader exits -> crash restart
end = time.time() + 40
while time.time() < end and not (rt.online and rt.pid != loader): time.sleep(0.5)
assert rt.online and rt.pid != loader and any("exited unexpectedly" in l for l in rt.log)
m.run_op(s, "Stop", m.op_stop, []); end = time.time() + 30
while time.time() < end and (m.is_running(s) or rt.busy): time.sleep(0.5)
assert not m.is_running(s); print("loader launch ok")
# ---- troubleshooter
os.makedirs(p["logs"], exist_ok=True)
open(os.path.join(p["logs"], "ArkApi_1234.log"), "w").write("[info] ok\n[error] Failed to load plugin ArkShop - requires newer API version!\n")
f = am.diagnose_server(m, s); t = [x for x in f if x["title"] == "AsaApi logged errors"]
assert t and "ArkShop" in t[0]["evidence"][0], [x["title"] for x in f]
am.asaapi_remove(s); f = am.diagnose_server(m, s)
assert any(x["title"] == "AsaApi is switched on but isn't installed" for x in f)
m.stop_event.set(); print("ALL OK")

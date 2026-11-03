import sys, os; sys.path.insert(0, sys.argv[1]); os.environ.pop("ASM_CF_BASE", None)
import tamer as am
urls = []
def fake(req, timeout=0):
    urls.append((req.full_url, req.get_header("X-api-key"))); raise am.urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
am.urllib.request.urlopen = fake
for key in ("", "MYKEY"):
    try: am.CurseForge(lambda k=key: k).search("dino")
    except RuntimeError as e: print(e, "\n")
for u in urls: print(u)
assert urls[0][0].startswith("https://api.curse.tools/v1/cf/mods/search?") and urls[0][1] is None
assert urls[1][0].startswith("https://api.curseforge.com/v1/mods/search?") and urls[1][1] == "MYKEY"
print("urls ok")

"""Set day/night = Auto (colour by day, B&W at night) and IR LEDs off; print before/after."""
import json, ssl, sys, urllib.request
C = "https://192.168.12.120/cgi-bin/api.cgi"; PW = sys.argv[1]
ctx = ssl._create_unverified_context(); ctx.set_ciphers("DEFAULT:@SECLEVEL=0"); ctx.minimum_version = ssl.TLSVersion.TLSv1
def api(cmd, param, tok=None, action=0):
    url = f"{C}?cmd={cmd}" + (f"&token={tok}" if tok else "")
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, json.dumps([{"cmd": cmd, "action": action, "param": param}]).encode()), context=ctx, timeout=15).read())[0]
tok = api("Login", {"User": {"Version": "0", "userName": "admin", "password": PW}})["value"]["Token"]["name"]
isp = api("GetIsp", {"channel": 0}, tok)["value"]["Isp"]; print("before:", isp["dayNight"], isp["dayNightThreshold"], isp["exposure"])
isp["dayNight"] = sys.argv[2] if len(sys.argv) > 2 else "Auto"
print("SetIsp:", api("SetIsp", {"Isp": isp}, tok)["code"], "SetIrLights:", api("SetIrLights", {"IrLights": {"channel": 0, "state": "Off"}}, tok)["code"])
isp = api("GetIsp", {"channel": 0}, tok)["value"]["Isp"]; ir = api("GetIrLights", {"channel": 0}, tok)["value"]["IrLights"]["state"]
print("after:", isp["dayNight"], "threshold", isp["dayNightThreshold"], "IR", ir); api("Logout", {}, tok)

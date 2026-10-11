"""Try day/night, IR and exposure modes on the Reolink; per mode: snapshot + frame rate + brightness/noise. Restores at the end."""
import json, ssl, subprocess, sys, time, urllib.request
import numpy as np, cv2
C = "https://192.168.12.120/cgi-bin/api.cgi"; OUT = sys.argv[1]; PW = sys.argv[2]
ctx = ssl._create_unverified_context()
ctx.set_ciphers("DEFAULT:@SECLEVEL=0"); ctx.minimum_version = ssl.TLSVersion.TLSv1   # camera firmware only speaks old TLS
def api(cmd, param, tok=None, action=0):
    url = f"{C}?cmd={cmd}" + (f"&token={tok}" if tok else "")
    body = json.dumps([{"cmd": cmd, "action": action, "param": param}]).encode()
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, body), context=ctx, timeout=15).read())[0]
tok = api("Login", {"User": {"Version": "0", "userName": "admin", "password": PW}})["value"]["Token"]["name"]
isp0 = api("GetIsp", {"channel": 0}, tok)["value"]["Isp"]; ir0 = api("GetIrLights", {"channel": 0}, tok)["value"]["IrLights"]["state"]
def setmode(dn, ir, exp, gmax=None):
    isp = dict(isp0); isp.update(dayNight=dn, exposure=exp)
    if gmax: isp["gain"] = {"min": 1, "max": gmax}
    r1 = api("SetIsp", {"Isp": isp}, tok)["code"]; r2 = api("SetIrLights", {"IrLights": {"channel": 0, "state": ir}}, tok)["code"]
    return r1, r2
def measure(tag):
    time.sleep(8)  # IR-cut filter + exposure settle
    jpg = urllib.request.urlopen("http://127.0.0.1:8097/api/frame.jpeg?src=main", timeout=20).read()
    open(f"{OUT}/night_{tag}.jpg", "wb").write(jpg)
    img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_GRAYSCALE).astype(np.float32)
    sky = img[200:700, 200:1000]; ground = img[1000:1700, 200:2400]
    noise = float(np.median(np.abs(sky - cv2.GaussianBlur(sky, (0, 0), 3))))
    p = subprocess.run(["ffprobe", "-v", "error", "-rtsp_transport", "tcp", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
                        "-of", "csv=p=0", "-read_intervals", "%+6", "rtsp://127.0.0.1:8557/main"], capture_output=True, text=True, timeout=40)
    ts = [float(x) for x in p.stdout.split() if x.strip() and x.strip() != "N/A"]
    fps = (len(ts) - 1) / (ts[-1] - ts[0]) if len(ts) > 2 else 0
    print(f"{tag:22s} fps {fps:5.1f}  sky mean {sky.mean():5.1f}  ground mean {ground.mean():5.1f}  sky noise {noise:4.2f}", flush=True)
import os
MODES = {"A_color_irOff_auto": ("Color", "Off", "Auto", None), "B_bw_irOff_auto": ("Black&White", "Off", "Auto", None),
         "C_bw_irOn_auto": ("Black&White", "Auto", "Auto", None), "D_bw_irOff_antismear": ("Black&White", "Off", "Anti-Smearing", None),
         "E_bw_irOff_gain100": ("Black&White", "Off", "Auto", 100), "F_bw_irOff_lownoise_g100": ("Black&White", "Off", "LowNoise", 100)}
modes = [(t, *MODES[t][:3]) for t in (sys.argv[3].split(",") if len(sys.argv) > 3 else list(MODES)[:4])]
try:
    for tag, dn, ir, exp in modes:
        print(tag, "set:", setmode(dn, ir, exp, MODES[tag][3]), flush=True); measure(tag)
finally:
    api("SetIsp", {"Isp": isp0}, tok); api("SetIrLights", {"IrLights": {"channel": 0, "state": ir0}}, tok)
    print("restored:", isp0["dayNight"], isp0["exposure"], "IR", ir0)
    api("Logout", {}, tok)

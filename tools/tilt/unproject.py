"""Pixel (full-res frame) -> true az/el through the page's camera model (sky.js Camera.unproject), and the
geometric elevation of a target (curvature + standard refraction k = 0.13).
Usage: unproject.py <objects.json> <rotator az> x,y [x,y ...]  |  ... --target lat,lon,h_asl"""
import json, math, sys
import numpy as np
cam = json.load(open(sys.argv[1]))["camera"]; st = json.load(open(sys.argv[1]))["station"]
W, H = cam["width"], cam["height"]; F = cam["f_px"] * W / cam["f_ref_w"]
PP = [v * W / cam["f_ref_w"] for v in cam.get("pp_px", [0, 0])]; CX, CY = W / 2 + PP[0], H / 2 + PP[1]
A0, E0 = math.degrees(math.atan(-PP[0] / F)), math.degrees(math.atan(PP[1] / F))
K1, K2, T = cam.get("k1", 0), cam.get("k2", 0), cam.get("tilt")
def tilt(az, t=T):
    if not t: return 0.0
    d = lambda a: t["A"] * math.sin(math.radians(a)) + t["B"] * math.cos(math.radians(a))
    return d(az) - d(t.get("ref_az", 121.95))
def unproject(x, y, yaw, t=T):
    p, tt, r = math.radians(yaw - A0), math.radians(cam["pitch"] - E0), math.radians(cam["roll"])
    fwd = np.array([math.sin(p) * math.cos(tt), math.cos(p) * math.cos(tt), math.sin(tt)])
    r0 = np.array([math.cos(p), -math.sin(p), 0.0]); u0 = np.cross(r0, fwd)
    right = r0 * math.cos(r) + u0 * math.sin(r); up = u0 * math.cos(r) - r0 * math.sin(r)
    xd, yd = (x - CX) / F, -(y - CY) / F; rd = math.hypot(xd, yd); ru = rd
    for _ in range(12): ru -= (ru * (1 + K1 * ru * ru + K2 * ru ** 4) - rd) / (1 + 3 * K1 * ru * ru + 5 * K2 * ru ** 4)
    s = ru / rd if rd > 1e-9 else 1
    d = fwd + xd * s * right + yd * s * up; d /= np.linalg.norm(d)
    az = math.degrees(math.atan2(d[0], d[1])) % 360
    return az, math.degrees(math.asin(d[2])) - tilt(az, t), math.degrees(math.asin(d[2]))
def target(lat, lon, h):
    R = 6371000.0; la1, lo1, la2, lo2 = map(math.radians, (st["lat"], st["lon"], lat, lon))
    dist = 2 * R * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
    az = math.degrees(math.atan2(math.sin(lo2 - lo1) * math.cos(la2), math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1))) % 360
    el = math.degrees(math.atan2(h - st["h"] - dist ** 2 / (2 * R) * (1 - 0.13), dist))
    return az, dist, el
yaw = float(sys.argv[2]) + cam.get("az_offset", 0)
args = sys.argv[3:]
if "--target" in args:
    i = args.index("--target"); lat, lon, h = map(float, args[i + 1].split(",")); args = args[:i] + args[i + 2:]
    az, dist, el = target(lat, lon, h); print(f"target: az {az:.2f}  dist {dist:.0f} m  geometric el {el:.3f}  (tilt model there {tilt(az):+.2f})")
for a in args:
    x, y = map(float, a.split(","))
    az, el, raw = unproject(x, y, yaw)
    print(f"px {x:.1f},{y:.1f}: az {az:.2f}  el {el:.3f} (model incl. tilt)  el without tilt {raw:.3f}")

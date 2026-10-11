"""Record N s from the restream, find (blinking) lights near a predicted az/el, report az/el + on-fraction.
Usage: blink_measure.py <rotator_az> <pred_az> <pred_el> <outdir> [secs]"""
import json, math, subprocess, sys
import cv2, numpy as np
rot, paz, pel, out = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
secs = float(sys.argv[5]) if len(sys.argv) > 5 else 15
cam = json.load(open("/www/objects.json"))["camera"]
W, H = 2560, 1920; f, k1, k2 = cam["f_px"], cam["k1"], cam["k2"]; ppx, ppy = cam["pp_px"]
cx, cy = W / 2 + ppx, H / 2 + ppy
a0 = math.degrees(math.atan(-ppx / f)); e0 = math.degrees(math.atan(ppy / f))
def axes(yaw):
    p, t, r = math.radians(yaw - a0), math.radians(cam["pitch"] - e0), math.radians(cam["roll"])
    fwd = np.array([math.sin(p) * math.cos(t), math.cos(p) * math.cos(t), math.sin(t)])
    right0 = np.array([math.cos(p), -math.sin(p), 0]); up0 = np.cross(right0, fwd)
    return fwd, right0 * math.cos(r) + up0 * math.sin(r), up0 * math.cos(r) - right0 * math.sin(r)
fwd, right, up = axes(rot + cam["az_offset"])
def proj(az, el):
    a, e = math.radians(az), math.radians(el); d = np.array([math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)])
    Z = d @ fwd; X = d @ right / Z; Y = d @ up / Z; s = 1 + k1 * (X*X + Y*Y) + k2 * (X*X + Y*Y) ** 2
    return cx + f * X * s, cy - f * Y * s
def unproj(x, y):
    xd, yd = (x - cx) / f, -(y - cy) / f; rd = math.hypot(xd, yd); ru = rd
    for _ in range(20): ru -= (ru * (1 + k1 * ru**2 + k2 * ru**4) - rd) / (1 + 3 * k1 * ru**2 + 5 * k2 * ru**4)
    sc = ru / rd if rd > 1e-9 else 1; d = fwd + xd * sc * right + yd * sc * up; d /= np.linalg.norm(d)
    return math.degrees(math.atan2(d[0], d[1])) % 360, math.degrees(math.asin(d[2]))
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-rtsp_transport", "tcp", "-i", "rtsp://127.0.0.1:8557/main", "-t", str(secs),
                "-vf", "fps=10", "-q:v", "2", f"{out}/f_%03d.jpg"], check=True)
import glob
files = sorted(glob.glob(f"{out}/f_*.jpg"))
px, py = proj(paz, pel); R = 260
x0, y0 = int(px) - R, int(py) - R
stack = np.stack([cv2.imread(p, cv2.IMREAD_GRAYSCALE)[y0:y0 + 2 * R, x0:x0 + 2 * R] for p in files]).astype(np.float32)
mx, med = stack.max(0), np.median(stack, 0)
cv2.imwrite(f"{out}/max.png", cv2.resize(mx.astype(np.uint8), None, fx=2, fy=2))
cv2.imwrite(f"{out}/median.png", cv2.resize(med.astype(np.uint8), None, fx=2, fy=2))
print(f"{len(files)} frames; predicted at ({px:.0f},{py:.0f})")
blur = cv2.GaussianBlur(mx, (0, 0), 1.5)
cand = []
m = blur.copy()
for _ in range(12):
    _, v, _, (lx, ly) = cv2.minMaxLoc(m)
    if v < 120: break
    ts = stack[:, ly, lx]; on = (ts > (v + np.median(ts)) / 2).mean()
    az, el = unproj(lx + x0, ly + y0)
    cand.append((lx + x0, ly + y0, v, float(np.median(ts)), on, az, el))
    cv2.circle(m, (lx, ly), 12, 0, -1)
print(" x     y    peak  median  on%    az       el      d_az   d_el   (vs predicted)")
for x, y, v, md, on, az, el in cand:
    print(f"{x:5d} {y:5d} {v:5.0f} {md:6.0f} {on*100:5.0f}  {az:7.2f} {el:7.3f}  {az - paz:+6.2f} {el - pel:+6.3f}")

"""Find the Sky Tower light in each rotated frame, compare with old (rectilinear) and new (distortion) model."""
import glob, json, math, re, sys
import cv2, numpy as np
D = sys.argv[1]; dist = json.load(open(f"{D}/distortion.json"))
AZ, EL = 121.95, 1.75
def proj(yaw, f, k1, k2, pitch, roll, W=2560, H=1920):
    p, t, r = math.radians(yaw), math.radians(pitch), math.radians(roll)
    fwd = np.array([math.sin(p) * math.cos(t), math.cos(p) * math.cos(t), math.sin(t)])
    right0 = np.array([math.cos(p), -math.sin(p), 0]); up0 = np.cross(right0, fwd)
    right = right0 * math.cos(r) + up0 * math.sin(r); up = up0 * math.cos(r) - right0 * math.sin(r)
    a, e = math.radians(AZ), math.radians(EL); d = np.array([math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)])
    Z = d @ fwd; X = d @ right / Z; Y = d @ up / Z; s = 1 + k1 * (X*X + Y*Y) + k2 * (X*X + Y*Y)**2
    return W / 2 + f * X * s, H / 2 - f * Y * s
models = {"old (hfov 65.7, pitch -1.28, roll 0)": (1982, 0, 0, -1.28, 0.0),
          "new, pitch -1.28 roll 0": (dist["f"], dist["k1"], dist["k2"], -1.28, 0.0),
          "new, pitch -1.28 roll fit": (dist["f"], dist["k1"], dist["k2"], -1.28, dist["roll"]),
          "new, all fitted": (dist["f"], dist["k1"], dist["k2"], dist["pitch"], dist["roll"])}
res = {m: [] for m in models}
for path in sorted(glob.glob(f"{D}/az*_1.jpg"), key=lambda p: int(re.search(r"az(\d+)_", p).group(1))):
    yaw = float(re.search(r"az(\d+)_", path).group(1))
    if yaw == 122: yaw = 122.0   # CCW approach for this one
    g = cv2.imread(path, cv2.IMREAD_GRAYSCALE).astype(np.float32)
    x0, y0 = proj(yaw, *models["new, pitch -1.28 roll fit"])
    xa, ya = int(x0) - 90, int(y0) - 90
    win = cv2.GaussianBlur(g[ya:ya + 160, xa:xa + 180], (0, 0), 2)
    _, mx, _, loc = cv2.minMaxLoc(win); lx, ly = loc[0] + xa, loc[1] + ya
    cv2.imwrite(f"{D}/st_{int(yaw)}.png", cv2.resize(g[ya:ya + 160, xa:xa + 180].astype(np.uint8), None, fx=3, fy=3))
    line = f"rotator {yaw:5.1f}  light found at ({lx:4d},{ly:4d}) peak {mx:.0f} | "
    for m, P in models.items():
        x, y = proj(yaw, *P); res[m].append((x - lx, y - ly)); line += f" {x - lx:+5.0f},{y - ly:+4.0f}"
    print(line)
print("\nmodel error (px at 2560 wide; 34.6 px = 1 deg):")
for m, v in res.items():
    v = np.array(v); print(f"  {m:40s} x err {' '.join(f'{a:+5.0f}' for a in v[:, 0])}   y err {' '.join(f'{a:+4.0f}' for a in v[:, 1])}")

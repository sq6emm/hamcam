"""Mast/rotation-axis tilt from roof edges: frames rotNNN.jpg (NNN = rotator az), LiDAR DSM (GUGiK NMPT 2024),
OSM building outlines. For rays whose highest point is a building roof, find the vertical offset between the
predicted roof edge (current camera model, objects.json) and the image edge, per 6-deg sector of world azimuth.
Fit  delta(az) = c + A sin(az) + B cos(az)   (delta = observed - predicted elevation, deg).
Usage: tilt_calib.py <frames dir> <out dir>"""
import glob, json, math, os, re, sys
import cv2, numpy as np
from pyproj import Transformer
FR, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True)
z = np.load("/g/nmpt2024/mosaic_1m.npz"); dsm, e_min, n_max = z["dsm"], float(z["e_min"]), float(z["n_max"])
dsm = np.where(np.isnan(dsm), np.nanmin(dsm), dsm).astype(np.float32)
dsm = cv2.morphologyEx(dsm, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))          # drop poles / wires
_st = json.load(open("/www/objects.json"))["station"]          # antenna location: same config as the page
E0, N0 = Transformer.from_crs(4326, 2180, always_xy=True).transform(_st["lon"], _st["lat"]); HS = _st["h"]
# building mask (1 m grid, same as DSM), dilated 1 m so roof edges are included
cache = "/g/building_mask.npy"
if os.path.exists(cache): bmask = np.load(cache)
else:
    tr = Transformer.from_crs(4326, 2180, always_xy=True)
    bmask = np.zeros(dsm.shape, np.uint8)
    for w in json.load(open("/g/osm_buildings.json"))["elements"]:
        g = w.get("geometry")
        if not g or len(g) < 3: continue
        x, y = tr.transform([p["lon"] for p in g], [p["lat"] for p in g])
        pts = np.array([[(xx - e_min), (n_max - yy)] for xx, yy in zip(x, y)], np.int32)
        cv2.fillPoly(bmask, [pts], 1)
    bmask = cv2.dilate(bmask, np.ones((3, 3), np.uint8)); np.save(cache, bmask)
cam = json.load(open("/www/objects.json"))["camera"]
W, H = 2560, 1920; f, k1, k2 = cam["f_px"], cam["k1"], cam["k2"]; ppx, ppy = cam["pp_px"]
cx, cy = W / 2 + ppx, H / 2 + ppy; a0 = math.degrees(math.atan(-ppx / f)); e0 = math.degrees(math.atan(ppy / f))
def axes(yaw):
    p, t, r = math.radians(yaw - a0), math.radians(cam["pitch"] - e0), math.radians(cam["roll"])
    fwd = np.array([math.sin(p) * math.cos(t), math.cos(p) * math.cos(t), math.sin(t)])
    right0 = np.array([math.cos(p), -math.sin(p), 0]); up0 = np.cross(right0, fwd)
    return fwd, right0 * math.cos(r) + up0 * math.sin(r), up0 * math.cos(r) - right0 * math.sin(r)
def proj(ax, az, el):
    fwd, right, up = ax; a, e = np.radians(az), np.radians(el)
    d = np.stack([np.sin(a) * np.cos(e), np.cos(a) * np.cos(e), np.sin(e)], -1)
    Z = d @ fwd; X = d @ right / Z; Y = d @ up / Z; r2 = X * X + Y * Y; s = 1 + k1 * r2 + k2 * r2 * r2
    return cx + f * X * s, cy - f * Y * s
# expected skyline over the full circle (0.1 deg), keep only roof-edge rays
D = np.arange(60.0, 4100.0, 0.5)
AZ = np.arange(0, 360, 0.1); EXP = np.full(len(AZ), np.nan); DIST = np.full(len(AZ), np.nan)
for i, az in enumerate(AZ):
    e = E0 + D * math.sin(math.radians(az)); n = N0 + D * math.cos(math.radians(az))
    c = (e - e_min).astype(int); r = (n_max - n).astype(int)
    ok = (r >= 0) & (r < dsm.shape[0]) & (c >= 0) & (c < dsm.shape[1])
    if not ok.any(): continue
    el = np.full(len(D), -90.0); el[ok] = np.degrees(np.arctan2(dsm[r[ok], c[ok]] - HS, D[ok]))
    j = int(np.argmax(el))
    if bmask[r[j], c[j]] and D[j] > 150:
        # roof must stand clear: the ray just above it should hit nothing within 0.15 deg further out
        EXP[i] = el[j]; DIST[i] = D[j]
print(f"roof-edge rays: {np.isfinite(EXP).sum()} of {len(AZ)}", flush=True)
rows = []
for path in sorted(glob.glob(f"{FR}/rot*.jpg")):
    rot = float(re.search(r"rot(\d+)", path).group(1)); ax = axes(rot + cam["az_offset"])
    img = cv2.imread(path); g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 1.0)
    edge = np.zeros_like(g); edge[1:-1] = np.clip(g[:-2] - g[2:], 0, None)          # brighter above (sky) than below (roof)
    rel = ((AZ - rot + 540) % 360) - 180; sel = np.isfinite(EXP) & (np.abs(rel) < 33)
    azs, els = AZ[sel], EXP[sel]
    if len(azs) < 30: continue
    def score(az_, el_):
        x, y = proj(ax, az_, el_); xi, yi = np.round(x).astype(int), np.round(y).astype(int)
        ok = (xi > 2) & (xi < W - 3) & (yi > 2) & (yi < H - 3)
        v = np.zeros(len(az_)); v[ok] = np.maximum.reduce([edge[yi[ok] + d, xi[ok]] for d in (-1, 0, 1)])
        return v
    # 1) frame-wide azimuth/elevation offset (rotator scatter), coarse
    best = max(((score(azs + da, els + de).mean(), da, de) for da in np.arange(-1.0, 1.01, 0.1) for de in np.arange(-3, 3.01, 0.05)))
    da = best[1]
    # 2) per 6-deg sector: elevation offset
    vis = img.copy()
    for s0 in np.arange(math.floor((rot - 33) / 6) * 6, rot + 33, 6):
        m = (((azs - s0) % 360) < 6)
        if m.sum() < 15: continue
        sc = [(score(azs[m] + da, els[m] + de).mean(), de) for de in np.arange(-3, 3.001, 0.02)]
        v = np.array([s for s, _ in sc]); k = int(np.argmax(v)); conf = v[k] / (np.median(v) + 1e-6)
        de = sc[k][1]
        rows.append({"rot": rot, "az": float((s0 + 3) % 360), "delta": float(de), "daz": float(da), "conf": float(conf), "n": int(m.sum()),
                     "dist": float(np.median(DIST[sel][m]))})
        x, y = proj(ax, azs[m] + da, els[m]); cv2.polylines(vis, [np.stack([x, y], -1).astype(np.int32)], False, (0, 0, 255), 2)
        x, y = proj(ax, azs[m] + da, els[m] + de); cv2.polylines(vis, [np.stack([x, y], -1).astype(np.int32)], False, (0, 255, 0), 2)
    cv2.imwrite(f"{OUT}/vis_{int(rot):03d}.jpg", cv2.resize(vis, (1280, 960)))
    print(f"rot {rot:5.1f}: frame daz {da:+.1f}, sectors {sum(1 for r in rows if r['rot'] == rot)}", flush=True)
json.dump(rows, open(f"{OUT}/sectors.json", "w"), indent=1)
R = np.array([[r["az"], r["delta"], r["conf"]] for r in rows if r["conf"] > 1.6])
print(f"\n{len(rows)} sector measurements, {len(R)} confident")
if len(R) >= 6:
    X = np.stack([np.ones(len(R)), np.sin(np.radians(R[:, 0])), np.cos(np.radians(R[:, 0]))], -1); w = R[:, 2]
    keep = np.ones(len(R), bool)
    for _ in range(3):
        coef = np.linalg.lstsq(X[keep] * w[keep, None], R[keep, 1] * w[keep], rcond=None)[0]
        res = R[:, 1] - X @ coef; mad = np.median(np.abs(res[keep])) * 1.4826 + 0.02; keep = np.abs(res) < 3 * mad
    c, A, B = coef; T = math.hypot(A, B); phi = math.degrees(math.atan2(A, B)) % 360
    ref = c + A * math.sin(math.radians(121.95)) + B * math.cos(math.radians(121.95))
    print(f"fit: c {c:+.2f}  tilt amplitude {T:.2f} deg, objects appear highest toward az {phi:.0f} (lowest {(phi + 180) % 360:.0f})")
    print(f"delta at Sky Tower (122): {ref:+.2f} deg   residual rms {np.sqrt(np.mean(res[keep] ** 2)):.2f} deg over {keep.sum()} sectors")
    json.dump({"c": c, "A": A, "B": B, "T": T, "phi": phi, "ref122": ref, "rms": float(np.sqrt(np.mean(res[keep] ** 2))), "n": int(keep.sum())},
              open(f"{OUT}/tilt_fit.json", "w"), indent=1)
    for az in range(0, 360, 30):
        print(f"  az {az:3d}: delta {c + A * math.sin(math.radians(az)) + B * math.cos(math.radians(az)):+.2f}")

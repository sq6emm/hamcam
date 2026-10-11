"""Absolute antenna/camera elevation error from the terrain: observed skyline vs. skyline predicted from the
GUGiK NMPT (LiDAR surface model incl. trees and buildings).

1. Mosaic the NMPT sheets (ARC/INFO ASCII, PL-1992, EVRF2007) at 1 m (max-pooled so tree tops survive).
2. Expected skyline: for each azimuth, max elevation angle of the surface along the ray from the antenna
   (25 m .. 2400 m), corrected for earth curvature and standard refraction.
3. Observed: the panorama (built with an assumed camera pitch). Per 10 deg sector, find the vertical shift
   (+ small azimuth shift) that best aligns the expected skyline with sky->ground edges in the image.
   shift = observed - expected elevation  ->  true pitch error there = -shift.
Usage: skyline.py <nmpt-dir> <analysis-dir (panorama.jpg, analysis.json)> <objects.json>
"""
import glob, json, math, os, sys
import cv2
import numpy as np

NM, AN, OBJ = sys.argv[1], sys.argv[2], sys.argv[3]
R, K = 6371000.0, 0.13
st = json.load(open(OBJ))["station"]
H_ANT = st["h"]
# station in PL-1992 (EPSG:2180): easting, northing (computed earlier with pyproj)
E0, N0 = 356022.8, 364023.7

# ---------- 1. NMPT mosaic ----------
cache = f"{NM}/mosaic_1m.npz"
if os.path.exists(cache):
    z = np.load(cache); dsm, e_min, n_max = z["dsm"], float(z["e_min"]), float(z["n_max"])
else:
    sheets = []
    for p in sorted(glob.glob(f"{NM}/*.asc")):
        hdr = {}
        with open(p) as fp:
            for _ in range(6):
                k, v = fp.readline().split(); hdr[k.lower()] = float(v)
        cs_ = hdr["cellsize"]
        if "xllcorner" not in hdr:  # GUGiK sheets give cell centres
            hdr["xllcorner"] = hdr["xllcenter"] - cs_ / 2; hdr["yllcorner"] = hdr["yllcenter"] - cs_ / 2
        sheets.append((p, hdr))
    xs = [h["xllcorner"] for _, h in sheets]; ys = [h["yllcorner"] for _, h in sheets]
    cs = sheets[0][1]["cellsize"]
    print("header example:", sheets[0][1])
    e_min = min(xs); n_min = min(ys)
    e_max = max(h["xllcorner"] + h["ncols"] * h["cellsize"] for _, h in sheets)
    n_max = max(h["yllcorner"] + h["nrows"] * h["cellsize"] for _, h in sheets)
    W, Hh = int(round(e_max - e_min)), int(round(n_max - n_min))
    dsm = np.full((Hh, W), np.nan, np.float32)
    for p, h in sheets:
        with open(p) as fp:
            for _ in range(6): fp.readline()
            a = np.array(fp.read().split(), dtype=np.float32).reshape(int(h["nrows"]), int(h["ncols"]))
        a[a == h.get("nodata_value", -9999)] = np.nan
        f = int(round(1.0 / h["cellsize"]))
        if f > 1:  # max-pool to 1 m
            r, c = (a.shape[0] // f) * f, (a.shape[1] // f) * f
            a = np.nanmax(a[:r, :c].reshape(r // f, f, c // f, f), axis=(1, 3))
        c0 = int(round(h["xllcorner"] - e_min)); r0 = int(round(n_max - (h["yllcorner"] + h["nrows"] * h["cellsize"])))
        dsm[r0:r0 + a.shape[0], c0:c0 + a.shape[1]] = np.fmax(dsm[r0:r0 + a.shape[0], c0:c0 + a.shape[1]], a)
        print("loaded", os.path.basename(p), a.shape)
    np.savez_compressed(cache, dsm=dsm, e_min=e_min, n_max=n_max)
print(f"DSM mosaic {dsm.shape}, E {e_min:.0f}.., N ..{n_max:.0f}; ground at antenna {dsm[int(n_max - N0), int(E0 - e_min)]:.1f} m")

# remove objects narrower than ~3 m (poles, wires, single thin treetops): invisible at a distance, but they would
# otherwise win the "highest point along the ray"
OPEN_M = int(os.environ.get("OPEN_M", "3"))
if OPEN_M > 1:
    filled = np.where(np.isnan(dsm), np.nanmin(dsm), dsm).astype(np.float32)
    dsm = cv2.morphologyEx(filled, cv2.MORPH_OPEN, np.ones((OPEN_M, OPEN_M), np.uint8))

# ---------- 2. expected skyline ----------
AZ = np.arange(0, 360, 0.2)
D = np.arange(25.0, 2400.0, 1.0)
curv = np.degrees(D / (2 * R) * (1 - K))
exp_el = np.full(len(AZ), np.nan); exp_d = np.full(len(AZ), np.nan)
for i, a in enumerate(AZ):
    e = E0 + D * math.sin(math.radians(a)); n = N0 + D * math.cos(math.radians(a))
    c = (e - e_min).astype(int); r = (n_max - n).astype(int)
    ok = (r >= 0) & (r < dsm.shape[0]) & (c >= 0) & (c < dsm.shape[1])
    h = np.full(len(D), np.nan); h[ok] = dsm[r[ok], c[ok]]
    el = np.degrees(np.arctan2(h - H_ANT, D)) - curv
    if np.all(np.isnan(el)):
        continue
    j = int(np.nanargmax(el)); exp_el[i] = el[j]; exp_d[i] = D[j]

# ---------- 3. match against the panorama ----------
A = json.load(open(f"{AN}/analysis.json")); P = A["pano"]
img = cv2.imread(f"{AN}/{P['file']}")
g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
g = cv2.GaussianBlur(g, (0, 0), 1.2)
# sky -> ground edge: brightness drops going down (positive when the pixel above is brighter)
edge = np.zeros_like(g); edge[1:-1] = g[:-2] - g[2:]
edge = np.clip(edge, 0, None)
valid = (img.sum(-1) > 90)  # not the empty background
ppd = P["ppd"]
def col_of(az):
    a = az
    while a < P["a0"]: a += 360
    while a > P["a1"]: a -= 360
    return (a - P["a0"]) * ppd
def row_of(el):
    return (P["e1"] - el) * ppd

sectors = []
for s0 in range(0, 360, 10):
    idx = np.nonzero((AZ >= s0) & (AZ < s0 + 10) & ~np.isnan(exp_el))[0]
    if len(idx) < 20:
        continue
    cols = np.array([col_of(AZ[i]) for i in idx]); rows0 = np.array([row_of(exp_el[i]) for i in idx])
    if cols.min() < 0 or cols.max() >= img.shape[1]:
        continue
    best = None
    for daz in np.arange(-1.5, 1.51, 0.1):
        cc = np.round(cols + daz * ppd).astype(int)
        if cc.min() < 0 or cc.max() >= img.shape[1] or not valid[img.shape[0] // 2, cc].mean() > 0.8:
            continue
        for dl in np.arange(-1.5, 1.501, 0.02):
            rr = np.round(rows0 - dl * ppd).astype(int)
            if rr.min() < 1 or rr.max() >= img.shape[0] - 1:
                continue
            if valid[rr, cc].mean() < 0.9:
                continue
            sc = edge[rr, cc].mean()
            if best is None or sc > best[0]:
                best = (sc, dl, daz)
    if best is None:
        continue
    # contrast of the match vs. the median over shifts = confidence
    sectors.append({"az": s0 + 5, "shift_deg": round(best[1], 3), "daz": round(best[2], 2), "score": round(float(best[0]), 2),
                    "exp_el": round(float(np.nanmean(exp_el[idx])), 3), "exp_dist_m": round(float(np.nanmedian(exp_d[idx])), 0)})

# fit: shift(az) = s0 + A sin az + B cos az  (shift = observed - expected); weight by score
S = np.array([[x["az"], x["shift_deg"], x["score"]] for x in sectors])
w = S[:, 2] / S[:, 2].max()
X = np.vstack([np.ones(len(S)), np.sin(np.radians(S[:, 0])), np.cos(np.radians(S[:, 0]))]).T
coef = np.linalg.lstsq(X * w[:, None], S[:, 1] * w, rcond=None)[0]
res = S[:, 1] - X @ coef
# robust refit without outliers (> 2.5 MAD)
mad = np.median(np.abs(res - np.median(res))) * 1.4826 + 1e-6
keep = np.abs(res) < 2.5 * mad
coef2 = np.linalg.lstsq((X * w[:, None])[keep], (S[:, 1] * w)[keep], rcond=None)[0]
s_mean, Aa, Bb = coef2
amp = math.hypot(Aa, Bb); ph = math.degrees(math.atan2(Aa, Bb)) % 360
model_pitch = A.get("pitch", -1.3)
out = {
    "antenna_h": H_ANT, "model_pitch": model_pitch,
    "sectors": sectors, "kept": [bool(k) for k in keep],
    "fit": {"shift_mean": s_mean, "amp": amp, "shift_max_az": ph,
            # true pitch = model pitch - shift  -> mean pitch, and where the antenna points highest (shift minimal)
            "pitch_mean": model_pitch - s_mean, "tilt": amp, "highest_az": (ph + 180) % 360, "lowest_az": ph,
            "rms_resid": float(np.sqrt(np.mean(res[keep] ** 2))), "n": int(keep.sum())},
    "expected": {"az": AZ[::5].round(1).tolist(), "el": np.round(exp_el[::5], 3).tolist(), "dist": np.round(exp_d[::5], 0).tolist()},
}
json.dump(out, open(f"{AN}/skyline.json", "w"), indent=1)
print("sector  exp_el  dist   shift   daz  score")
for x, k in zip(sectors, keep):
    print(f"{x['az']:5.0f}  {x['exp_el']:+6.2f}  {x['exp_dist_m']:5.0f}  {x['shift_deg']:+6.2f}  {x['daz']:+5.1f}  {x['score']:5.1f} {'' if k else ' (outlier)'}")
f = out["fit"]
print(f"\nmean camera/antenna pitch (true): {f['pitch_mean']:+.2f} deg   (model assumed {model_pitch})")
print(f"tilt amplitude: {f['tilt']:.2f} deg, antenna highest toward {f['highest_az']:.0f} deg, lowest toward {f['lowest_az']:.0f}")
print(f"residual rms {f['rms_resid']:.2f} deg over {f['n']} sectors")

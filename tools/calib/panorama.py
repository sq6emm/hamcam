"""Build an azimuth/elevation panorama from recorder snapshots + analysis JSON for the web page.

Each snapshot is projected through the pinhole model (f = 1983 px @2560, pitch, roll) at the azimuth the
rotator had when the frame was captured: az(mtime - lag) from the recorder's az logs. lag and roll are
chosen by minimising disagreement between overlapping snapshots.
Usage: panorama.py <tilt-dir> <out-dir> <objects.json>
"""
import csv, glob, json, math, os, re, sys
import cv2
import numpy as np

D, OUT, OBJ = sys.argv[1], sys.argv[2], sys.argv[3]
F_FULL, W_FULL, H_FULL = 1983.0, 2560, 1920
PITCH = -1.3

# ---- rotator log (all events) ----
az_rows = []
for f in sorted(glob.glob(f"{D}/event*_az.csv")):
    az_rows += [(float(t), float(a)) for t, a in list(csv.reader(open(f)))[1:]]
az_rows.sort()
TA = np.array([r[0] for r in az_rows]); AA = np.degrees(np.unwrap(np.radians([r[1] for r in az_rows])))

def az_at(t):
    return float(np.interp(t, TA, AA)) % 360

# ---- snapshots ----
snaps = []
for p in sorted(glob.glob(f"{D}/snaps/*.jpg")):
    m = re.search(r"_(start|move|stop)_az([\d.]+)\.jpg$", p)
    t = os.stat(p).st_mtime
    if not m or t < TA[0] - 30 or t > TA[-1] + 30:
        continue
    img = cv2.imread(p)
    if img is None:
        continue
    snaps.append({"path": p, "t": t, "kind": m.group(1), "img": img})
print(f"{len(snaps)} snapshots")

def render(lag, roll, ppd, a0, a1, e0=-24.0, e1=22.0, keep=False, sharp=2):
    Wp, Hp = int((a1 - a0) * ppd), int((e1 - e0) * ppd)
    az_deg = a0 + (np.arange(Wp) + 0.5) / ppd
    el = np.radians(e1 - (np.arange(Hp) + 0.5) / ppd)
    acc = np.zeros((Hp, Wp, 3), np.float32); acc2 = np.zeros((Hp, Wp), np.float32); wsum = np.zeros((Hp, Wp), np.float32)
    scale = 1.0 if keep else 0.25
    f = F_FULL * scale; cx, cy = W_FULL * scale / 2, H_FULL * scale / 2
    t_, r_ = math.radians(PITCH), math.radians(roll)
    for s in snaps:
        yawd = az_at(s["t"] - lag)
        rel = (az_deg - yawd + 540) % 360 - 180
        cols = np.nonzero(np.abs(rel) < 42)[0]
        if not len(cols):
            continue
        c0, c1 = cols.min(), cols.max() + 1
        AZ, EL = np.meshgrid(np.radians(az_deg[c0:c1]), el)
        d = np.stack([np.sin(AZ) * np.cos(EL), np.cos(AZ) * np.cos(EL), np.sin(EL)], -1).astype(np.float32)
        yaw = math.radians(yawd)
        fwd = np.array([math.sin(yaw) * math.cos(t_), math.cos(yaw) * math.cos(t_), math.sin(t_)], np.float32)
        right0 = np.array([math.cos(yaw), -math.sin(yaw), 0.0], np.float32); up0 = np.cross(right0, fwd)
        right = right0 * math.cos(r_) + up0 * math.sin(r_); up = up0 * math.cos(r_) - right0 * math.sin(r_)
        Z = d @ fwd; X = d @ right; Y = d @ up
        ok = Z > 0.2
        u = np.where(ok, cx + f * X / Z, -1).astype(np.float32); v = np.where(ok, cy - f * Y / Z, -1).astype(np.float32)
        img = s["img"] if keep else cv2.resize(s["img"], None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
        smp = cv2.remap(img, u, v, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        # feather: favour the image centre (lens distortion grows outwards); skip OSD strip at the bottom
        nx, ny = (u - w / 2) / (w / 2), (v - h / 2) / (h / 2)
        wt = np.clip(1 - np.maximum(np.abs(nx) / 0.85, np.abs(ny) / 0.85), 0, 1) ** 2
        wt[(v > h * 0.94) | (u < 0) | (v < 0) | (u >= w) | (v >= h)] = 0
        # the antenna boom turns with the camera: never paint it into the panorama
        wt[(u > w * 0.46) & (u < w * 0.59) & (v < h * 0.30)] = 0
        # final render: let the most central view win (sharp), prefer frames taken while standing still
        wt = wt ** (sharp / 2) * (1.0 if s["kind"] != "move" else 0.35)
        g = smp.mean(-1)
        acc[:, c0:c1] += smp * wt[..., None]; acc2[:, c0:c1] += g * g * wt; wsum[:, c0:c1] += wt
    n = np.maximum(wsum, 1e-6)
    mean = acc / n[..., None]
    var = acc2 / n - (mean.mean(-1)) ** 2
    cover = wsum > 1e-5   # drop the faint outer fringe
    return mean, var, cover

azs = [az_at(s["t"]) for s in snaps]
a0, a1 = math.floor(min(azs) - 36), math.ceil(max(azs) + 36)

# ---- fit lag and roll on a coarse render ----
best = None
for lag in (0.4, 0.6, 0.8, 1.0, 1.2):
    for roll in (0.0, 0.5, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0):
        _, var, cover = render(lag, roll, 4, a0, a1)
        score = float(np.mean(var[cover]))
        if best is None or score < best[0]:
            best = (score, lag, roll)
print(f"best lag {best[1]} s, roll {best[2]} deg (overlap variance {best[0]:.1f})")
lag, roll = best[1], best[2]

PPD = 30
pano, _, cover = render(lag, roll, PPD, a0, a1, keep=True, sharp=16)
pano[~cover] = (24, 24, 26)
os.makedirs(OUT, exist_ok=True)
cv2.imwrite(f"{OUT}/panorama.jpg", np.clip(pano, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 88])

# ---- analysis (same model as tilt_analyze.py) ----
rows = []
for f in sorted(glob.glob(f"{D}/event*_shift.csv")):
    tag = f[:-len("_shift.csv")]
    tau = json.load(open(f"{tag}.json")).get("tau_s", 1.0); tau = tau if 0.3 < tau < 2.5 else 1.0
    az = np.array([[float(t), float(a)] for t, a in list(csv.reader(open(f"{tag}_az.csv")))[1:]])
    sh = np.array([[float(x) for x in r] for r in list(csv.reader(open(f)))[1:]])
    if len(az) < 2 or len(sh) < 2:
        continue
    a = np.interp(sh[:, 0] - tau, az[:, 0], np.degrees(np.unwrap(np.radians(az[:, 1])))) % 360
    m = (np.abs(sh[:, 1]) > 1.0) & (sh[:, 3] > 0.1)
    rows += list(zip(a[m], sh[m, 1], sh[m, 2]))
r = np.array(rows); az_, dx, dy = r[:, 0], r[:, 1], r[:, 2]
X = np.vstack([dx, dx * np.sin(np.radians(az_)), dx * np.cos(np.radians(az_))]).T
def fit(i):
    return np.linalg.lstsq(X[i], dy[i], rcond=None)[0]
c, A, B = fit(np.arange(len(r)))
T = math.degrees(math.hypot(A, B)); phi = math.degrees(math.atan2(A, B)) % 360
rng = np.random.default_rng(0)
boot = np.array([fit(rng.integers(0, len(r), len(r))) for _ in range(300)])
bs = np.degrees(np.hypot(boot[:, 1], boot[:, 2]))
# beam elevation change E(az) = -T sin(az - phi), with dE/daz = -(dy/dx - c); in degrees
grid = np.arange(360)
def elev(A_, B_):
    T_ = math.degrees(math.hypot(A_, B_)); ph = math.degrees(math.atan2(A_, B_))
    return -T_ * np.sin(np.radians(grid - ph))
E_all = np.array([elev(b[1], b[2]) for b in boot])
E_fit = elev(A, B)
bins = []
for b in range(0, 360, 15):
    m = (az_ >= b) & (az_ < b + 15)
    if m.sum() >= 40:
        bins.append({"az": b + 7.5, "frames": int(m.sum()), "ratio_mrad": float(1000 * np.sum(dy[m] * np.sign(dx[m])) / np.sum(np.abs(dx[m])))})

obj = json.load(open(OBJ)); st = obj["station"]
def bearing(la, lo):
    p1, p2 = math.radians(st["lat"]), math.radians(la); dl = math.radians(lo - st["lon"])
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360

def loc2ll(loc):
    loc = loc.upper(); lon = (ord(loc[0]) - 65) * 20 - 180 + int(loc[2]) * 2; lat = (ord(loc[1]) - 65) * 10 - 90 + int(loc[3])
    if len(loc) >= 6:
        lon += (ord(loc[4]) - 65) * 5 / 60 + 2.5 / 60; lat += (ord(loc[5]) - 65) * 2.5 / 60 + 1.25 / 60
    return lat, lon

marks = []
for o in obj["objects"]:
    la, lo = (o["lat"], o["lon"]) if "lat" in o else loc2ll(o["locator"])
    dist = 6371 * 2 * math.asin(math.sqrt(math.sin(math.radians(la - st["lat"]) / 2) ** 2 + math.cos(math.radians(st["lat"])) * math.cos(math.radians(la)) * math.sin(math.radians(lo - st["lon"]) / 2) ** 2))
    el = math.degrees(math.atan2((o.get("h", st["h"]) - st["h"]) / 1000, dist)) - dist / (2 * 6371) * 0.87 * 180 / math.pi if o["kind"] != "radio" else None
    marks.append({"name": o["name"], "kind": o["kind"], "az": bearing(la, lo), "el": el, "km": dist})

covered = sorted(set(int(a // 5) * 5 for a in az_))
json.dump({
    "pano": {"a0": a0, "a1": a1, "e0": -24.0, "e1": 22.0, "ppd": PPD, "file": "panorama.jpg"},
    "snapshots": len(snaps), "lag_s": lag, "roll_fit_deg": roll,
    "frames": int(len(r)), "coverage_deg": 15 * len(bins), "covered_5deg": covered,
    "fit": {"roll_deg": math.degrees(c), "tilt_deg": T, "tilt_p5": float(np.percentile(bs, 5)), "tilt_p95": float(np.percentile(bs, 95)),
            "phase_deg": phi, "highest_az": (phi - 90) % 360, "lean_az": (phi + 90) % 360, "c_mrad": 1000 * c,
            "A_mrad": 1000 * A, "B_mrad": 1000 * B},
    "bins": bins, "marks": marks, "pitch": PITCH,
    "elev": {"az": grid.tolist(), "fit": np.round(E_fit, 4).tolist(),
             "p5": np.round(np.percentile(E_all, 5, axis=0), 4).tolist(), "p95": np.round(np.percentile(E_all, 95, axis=0), 4).tolist(),
             "max": float(E_fit.max()), "max_az": int(grid[E_fit.argmax()]), "min": float(E_fit.min()), "min_az": int(grid[E_fit.argmin()])},
}, open(f"{OUT}/analysis.json", "w"), indent=1)
print(f"panorama {a0}..{a1} deg az, tilt {T:.2f} deg, roll {math.degrees(c):+.2f} deg, {len(snaps)} snaps")

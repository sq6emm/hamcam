"""Mast tilt from recorded moves: vertical/horizontal image motion vs azimuth.
dy/dx = c + A sin(az) + B cos(az); c -> camera roll on its mount, sqrt(A^2+B^2) -> rotation-axis (mast) tilt.
Usage: tilt_analyze.py <dir> [--coverage]   (--coverage: print covered degrees only, exit 0 if >= 300)"""
import csv, glob, json, sys
import numpy as np
d = sys.argv[1]
rows = []
for f in sorted(glob.glob(f"{d}/event*_shift.csv")):
    tag = f[:-len("_shift.csv")]
    tau = json.load(open(f"{tag}.json")).get("tau_s", 1.0)
    tau = tau if 0.3 < tau < 2.5 else 1.0
    az = np.array([[float(t), float(a)] for t, a in list(csv.reader(open(f"{tag}_az.csv")))[1:]])
    sh = np.array([[float(x) for x in r] for r in list(csv.reader(open(f)))[1:]])
    if len(az) < 2 or len(sh) < 2:
        continue
    a = np.interp(sh[:, 0] - tau, az[:, 0], np.degrees(np.unwrap(np.radians(az[:, 1])))) % 360
    m = (np.abs(sh[:, 1]) > 1.0) & (sh[:, 3] > 0.1)
    rows += list(zip(a[m], sh[m, 1], sh[m, 2]))
r = np.array(rows) if rows else np.zeros((0, 3))
bins = [b for b in range(0, 360, 15) if ((r[:, 0] >= b) & (r[:, 0] < b + 15)).sum() >= 40] if len(r) else []
cover = 15 * len(bins)
if "--coverage" in sys.argv:
    print(f"coverage {cover} deg, {len(r)} frames"); sys.exit(0 if cover >= 300 else 1)
az, dx, dy = r[:, 0], r[:, 1], r[:, 2]
print(f"{len(r)} moving frames, coverage {cover} deg of azimuth\n\naz bin    frames  dy/dx [mrad]")
for b in range(0, 360, 15):
    m = (az >= b) & (az < b + 15)
    if m.sum() >= 40:
        print(f"{b:3d}-{b+15:3d}   {m.sum():5d}   {1000*np.sum(dy[m]*np.sign(dx[m]))/np.sum(np.abs(dx[m])):+7.2f}")
s, co = np.sin(np.radians(az)), np.cos(np.radians(az))
X = np.vstack([dx, dx*s, dx*co]).T
def fit(i):
    c, A, B = np.linalg.lstsq(X[i], dy[i], rcond=None)[0]
    return c, np.degrees(np.hypot(A, B)), np.degrees(np.arctan2(A, B)) % 360
c, T, phi = fit(np.arange(len(r)))
# dE/daz = -(dy/dx) (dx<0 when az increases, dy>0 = camera tilting up)  =>  E(az) = -T sin(az - phi)
up = (phi - 90) % 360
rng = np.random.default_rng(0)
bs = np.array([fit(rng.integers(0, len(r), len(r)))[1] for _ in range(300)])
print(f"\ncamera roll on mount : {np.degrees(c):+.2f} deg")
print(f"mast (axis) tilt     : {T:.2f} deg   (90% bootstrap {np.percentile(bs,5):.2f} .. {np.percentile(bs,95):.2f})")
print(f"beam highest towards : {up:.0f} deg az, lowest towards {(up+180)%360:.0f} deg -> mast top leans to ~{(up+180)%360:.0f} deg")

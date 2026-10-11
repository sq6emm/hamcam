"""Tilt analysis of full sweeps, per sweep, per direction and combined. Usage: sweep_analyze.py <dir>"""
import csv, glob, json, math, sys
import numpy as np
D = sys.argv[1]

def load(tag):
    m = json.load(open(f"{D}/{tag}.json")); tau = float(__import__("os").environ.get("TAU", 0)) or (m["tau_s"] if 0.3 < m["tau_s"] < 2.5 else 1.0)
    az = np.array([[float(t), float(a)] for t, a in list(csv.reader(open(f"{D}/{tag}_az.csv")))[1:]])
    sh = np.array([[float(x) for x in r] for r in list(csv.reader(open(f"{D}/{tag}_shift.csv")))[1:]])
    a = np.interp(sh[:, 0] - tau, az[:, 0], np.degrees(np.unwrap(np.radians(az[:, 1])))) % 360
    k = (np.abs(sh[:, 1]) > 1.0) & (sh[:, 3] > 0.1)
    return a[k], sh[k, 1], sh[k, 2], sh[k, 3], m

def fit(az, dx, dy):
    X = np.vstack([dx, dx * np.sin(np.radians(az)), dx * np.cos(np.radians(az))]).T
    c, A, B = np.linalg.lstsq(X, dy, rcond=None)[0]
    return math.degrees(c), math.degrees(math.hypot(A, B)), (math.degrees(math.atan2(A, B)) - 90) % 360

allr = {"cw": [], "ccw": []}
print("sweep            dir  frames   roll   tilt  highest  tau   resp")
for f in sorted(glob.glob(f"{D}/event*_shift.csv")):
    tag = f.split("/")[-1][:-10]
    az, dx, dy, resp, m = load(tag)
    if m["az_span_deg"] < 300:
        continue
    d = "cw" if m["az_to"] > m["az_from"] else "ccw"
    c, T, hi = fit(az, dx, dy)
    allr[d].append((az, dx, dy))
    print(f"{tag:16s} {d:4s} {len(az):6d}  {c:+.2f}  {T:.2f}  {hi:6.0f}  {m['tau_s']:.2f}  {np.median(resp):.2f}")
cat = lambda L: [np.concatenate([x[i] for x in L]) for i in range(3)]
for d in ("cw", "ccw"):
    c, T, hi = fit(*cat(allr[d])); print(f"all {d:4s}: roll {c:+.2f}  tilt {T:.2f}  highest {hi:.0f}")
az, dx, dy = cat(allr["cw"] + allr["ccw"])
c, T, hi = fit(az, dx, dy)
rng = np.random.default_rng(1)
bs = np.array([fit(*(v[i] for v in (az, dx, dy)))[1:] for i in (rng.integers(0, len(az), len(az)) for _ in range(400))])
dphi = np.abs((bs[:, 1] - hi + 180) % 360 - 180)
print(f"\nCOMBINED cw+ccw: roll {c:+.2f} deg | tilt {T:.2f} deg (90% {np.percentile(bs[:,0],5):.2f}-{np.percentile(bs[:,0],95):.2f})"
      f" | beam highest toward {hi:.0f} deg (90% +-{np.percentile(dphi,90):.0f}) | lowest {((hi+180)%360):.0f}")
print("\naz bin   dy/dx [mrad]  cw     ccw")
for b in range(0, 360, 30):
    row = []
    for d in ("cw", "ccw"):
        a_, x_, y_ = cat(allr[d]); k = (a_ >= b) & (a_ < b + 30)
        row.append(f"{1000*np.sum(y_[k]*np.sign(x_[k]))/max(np.sum(np.abs(x_[k])),1):+6.1f}" if k.sum() > 20 else "   -  ")
    print(f"{b:3d}-{b+30:3d}            {row[0]}  {row[1]}")

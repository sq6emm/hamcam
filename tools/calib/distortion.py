"""Lens distortion from rotator-turned frames: SIFT matches between frames at known yaws, fit
f, k1, k2 (radial, r_d = r_u (1 + k1 r_u^2 + k2 r_u^4), normalized tan-plane coords), pitch, roll, per-frame yaw.
Usage: distortion.py <dir with azNNN_1.jpg>"""
import glob, json, math, re, sys
import cv2, numpy as np
D = sys.argv[1]
files = sorted(glob.glob(f"{D}/az*_1.jpg"), key=lambda p: int(re.search(r"az(\d+)_", p).group(1)))
yaw0 = [float(re.search(r"az(\d+)_", p).group(1)) for p in files]
imgs = [cv2.imread(p, cv2.IMREAD_GRAYSCALE) for p in files]
H, W = imgs[0].shape; cx, cy = W / 2, H / 2
sift = cv2.SIFT_create(6000)
mask = np.zeros((H, W), np.uint8); mask[int(H * 0.47):int(H * 0.80), 40:W - 40] = 255   # ground band, below horizon, above boom
kd = [sift.detectAndCompute(im, mask) for im in imgs]
bf = cv2.BFMatcher()
M = []   # (i, j, xi, yi, xj, yj)
for i in range(len(files)):
    for j in range(i + 1, len(files)):
        dyaw = yaw0[j] - yaw0[i]
        if not 4 <= abs(dyaw) <= 32: continue
        mm = bf.knnMatch(kd[i][1], kd[j][1], k=2)
        good = [m for m, n in mm if m.distance < 0.7 * n.distance]
        if len(good) < 20: continue
        p = np.float32([kd[i][0][m.queryIdx].pt for m in good]); q = np.float32([kd[j][0][m.trainIdx].pt for m in good])
        dx = q[:, 0] - p[:, 0]
        exp = -dyaw * 34.6
        ok = (np.abs(dx - exp) < 0.35 * abs(exp) + 60) & (np.abs(q[:, 1] - p[:, 1]) < 40)
        p, q = p[ok], q[ok]
        if len(p) < 15: continue
        _, inl = cv2.findHomography(p, q, cv2.RANSAC, 12.0)
        inl = inl.ravel().astype(bool)
        for a, b in zip(p[inl], q[inl]): M.append((i, j, *a, *b))
        print(f"pair {yaw0[i]:.0f}-{yaw0[j]:.0f}: {inl.sum()} matches", flush=True)
M = np.array(M); print("total matches", len(M))

CYOFF = [0.0]; PP = [0.0, 0.0]
def undist(x, y, f, k1, k2):
    xd, yd = (x - cx - PP[0]) / f, (y - cy - CYOFF[0] - PP[1]) / f
    rd = np.hypot(xd, yd); ru = rd.copy()
    for _ in range(20): ru = ru - (ru * (1 + k1 * ru**2 + k2 * ru**4) - rd) / (1 + 3 * k1 * ru**2 + 5 * k2 * ru**4)
    s = np.where(rd > 1e-9, ru / np.maximum(rd, 1e-12), 1.0)
    return xd * s, yd * s
def dirs(X, Y, yaw, pitch, roll):
    # camera axes (same convention as sky.js Camera)
    p, t, r = np.radians(yaw), math.radians(pitch), math.radians(roll)
    fwd = np.stack([np.sin(p) * math.cos(t), np.cos(p) * math.cos(t), np.full_like(p, math.sin(t))], -1)
    right0 = np.stack([np.cos(p), -np.sin(p), np.zeros_like(p)], -1)
    up0 = np.cross(right0, fwd)
    right = right0 * math.cos(r) + up0 * math.sin(r); up = up0 * math.cos(r) - right0 * math.sin(r)
    d = fwd + X[:, None] * right + Y[:, None] * up
    return d / np.linalg.norm(d, axis=1, keepdims=True)
import os
FIXP = float(os.environ['PITCH']) if 'PITCH' in os.environ else None
NF = len(files); REF = yaw0.index(122.0)
def resid(P, Mx):
    f, k1, k2, pitch, roll = P[:5]; NPP = len(P) - 5 - NF; PP[:] = list(P[5:5 + NPP]) + [0.0] * (2 - NPP); yaws = np.array(yaw0) + P[5 + NPP:]
    if FIXP is not None: CYOFF[0] = pitch; pitch = FIXP
    I, J = Mx[:, 0].astype(int), Mx[:, 1].astype(int)
    Xi, Yi = undist(Mx[:, 2], Mx[:, 3], f, k1, k2); Xj, Yj = undist(Mx[:, 4], Mx[:, 5], f, k1, k2)
    di = dirs(Xi, -Yi, yaws[I], pitch, roll); dj = dirs(Xj, -Yj, yaws[J], pitch, roll)
    r = np.degrees(np.cross(di, dj)).ravel()          # small-angle difference (deg)
    yp = P[len(P) - NF:]
    prior = yp / 0.3                                   # rotator yaw prior +-0.3 deg
    prior[REF] = yp[REF] / 0.01                     # anchor frame at 122
    return np.concatenate([r, prior])
def fit(P, Mx, fixk=False):
    lam = 1e-3
    for it in range(60):
        r = resid(P, Mx); J = np.zeros((len(r), len(P)))
        for k in range(len(P)):
            if fixk and k in (1, 2) + tuple(range(5, 5 + NPP0)): continue
            h = 1e-6 * max(1, abs(P[k])); Q = P.copy(); Q[k] += h; J[:, k] = (resid(Q, Mx) - r) / h
        A = J.T @ J; g = J.T @ r
        step = -np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-12), g)
        Pn = P + step
        if (resid(Pn, Mx)**2).sum() < (r**2).sum(): P, lam = Pn, lam * 0.3
        else: lam *= 10
    return P
NPP0 = int(os.environ.get('NPP', '0'))
P0 = np.array([1982.0, 0.0, 0.0, 0.0 if FIXP is not None else -1.28, 1.1] + [0.0] * NPP0 + [0.0] * NF)
P_rect = fit(P0.copy(), M, fixk=True)
P = fit(P0.copy(), M)
for it in range(2):    # drop outliers > 3 sigma
    r = resid(P, M)[:3 * len(M)].reshape(-1, 3); e = np.linalg.norm(r, axis=1)
    keep = e < 3 * np.median(e) * 1.5; M = M[keep]; P = fit(P, M)
    P_rect = fit(P_rect, M, fixk=True)
def rms(P): r = resid(P, M)[:3 * len(M)].reshape(-1, 3); return float(np.sqrt((np.linalg.norm(r, axis=1)**2).mean()))
f, k1, k2, pitch, roll = P[:5]
print(f"\nrectilinear only: f={P_rect[0]:.1f}  rms {rms(P_rect):.3f} deg")
print("(pitch fixed, 4th value = principal point y offset px)" if FIXP is not None else "")
print(f"with distortion : f={f:.1f} k1={k1:+.4f} k2={k2:+.4f} pitch={pitch:+.2f} roll={roll:+.2f}  rms {rms(P):.3f} deg  ({len(M)} matches)")
print("principal point offset (px):", np.round(P[5:5 + NPP0], 1))
print("yaw corrections:", dict(zip(yaw0, np.round(P[len(P) - NF:], 2))))
# where does an object at angle a (horizontal, on the centre row) land, rectilinear-centre model vs fitted
def x_of(a, f, k1, k2):
    ru = math.tan(math.radians(a)); return cx + f * ru * (1 + k1 * ru**2 + k2 * ru**4)
print("\nangle  old model x  fitted x  difference")
for a in (5, 10, 15, 20, 25, 30, 35, 40):
    xo = cx + 1982 * math.tan(math.radians(a)); xn = x_of(a, f, k1, k2)
    print(f"{a:5d}  {xo:9.0f}  {xn:9.0f}  {xo - xn:+7.0f} px")
# horizontal field of view with the fitted model
lo, hi = 0, 60
for _ in range(60):
    m = (lo + hi) / 2
    if x_of(m, f, k1, k2) < W: lo = m
    else: hi = m
print(f"HFOV = {2 * lo:.1f} deg")
json.dump({"pp": [float(v) for v in P[5:5 + NPP0]], "f": f, "k1": k1, "k2": k2, "pitch": pitch, "roll": roll, "rms": rms(P), "n": len(M), "W": W, "H": H},
          open(f"{D}/distortion{os.environ.get('TAG','')}.json", "w"), indent=1)

"""Daylight panorama for the page's Day view: frames from capture.sh -> one image in true azimuth / elevation.

Every panorama pixel (az, el) is looked up in the frames through the same camera model the page uses (sky.js Camera:
f, k1/k2, optical centre, pitch, roll, mast tilt), so the page can project it back for any rotator azimuth and the
overlay lands on the same objects as on the live video. Per frame the yaw/elevation scatter of the rotator is
removed by aligning neighbouring frames (edges below the skyline), exposure differences by a gain per frame.
Usage: build.py <frames dir> <out dir> <objects.json>
Out: panorama.jpg (8192 px = 360 deg), panorama-4k.jpg (4096 px, for GPUs with small textures), panorama.json
"""
import glob, json, math, os, re, sys
import cv2
import numpy as np

FR, OUT, OBJ = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(OUT, exist_ok=True)
cam = json.load(open(OBJ))["camera"]
W, H = cam["width"], cam["height"]
F = cam["f_px"] * W / cam["f_ref_w"]
K1, K2 = cam.get("k1", 0), cam.get("k2", 0)
PP = [v * W / cam["f_ref_w"] for v in cam.get("pp_px", [0, 0])]
CX, CY = W / 2 + PP[0], H / 2 + PP[1]
A0, E0 = math.degrees(math.atan(-PP[0] / F)), math.degrees(math.atan(PP[1] / F))
TILT = cam.get("tilt")
EL_MIN, EL_MAX = -36.0, 30.0              # the view corners reach this far (barrel lens + mast tilt)
PW = 8192                                       # 360 deg; ~22.8 px/deg = the page's 1600 px view at 1x zoom


def tilt_delta(az):
    if not TILT:
        return 0.0
    d = lambda a: TILT["A"] * np.sin(np.radians(a)) + TILT["B"] * np.cos(np.radians(a))
    return d(az) - d(TILT.get("ref_az", 121.95))


def maps(yaw, az, el, pitch_add=0.0):
    """frame pixel coordinates (x, y) of world directions az/el (deg arrays) for a camera at image-centre yaw"""
    p, t, r = math.radians(yaw - A0), math.radians(cam["pitch"] + pitch_add - E0), math.radians(cam["roll"])
    fwd = np.array([math.sin(p) * math.cos(t), math.cos(p) * math.cos(t), math.sin(t)])
    right0 = np.array([math.cos(p), -math.sin(p), 0.0]); up0 = np.cross(right0, fwd)
    right = right0 * math.cos(r) + up0 * math.sin(r); up = up0 * math.cos(r) - right0 * math.sin(r)
    a, e = np.radians(az), np.radians(el + tilt_delta(az))
    d = np.stack([np.sin(a) * np.cos(e), np.cos(a) * np.cos(e), np.sin(e)], -1)
    Z = d @ fwd
    X, Y = (d @ right) / Z, (d @ up) / Z
    r2 = X * X + Y * Y; s = 1 + K1 * r2 + K2 * r2 * r2
    x, y = CX + F * X * s, CY - F * Y * s
    bad = (Z < 0.3) | (r2 > 0.9)                # behind / far outside the lens model's range
    x[bad] = -1e4; y[bad] = -1e4
    return x.astype(np.float32), y.astype(np.float32)


# ---- frames: the middle of the 3 grabs per stop, yaw = settled rotator az (+ az_offset) ----
frames = []
for p in sorted(glob.glob(f"{FR}/g[0-9][0-9][0-9]_1.jpg")):
    stop = re.search(r"g(\d{3})_1", p).group(1)
    log = open(f"{FR}/g{stop}.txt").read() if os.path.exists(f"{FR}/g{stop}.txt") else ""
    m = re.findall(r"final az ([\d.]+)", log) or re.findall(r"settled az ([\d.]+)", log)
    az = float(m[-1]) if m else float(stop)
    img = cv2.imread(p)
    if img is None or img.shape[:2] != (H, W):
        continue
    frames.append({"stop": int(stop), "rot": az, "img": img, "daz": 0.0, "del": 0.0, "gain": 1.0})
print(f"{len(frames)} frames: " + " ".join(f"{f['stop']}->{f['rot']:.0f}" for f in frames))

# weight: high in the middle of a frame, 0 at its edges and in the masks of <frames>/../osd.json ([x0,y0,x1,y1] px:
# the camera OSD text and the antenna boom, which turn with the camera and are filled in from the neighbouring frames)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
WGT = (np.clip(np.minimum(xx, W - 1 - xx) / (W / 2), 0, 1) ** 4) * np.clip(np.minimum(yy, H - 1 - yy) / (H * 0.12), 0, 1)
MASK = np.full((H, W), 255, np.uint8)
for x0, y0, x1, y1 in json.load(open(f"{FR}/../osd.json")) if os.path.exists(f"{FR}/../osd.json") else []:
    MASK[y0:y1, x0:x1] = 0
WGT = (WGT * np.clip(cv2.distanceTransform(MASK, cv2.DIST_L2, 5) / 200.0, 0, 1)).astype(np.float32)   # soft mask edges
RAD = (np.hypot(xx - CX, yy - CY) / math.hypot(W / 2, H / 2)).astype(np.float32)   # radius from the optical centre, 1 = corner


def render(f, ppd, az0, az1, gray=False):
    nx, ny = int(round((az1 - az0) * ppd)), int(round((EL_MAX - EL_MIN) * ppd))
    az = az0 + (np.arange(nx) + 0.5) / ppd
    el = EL_MAX - (np.arange(ny) + 0.5) / ppd
    AZ, EL = np.meshgrid(az, el)
    mx, my = maps(f["rot"] + f["daz"], AZ % 360, EL, f["del"])
    src = cv2.cvtColor(f["img"], cv2.COLOR_BGR2GRAY) if gray else f["img"]
    if not gray and VIG is not None:
        src = np.clip(f["img"].astype(np.float32) / VIG[..., None], 0, 255).astype(np.uint8)
    im = cv2.remap(src, mx, my, cv2.INTER_LINEAR if ppd < 30 else cv2.INTER_CUBIC, borderValue=0)
    w = cv2.remap(WGT, mx, my, cv2.INTER_LINEAR, borderValue=0)
    if gray == "rad":
        return im, w, cv2.remap(RAD, mx, my, cv2.INTER_LINEAR, borderValue=0)
    return im, w


VIG = None
# ---- alignment of neighbours: shift of frame j against frame i in their overlap (edges, below +12 deg el) ----
PPD_A = 8.0
frames.sort(key=lambda f: f["rot"])
def measure(i, j):
    """shift (az, el deg) to add to frame j's yaw / pitch so it matches frame i in their overlap, gain log ratio, corr"""
    a, b = frames[i], frames[j]
    gap = (b["rot"] + b["daz"] - a["rot"] - a["daz"]) % 360
    lo, hi = a["rot"] + a["daz"] + gap / 2 - 14, a["rot"] + a["daz"] + gap / 2 + 14
    ia, wa = render(a, PPD_A, lo - 3, hi + 3, gray=True)
    ib, wb = render(b, PPD_A, lo - 3, hi + 3, gray=True)
    edge = lambda im: np.sqrt(cv2.Sobel(im.astype(np.float32), cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(im.astype(np.float32), cv2.CV_32F, 0, 1) ** 2)
    ea, eb = edge(ia), edge(ib)
    rows = slice(int((EL_MAX - 12) * PPD_A), int((EL_MAX - EL_MIN - 2) * PPD_A))   # below +12 deg: buildings, not clouds
    best = None
    for dx in range(-16, 17):                       # 1/8 deg steps, +-2 deg
        for dy in range(-6, 7):
            sb = np.roll(np.roll(eb, dy, 0), dx, 1)
            m = (wa > 0.02) & (np.roll(np.roll(wb, dy, 0), dx, 1) > 0.02)
            m[:, :24] = m[:, -24:] = False; m[:rows.start] = False; m[rows.stop:] = False
            if m.sum() < 2000:
                continue
            c = np.corrcoef(ea[m], sb[m])[0, 1]
            if best is None or c > best[0]:
                best = (c, dx, dy)
    if best is None:
        return None
    c, dx, dy = best
    m = (wa > 0.02) & (wb > 0.02)
    g = float(np.log((ia[m].astype(np.float32).mean() + 1) / (ib[m].astype(np.float32).mean() + 1)))
    # b's picture shifted by dx px towards higher az matches a -> b's yaw was dx/PPD_A deg too small (same for el, rows grow downwards)
    return dx / PPD_A, -dy / PPD_A, g, c

pairs = []
for i in range(len(frames)):
    j = (i + 1) % len(frames)
    if not 5 < (frames[j]["rot"] - frames[i]["rot"]) % 360 < 50:
        continue
    r = measure(i, j)
    if r:
        pairs.append((i, j, *r))
        print(f"pair {frames[i]['stop']:3d}-{frames[j]['stop']:3d}: daz {r[0]:+.2f}  del {r[1]:+.2f}  gain {math.exp(r[2]):.2f}  corr {r[3]:.2f}")

# ---- vignetting V(r) = 1 + a r^2 + b r^4 (r = 1 in the corner): the brightness of a scene point must not depend on where it
# sits in the two overlapping frames (up to a gain per frame)
samples = []
for i, j, *_ in pairs:
    ia, wa, ra = render(frames[i], PPD_A, frames[i]["rot"] - 10, frames[j]["rot"] + 10 + (360 if frames[j]["rot"] < frames[i]["rot"] else 0), gray="rad")
    ib, wb, rb = render(frames[j], PPD_A, frames[i]["rot"] - 10, frames[j]["rot"] + 10 + (360 if frames[j]["rot"] < frames[i]["rot"] else 0), gray="rad")
    m = (wa > 0.002) & (wb > 0.002) & (ia > 25) & (ia < 240) & (ib > 25) & (ib < 240)
    samples.append((np.log(ia[m].astype(np.float32)) - np.log(ib[m].astype(np.float32)), ra[m] ** 2, rb[m] ** 2))
best = (1e9, 0.0, 0.0)
for a in np.arange(-0.8, 0.21, 0.02):
    for b in np.arange(-0.4, 0.41, 0.04):
        cost = 0.0
        for d, r2a, r2b in samples:
            va, vb = 1 + a * r2a + b * r2a ** 2, 1 + a * r2b + b * r2b ** 2
            if va.min() <= 0.2 or vb.min() <= 0.2:
                cost = 1e9; break
            e = d - np.log(va) + np.log(vb)
            cost += float(np.var(e)) * len(e)
        if cost < best[0]:
            best = (cost, a, b)
_, va_, vb_ = best
r2 = RAD ** 2
VIG = (1 + va_ * r2 + vb_ * r2 * r2).astype(np.float32)
print(f"vignetting a {va_:+.2f} b {vb_:+.2f}: corner at {1 + va_ + vb_:.2f} of the centre")
for k, (i, j, dz, de, g, c) in enumerate(pairs):        # gains again, on corrected frames
    a, b = frames[i], frames[j]
    lo, hi = a["rot"] - 10, b["rot"] + 10 + (360 if b["rot"] < a["rot"] else 0)
    ia, wa = render(a, PPD_A, lo, hi); ib, wb = render(b, PPD_A, lo, hi)
    m = (wa > 0.02) & (wb > 0.02)
    pairs[k] = (i, j, dz, de, float(np.log((ia[m].astype(np.float32).mean() + 1) / (ib[m].astype(np.float32).mean() + 1))), c)

# least squares: off_j - off_i = measured, sum = 0 (the rotator's mean is right: az_offset is calibrated on Sky Tower)
n = len(frames)
def solve(k):
    A, b = [], []
    for i, j, dz, de, g, c in pairs:
        if c < 0.3:
            continue
        r = np.zeros(n); r[j] = 1; r[i] = -1; A.append(r * c); b.append([dz, de, g][k] * c)
    A.append(np.ones(n) * 3); b.append(0.0)
    return np.linalg.lstsq(np.array(A), np.array(b), rcond=None)[0]
dz, de, lg = solve(0), solve(1), solve(2)
for f, z, e, g in zip(frames, dz, de, lg):
    f["daz"], f["del"], f["gain"] = float(z), float(e), float(math.exp(g))
print("yaw corr  " + " ".join(f"{f['daz']:+.2f}" for f in frames))
print("el corr   " + " ".join(f"{f['del']:+.2f}" for f in frames))
print("gain      " + " ".join(f"{f['gain']:.2f}" for f in frames))
res = [measure(i, j) for i, j, *_ in pairs]          # check: what is left after the correction (should be ~0)
print("residual az " + " ".join(f"{r[0]:+.2f}" for r in res if r))

# ---- full panorama: weighted blend, rendered in azimuth strips ----
ppd = PW / 360.0
PH = int(round((EL_MAX - EL_MIN) * ppd))
acc = np.zeros((PH, PW, 3), np.float32); ws = np.zeros((PH, PW), np.float32)
for f in frames:
    c0 = int(math.floor((f["rot"] + f["daz"] - 45) * ppd)); c1 = int(math.ceil((f["rot"] + f["daz"] + 45) * ppd))
    im, w = render(f, ppd, c0 / ppd, c1 / ppd)
    cols = np.arange(c0, c1) % PW
    acc[:, cols] += im.astype(np.float32) * (w * f["gain"])[..., None]
    ws[:, cols] += w
    print(f"rendered {f['stop']}", flush=True)
pano = np.where(ws[..., None] > 1e-4, acc / np.maximum(ws, 1e-4)[..., None], 0)
pano = np.clip(pano, 0, 255).astype(np.uint8)
cv2.imwrite(f"{OUT}/panorama.jpg", pano, [cv2.IMWRITE_JPEG_QUALITY, 85, cv2.IMWRITE_JPEG_PROGRESSIVE, 1])
cv2.imwrite(f"{OUT}/panorama-4k.jpg", cv2.resize(pano, (PW // 2, PH // 2), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 85])
cv2.imwrite(f"{OUT}/preview.jpg", cv2.resize(pano, (PW // 4, PH // 4), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 80])
meta = {"vignetting": [round(va_, 3), round(vb_, 3)], "image": "panorama.jpg", "image_small": "panorama-4k.jpg", "width": PW, "height": PH,
        "az0": 0.0, "az1": 360.0, "el_max": EL_MAX, "el_min": EL_MIN,
        "captured": sorted(os.path.basename(FR.rstrip('/')) for _ in [0])[0],
        "taken_utc": None, "frames": [{"stop": f["stop"], "rot": f["rot"], "daz": round(f["daz"], 3), "del": round(f["del"], 3),
                                        "gain": round(f["gain"], 3)} for f in frames]}
t = [os.stat(p).st_mtime for p in glob.glob(f"{FR}/g*_1.jpg")]
if t:
    import datetime
    meta["taken_utc"] = datetime.datetime.fromtimestamp(sum(t) / len(t), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
meta.pop("captured")
json.dump(meta, open(f"{OUT}/panorama.json", "w"), indent=1)
print(f"panorama {PW}x{PH}, el {EL_MIN}..{EL_MAX}, taken {meta['taken_utc']} UTC")

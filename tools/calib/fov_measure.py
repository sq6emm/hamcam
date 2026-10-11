"""Passive FOV + latency measurement: waits for the rotator to move (never commands it).

While the rotator turns, the far scene shifts horizontally in the image. We track that shift
frame-to-frame (phase correlation on a band below the horizon, away from the boom) and compare
the accumulated pixel shift with the azimuth reported by rotctld:

    px(t) = k * (az(t - tau) - az0) + c

k   -> pixels per degree near the image centre -> focal length -> horizontal FOV
tau -> how far the video lags behind rotctld (camera + decode latency, relative to rotctld polling)

Env: RTSP, ROTCTLD_HOST, ROTCTLD_PORT, OUT (dir), MAX_WAIT_S, EVENTS (number of moves to record)
"""
import collections
import csv
import json
import math
import os
import socket
import subprocess
import threading
import time
import urllib.request

import cv2  # noqa: E402
import numpy as np  # noqa: E402

RTSP = os.environ["RTSP"]
ROT = (os.environ.get("ROTCTLD_HOST", "192.168.14.199"), int(os.environ.get("ROTCTLD_PORT", "4533")))
OUT = os.environ.get("OUT", "/out")
MAX_WAIT = float(os.environ.get("MAX_WAIT_S", str(6 * 3600)))
EVENTS = int(os.environ.get("EVENTS", "3"))
SNAP_URL = os.environ.get("SNAP_URL", "")          # full-res still (go2rtc frame.jpeg); empty = no snapshots
SNAP_S = float(os.environ.get("SNAP_S", "2"))       # snapshot interval while moving
PRE_S, POST_S = 8.0, 6.0          # keep this much before the move starts / after it stops
FULL_W, FULL_H = 2560, 1920       # main stream
WORK_W, WORK_H = 1280, 960         # analysis size
SCALE = FULL_W / WORK_W
BAND_Y = (0.40, 0.62)             # rows: tree line / far scene, below the boom, above roof & OSD
BAND_X = (0.15, 0.85)

lock = threading.Lock()
az_log = collections.deque(maxlen=20000)     # (t, az)
shift_log = collections.deque(maxlen=20000)  # (t, dx, dy, response)
frames_keep = collections.deque(maxlen=3)    # latest full frame, for stills


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def rot_thread():
    while True:
        try:
            s = socket.create_connection(ROT, timeout=5)
            f = s.makefile("rwb")
            log("rotctld connected", ROT)
            while True:
                f.write(b"p\n"); f.flush()
                az = float(f.readline()); f.readline()
                with lock:
                    az_log.append((time.time(), az))
                time.sleep(0.1)
        except Exception as e:
            log("rotctld error", repr(e)); time.sleep(3)


def video_thread():
    """ffmpeg (multi-threaded decode + scale) -> raw gray frames on a pipe; keeps up with 30 fps main."""
    while True:
        cmd = ["ffmpeg", "-loglevel", "error", "-rtsp_transport", "tcp", "-fflags", "nobuffer", "-flags", "low_delay",
               "-threads", "8", "-i", RTSP, "-an", "-vf", f"scale={WORK_W}:{WORK_H}:flags=area,format=gray",
               "-f", "rawvideo", "-"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=4 * 1024 * 1024)  # buffered: read(n) returns whole frames
        log("rtsp open (ffmpeg)")
        n = WORK_W * WORK_H
        prev = None; win = None
        y0, y1 = int(WORK_H * BAND_Y[0]), int(WORK_H * BAND_Y[1])
        x0, x1 = int(WORK_W * BAND_X[0]), int(WORK_W * BAND_X[1])
        while True:
            buf = p.stdout.read(n)
            t = time.time()
            if len(buf) < n:
                log("rtsp read failed"); break
            img = np.frombuffer(buf, np.uint8).reshape(WORK_H, WORK_W)
            band = img[y0:y1, x0:x1].astype(np.float32)
            if win is None:
                win = cv2.createHanningWindow(band.shape[::-1], cv2.CV_32F)
            if prev is not None:
                (dx, dy), resp = cv2.phaseCorrelate(prev, band, win)
                with lock:
                    shift_log.append((t, dx * SCALE, dy * SCALE, resp))  # in full-res pixels
            prev = band
            with lock:
                frames_keep.append((t, img))
        p.kill(); time.sleep(1)


def snapshot(az, tag):
    try:
        os.makedirs(f"{OUT}/snaps", exist_ok=True)
        data = urllib.request.urlopen(SNAP_URL, timeout=5).read()
        name = f"{OUT}/snaps/{time.strftime('%H%M%S')}_{tag}_az{az:05.1f}.jpg"
        with open(name, "wb") as fp:
            fp.write(data)
    except Exception as e:
        log("snapshot failed", repr(e))


def window(log_deque, t0, t1):
    with lock:
        return [r for r in log_deque if t0 <= r[0] <= t1]


def analyse(az, sh, width):
    """Fit accumulated image shift to azimuth with a time offset. Returns dict."""
    ta = np.array([r[0] for r in az]); aa = np.unwrap(np.radians([r[1] for r in az]))
    aa = np.degrees(aa)
    ts = np.array([r[0] for r in sh]); dx = np.array([r[1] for r in sh]); resp = np.array([r[3] for r in sh])
    # drop low-confidence correlations (treat as zero motion would bias; interpolate instead)
    good = resp > 0.05
    if good.sum() < 10:
        return {"error": "too few good correlations"}
    dx = np.where(good, dx, np.interp(ts, ts[good], dx[good]))
    px = np.cumsum(dx)
    best = None
    for tau in np.arange(-0.2, 3.0, 0.01):
        a = np.interp(ts - tau, ta, aa)
        A = np.vstack([a - a[0], np.ones_like(a)]).T
        (k, c), res, *_ = np.linalg.lstsq(A, px, rcond=None)
        r = float(np.sqrt(np.mean((A @ [k, c] - px) ** 2)))
        if best is None or r < best["rms_px"]:
            best = {"tau_s": round(float(tau), 3), "k_px_per_deg": float(k), "rms_px": r}
    k = abs(best["k_px_per_deg"])
    f_px = k * 180 / math.pi                   # focal length in px (rectilinear, centre of image)
    best.update(
        az_span_deg=round(float(aa.max() - aa.min()), 2),
        px_span=round(float(px.max() - px.min()), 1),
        image_width=width,
        focal_px=round(f_px, 1),
        hfov_deg=round(math.degrees(2 * math.atan(width / 2 / f_px)), 2),
        deg_per_px_centre=round(1 / k, 5),
        direction="scene moves left when az increases" if best["k_px_per_deg"] < 0 else "scene moves right when az increases",
        good_frac=round(float(good.mean()), 3),
    )
    return best


def main():
    os.makedirs(OUT, exist_ok=True)
    threading.Thread(target=rot_thread, daemon=True).start()
    threading.Thread(target=video_thread, daemon=True).start()
    start = time.time(); events = 0; moving_since = None; last_change = None; last_az = None; next_snap = 0
    log(f"waiting for rotator movement (max {MAX_WAIT/3600:.1f} h, {EVENTS} events)")
    next_stat = time.time() + 20
    while time.time() - start < MAX_WAIT and events < EVENTS:
        time.sleep(0.2)
        if time.time() > next_stat:
            next_stat = time.time() + 60
            recent = window(shift_log, time.time() - 10, time.time())
            with lock:
                cur = az_log[-1][1] if az_log else None
            log(f"status: video {len(recent)/10:.1f} fps analysed, az {cur}, events {events}")
        with lock:
            if not az_log:
                continue
            t, az = az_log[-1]
        if last_az is not None and abs(az - last_az) >= 0.1:
            last_change = t
            with lock:
                video_ok = bool(shift_log) and shift_log[0][0] < t - PRE_S and shift_log[-1][0] > t - 1
            if moving_since is None and not video_ok:
                log("movement ignored (video not running long enough yet)")
            elif moving_since is None:
                moving_since = t
                log(f"movement started at az {last_az:.1f}")
                if SNAP_URL:
                    threading.Thread(target=snapshot, args=(last_az, "start"), daemon=True).start()
                next_snap = time.time() + SNAP_S
                with lock:
                    still_before = frames_keep[-1] if frames_keep else None
        last_az = az
        if SNAP_URL and moving_since is not None and t - last_change < 1.0 and time.time() > next_snap:
            next_snap = time.time() + SNAP_S
            threading.Thread(target=snapshot, args=(az, "move"), daemon=True).start()
        if moving_since is not None and t - last_change > POST_S:
            if SNAP_URL:
                threading.Thread(target=snapshot, args=(az, "stop"), daemon=True).start()
            t0, t1 = moving_since - PRE_S, last_change + POST_S
            az_w, sh_w = window(az_log, t0, t1), window(shift_log, t0, t1)
            with lock:
                still_after = frames_keep[-1] if frames_keep else None
            width = FULL_W
            res = analyse(az_w, sh_w, width)
            res.update(start=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(moving_since)),
                       az_from=az_w[0][1] if az_w else None, az_to=az_w[-1][1] if az_w else None,
                       duration_s=round(last_change - moving_since, 1), frames=len(sh_w))
            events += 1
            tag = f"event{events}_{time.strftime('%H%M%S', time.localtime(moving_since))}"
            with open(f"{OUT}/{tag}.json", "w") as fp:
                json.dump(res, fp, indent=2)
            with open(f"{OUT}/{tag}_az.csv", "w", newline="") as fp:
                csv.writer(fp).writerows([("t", "az")] + az_w)
            with open(f"{OUT}/{tag}_shift.csv", "w", newline="") as fp:
                csv.writer(fp).writerows([("t", "dx", "dy", "resp")] + sh_w)
            for name, still in (("before", still_before), ("after", still_after)):
                if still:
                    cv2.imwrite(f"{OUT}/{tag}_{name}.jpg", still[1], [cv2.IMWRITE_JPEG_QUALITY, 92])
            log(f"{tag}: {json.dumps(res)}")
            moving_since = None
    log(f"done: {events} event(s)")


if __name__ == "__main__":
    main()

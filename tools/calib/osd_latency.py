"""Camera latency from the burned-in OSD clock: arrival time of the frame where the seconds digit flips.
latency = arrival_time - whole_second (camera clock is NTP-synced). Single-thread decode = no decoder frame delay."""
import subprocess, sys, time
import numpy as np
RTSP = sys.argv[1]; N = int(sys.argv[2]) if len(sys.argv) > 2 else 30
W, H = 1280, 960
X0, X1, Y0, Y1 = 728, 766, 922, 952          # seconds digits of the OSD time (bottom centre), 1280x960 coords
cmd = ["ffmpeg", "-loglevel", "error", "-rtsp_transport", "tcp", "-fflags", "nobuffer", "-flags", "low_delay",
       "-threads", "1", "-i", RTSP, "-an", "-vf", f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"]
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=4 << 20)
prev = None; last_flip = 0; lat = []; diffs = []; t_start = time.time()
while len(lat) < N:
    buf = p.stdout.read(W * H); t = time.time()
    img = np.frombuffer(buf, np.uint8).reshape(H, W)[Y0:Y1, X0:X1] > 215   # white OSD glyph pixels only
    if prev is not None:
        d = float((img != prev).mean() * 100); diffs.append(d)   # % of glyph pixels that changed
        thr = max(3.0, 4 * float(np.median(diffs[-60:])))
        if d > thr and t - t_start > 3 and (not lat or t - last_flip > 0.7):
            last_flip = t
            lat.append(t - np.floor(t)); print(f"flip at {time.strftime('%H:%M:%S', time.localtime(t))}  +{lat[-1]*1000:.0f} ms  (diff {d:.1f})", flush=True)
    prev = img
p.kill()
l = np.array(lat); print(f"\nOSD flips: {len(l)}  median {np.median(l)*1000:.0f} ms  min {l.min()*1000:.0f}  max {l.max()*1000:.0f}")

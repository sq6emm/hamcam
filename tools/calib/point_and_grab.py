"""Point the rotator (rotctld P), wait until it has stopped, grab full-res frames via go2rtc restream."""
import os, socket, subprocess, sys, time
HOST, PORT = os.environ.get("ROTCTLD_HOST", "192.168.14.199"), int(os.environ.get("ROTCTLD_PORT", "4533"))   # from .env
target, out = float(sys.argv[1]), sys.argv[2]

def cmd(f, c):
    f.write((c + "\n").encode()); f.flush()

s = socket.create_connection((HOST, PORT), timeout=10); f = s.makefile("rwb")
def pos():
    cmd(f, "p"); az = float(f.readline()); f.readline(); return az
print(f"start az {pos():.1f}, commanding P {target:.0f} 0", flush=True)
cmd(f, f"P {target:.0f} 0"); print("reply:", f.readline().decode().strip(), flush=True)
t0 = time.time(); last = None; still_since = time.time()
while time.time() - t0 < 180:
    az = pos()
    if az != last: last, still_since = az, time.time()
    if time.time() - still_since > 4 and abs(((az - target + 540) % 360) - 180) <= 2: break
    time.sleep(0.25)
print(f"settled az {last:.1f} after {time.time()-t0:.0f}s", flush=True)
time.sleep(3)  # video latency + any mast swing
for i in range(3):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-rtsp_transport", "tcp", "-i", "rtsp://127.0.0.1:8557/main",
                    "-frames:v", "1", "-q:v", "2", f"{out}_{i}.jpg"], check=True)
    time.sleep(1)
print(f"final az {pos():.1f}", flush=True)

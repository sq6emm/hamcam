"""Passive monitor for the button test: log position changes and PD for N seconds (no commands that move anything)."""
import sys, time
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 600
from rot import pd, az
t0 = time.time(); last = None; last_pd = None; t_last_change = None
print(time.strftime("%H:%M:%S"), "monitor start", flush=True)
while time.time() - t0 < dur:
    try: a = az()
    except Exception: time.sleep(0.3); continue
    now = time.time()
    if a != last:
        if last is not None and (t_last_change is None or now - t_last_change > 1.5):
            print(time.strftime("%H:%M:%S"), f"MOVE START from {last}", flush=True)
        print(time.strftime("%H:%M:%S"), f"az {a}", flush=True); last = a; t_last_change = now
    elif t_last_change and now - t_last_change > 1.5:
        d = pd()
        print(time.strftime("%H:%M:%S"), f"STOPPED at {a}  PD {d}", flush=True); t_last_change = None
    time.sleep(0.2)
print(time.strftime("%H:%M:%S"), "monitor end", flush=True)

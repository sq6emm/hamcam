"""Passive monitor for the button test: log position changes and \\?PD for N seconds (no commands that move anything)."""
import socket, sys, time
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 600
s = socket.create_connection(("192.168.14.199", 4533), timeout=10); f = s.makefile("rwb")
def q(c, want):
    f.write((c + "\n").encode()); f.flush(); s.settimeout(1.5); out = []
    try:
        while True:
            l = f.readline().decode()
            if not l: break
            out.append(l.strip())
            if want in l: break
    except Exception: pass
    s.settimeout(10); return " ".join(out)
t0 = time.time(); last = None; last_pd = None; t_last_change = None
print(time.strftime("%H:%M:%S"), "monitor start", flush=True)
while time.time() - t0 < dur:
    r = q("w \\?AZ", "OKAZ")
    try: a = float(r.split("OKAZ")[1])
    except Exception: time.sleep(0.3); continue
    now = time.time()
    if a != last:
        if last is not None and (t_last_change is None or now - t_last_change > 1.5):
            print(time.strftime("%H:%M:%S"), f"MOVE START from {last}", flush=True)
        print(time.strftime("%H:%M:%S"), f"az {a}", flush=True); last = a; t_last_change = now
    elif t_last_change and now - t_last_change > 1.5:
        pd = q("w \\?PD", "OKPD").split("OKPD")[-1].strip()
        print(time.strftime("%H:%M:%S"), f"STOPPED at {a}  PD {pd}", flush=True); t_last_change = None
    time.sleep(0.2)
print(time.strftime("%H:%M:%S"), "monitor end", flush=True)

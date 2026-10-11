"""Live encoder diagnostics: poll \\?PD every 0.5 s, print e/i/k changes (read-only)."""
import socket, sys, time, re
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 240
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
t0 = time.time(); last = None
print(time.strftime("%H:%M:%S"), "encoder monitor start", flush=True)
while time.time() - t0 < dur:
    r = q("w \\?PD", "OKPD"); m = re.search(r"e(\d+) i(\d+) k(\d+)", r)
    if m:
        cur = tuple(int(x) for x in m.groups())
        if cur != last:
            if last: print(time.strftime("%H:%M:%S"), f"transitions +{cur[0]-last[0]:4d}  invalid +{cur[1]-last[1]:3d}  clicks +{cur[2]-last[2]:3d}   (total e{cur[0]} i{cur[1]} k{cur[2]})", flush=True)
            last = cur
    time.sleep(0.5)
print(time.strftime("%H:%M:%S"), "encoder monitor end", flush=True)

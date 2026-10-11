"""One watched move: log \\?AZ, send S if no progress for 4 s before reaching the target."""
import socket, sys, time
s = socket.create_connection(("192.168.14.199", 4533), timeout=10); f = s.makefile("rwb")
def q(c, want=None, wait=1.5):
    f.write((c + "\n").encode()); f.flush(); s.settimeout(wait); out = []
    try:
        while True:
            l = f.readline().decode()
            if not l: break
            out.append(l.strip())
            if (want and want in l) or (not want and l.strip()): break
    except Exception: pass
    s.settimeout(10); return " ".join(x for x in out if x)
def az():
    for _ in range(10):
        r = q("w \\?AZ", "OKAZ")
        if "OKAZ" in r: return float(r.split("OKAZ")[1])
        time.sleep(0.1)
for tg in [float(x) for x in sys.argv[1:]]:
    a0 = az(); t0 = time.time(); q(f"P {tg:.0f} 0", "RPRT"); last, t_last = a0, time.time(); trace = []
    while time.time() - t0 < 150:
        a = az(); t = time.time() - t0
        if a != last: last, t_last = a, time.time(); trace.append(f"{t:.1f}s:{a}")
        if abs(a - tg) >= 0.5 and time.time() - t_last > 4:
            print(f"  NO PROGRESS 4 s at {a} (target {tg}) -> S", q("S", "RPRT")); break
        if abs(a - tg) < 0.5 and time.time() - t_last > 2.5: break
        time.sleep(0.15)
    pd = q("w \\?PD", "OKPD").split("OKPD")[-1]
    print(f"{a0} -> {tg}: final {last} err {last - tg:+.1f} in {t_last - t0:.1f}s | {' '.join(trace)} | PD {pd}", flush=True)
    time.sleep(1.5)

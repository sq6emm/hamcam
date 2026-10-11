"""Firmware function test: log \\?AZ (decimal) while moving; optional explicit STOP after N seconds."""
import socket, sys, time
s = socket.create_connection(("192.168.14.199", 4533), timeout=10); f = s.makefile("rwb")
def q(c, want=None, wait=1.5):
    # rotctld raw replies span several lines: collect until the expected token (or a short timeout)
    f.write((c + "\n").encode()); f.flush()
    s.settimeout(wait); out = []
    try:
        while True:
            l = f.readline().decode()
            if not l: break
            out.append(l.strip())
            if want and want in l: break
            if not want and l.strip(): break
    except Exception:
        pass
    s.settimeout(10)
    return " ".join(x for x in out if x)
def az():
    for _ in range(10):
        r = q("w \\?AZ", "OKAZ")
        if "OKAZ" in r: return float(r.split("OKAZ")[1])
        time.sleep(0.1)
def run(target, stop_after=None, tmax=90):
    t0 = time.time(); log = []; print(f"-> P {target}" + (f", S after {stop_after}s" if stop_after else ""), q(f"P {target} 0", "RPRT"))
    stopped = False; last = None; still = time.time()
    while time.time() - t0 < tmax:
        a = az(); t = time.time() - t0; log.append((t, a))
        if stop_after and not stopped and t >= stop_after:
            print(f"   S at t={t:.2f}s az={a}:", q("S", "RPRT")); stopped = True; ts = t
        if a != last: last, still = a, time.time()
        if time.time() - still > 3: break
        time.sleep(0.2)
    # speed profile (deg/s over 1 s windows)
    prof = []
    for i in range(len(log)):
        j = next((k for k in range(i, len(log)) if log[k][0] - log[i][0] >= 1.0), None)
        if j: prof.append((log[i][0], (log[j][1] - log[i][1]) / (log[j][0] - log[i][0])))
    print("   t[s]  az     speed[deg/s]")
    for (t, a), (_, v) in zip(log[::5], prof[::5]): print(f"   {t:5.1f} {a:7.1f}  {v:+5.2f}")
    print(f"   final {log[-1][1]} after {log[-1][0]:.1f}s; half-degree values seen: {sorted(set(a for _, a in log if a is not None and (a * 2) % 2 == 1))[:6]}")
    if stopped:
        after = [a for t, a in log if t >= ts]
        print(f"   travel after S: {abs(after[-1] - after[0]):.1f} deg")
    return log
for arg in sys.argv[1:]:
    if ":" in arg: tg, sa = arg.split(":"); run(float(tg), float(sa))
    else: run(float(arg))
    time.sleep(2)
print("PD:", q("w \\?PD", "OKPD"))

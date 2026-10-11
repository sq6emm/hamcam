"""Drift / start-stop test: many short moves between 100 and 200 deg; per move log target, final, overshoot, coasting."""
import json, random, socket, sys, time
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
def pd():
    r = q("w \\?PD", "OKPD"); return r.split("OKPD")[1].strip() if "OKPD" in r else r
rnd = random.Random(42)
targets = [100]
pos = 100
while len(targets) < 46:
    step = rnd.choice([1, 2, 2, 3, 3, 4, 5, 6, 8, 10, 12, 15, 25, 40])
    t = pos + step * rnd.choice([-1, 1])
    if 100 <= t <= 200: targets.append(t); pos = t
targets += [200, 100, 200, 100, 122]
print("PD start:", pd(), flush=True)
moves = []
for tg in targets:
    a0 = az(); t0 = time.time(); q(f"P {tg} 0", "RPRT")
    log = [(0.0, a0)]; last = a0; still = time.time(); moving_seen = False; t_stop = None
    while time.time() - t0 < 120:
        a = az(); t = time.time() - t0; log.append((t, a))
        if a != last:
            last, still = a, time.time(); moving_seen = True
        if moving_seen or abs(a - tg) < 0.6:
            if time.time() - still > 2.5: break
        time.sleep(0.15)
    final = log[-1][1]
    # first time the reading reached its final value -> later changes would be coasting (already included in final)
    t_final = next(t for t, a in log if a == final)
    vmax = max((abs(log[i+1][1] - log[i][1]) / max(log[i+1][0] - log[i][0], 1e-3) for i in range(len(log) - 1)), default=0)
    m = {"from": a0, "target": tg, "final": final, "err": round(final - tg, 2), "t_reach": round(t_final, 1), "vmax": round(vmax, 2)}
    moves.append(m); print(json.dumps(m), flush=True)
print("PD end:", pd(), flush=True)
json.dump(moves, open("/out/drift_moves.json", "w"), indent=1)
errs = [m["err"] for m in moves]
print(f"moves {len(moves)}: err min {min(errs):+.1f} max {max(errs):+.1f}, |err|>0.5: {sum(1 for e in errs if abs(e) > 0.5)}, total travel {sum(abs(m['final'] - m['from']) for m in moves):.0f} deg", flush=True)

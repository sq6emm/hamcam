"""One watched move: log AR, send S if no progress for 4 s before reaching the target."""
import sys, time
from rot import q, az, pd
for tg in [float(x) for x in sys.argv[1:]]:
    a0 = az(); t0 = time.time(); q(f"P {tg:.0f} 0", "RPRT"); last, t_last = a0, time.time(); trace = []
    while time.time() - t0 < 150:
        a = az(); t = time.time() - t0
        if a != last: last, t_last = a, time.time(); trace.append(f"{t:.1f}s:{a}")
        if abs(a - tg) >= 0.5 and time.time() - t_last > 4:
            print(f"  NO PROGRESS 4 s at {a} (target {tg}) -> S", q("S", "RPRT")); break
        if abs(a - tg) < 0.5 and time.time() - t_last > 2.5: break
        time.sleep(0.15)
    diag = pd()
    print(f"{a0} -> {tg}: final {last} err {last - tg:+.1f} in {t_last - t0:.1f}s | {' '.join(trace)} | PD {diag}", flush=True)
    time.sleep(1.5)

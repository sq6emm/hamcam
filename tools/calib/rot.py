"""rotctld helper for the SQ6EMM rotor firmware (Easycomm III, rotctld -m 204): raw controller commands through 'w'.

az()  raw position from AR: -30..390 in 0.5 deg steps (no wrap at 360, unlike 'p')
pd()  PD diagnostics: a<pulses accepted>,r<rejected>,c<coasting>,h<reversal holds>,s<stalls>,t<timeouts>,p<pwm>,f<Hz>
gs()  GS status bits: 1 idle, 2 moving, 4 on target, 8 error;  ge() GE error bits (0 = none)
Calibration is 'w CW7,<deg>' on the controller (0-359.9 keeps the current turn) - none of these tools send it.
"""
import os, socket, time

ADDR = (os.environ.get("ROTCTLD_HOST", "192.168.14.199"), int(os.environ.get("ROTCTLD_PORT", "4533")))
s = socket.create_connection(ADDR, timeout=10); f = s.makefile("rwb")


def q(c, want=None, wait=1.5):
    # rotctld raw replies come with empty lines around them: collect until the expected token (or a short timeout)
    if want is None and c.startswith("w "):
        want = c[2:4]                                # Easycomm replies echo the command: "w AR" -> "AR327.0"
    f.write((c + "\n").encode()); f.flush(); s.settimeout(wait); out = []
    try:
        while True:
            l = f.readline().decode()
            if not l: break
            l = l.strip()
            if not l: continue
            out.append(l)
            if (want and l.startswith(want)) or not want or l.startswith("RPRT -"): break
    except Exception: pass
    s.settimeout(10); return " ".join(out)


def _val(cmd):
    for _ in range(10):
        r = q(f"w {cmd}")
        if r.startswith(cmd): return r[len(cmd):]
        time.sleep(0.1)
    raise RuntimeError(f"no {cmd} reply")


def az(): return float(_val("AR"))
def pd(): return _val("PD")
def gs(): return int(_val("GS"))
def ge(): return int(_val("GE"))
def moving(): return bool(gs() & 2)

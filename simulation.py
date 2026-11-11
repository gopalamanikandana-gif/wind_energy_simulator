"""Wind energy harvesting + supercapacitor + power-management simulation (pure Python, no dependencies)."""
import math
import random
from collections import deque

DT = 60  # seconds simulated per step (1 minute)
MODES = ("ACTIVE", "LOW POWER", "DEEP SLEEP")
LOAD_KEY = {"ACTIVE": "p_active", "LOW POWER": "p_low", "DEEP SLEEP": "p_sleep"}
TX_EVERY = {"ACTIVE": 5, "LOW POWER": 30}  # minutes between transmissions; none in deep sleep

# key, label, min, max, default, unit
SCHEMA = [
    ("mean_wind", "Mean wind speed", 1, 12, 5.5, "m/s"),
    ("rho", "Air density (rho)", 1.0, 1.4, 1.225, "kg/m3"),
    ("area", "Rotor swept area (A)", 0.005, 0.5, 0.012, "m2"),
    ("cp", "Power coefficient (Cp)", 0.1, 0.59, 0.35, ""),
    ("eta", "Generator efficiency (eta)", 0.5, 1.0, 0.85, ""),
    ("cut_in", "Cut-in speed", 1, 6, 3.0, "m/s"),
    ("cut_out", "Cut-out speed", 15, 30, 20.0, "m/s"),
    ("rated_power", "Rated power limit", 0.5, 50, 5.0, "W"),
    ("conv_eff", "Charger efficiency", 0.5, 1.0, 0.9, ""),
    ("capacitance", "Supercapacitor C", 10, 500, 100, "F"),
    ("vmax", "Maximum voltage", 2.7, 10, 5.4, "V"),
    ("vmin", "Minimum usable voltage", 0.5, 5, 2.0, "V"),
    ("p_active", "Active-mode load", 0.01, 5, 0.4, "W"),
    ("p_low", "Low-power-mode load", 0.001, 1, 0.05, "W"),
    ("p_sleep", "Deep-sleep load", 0.0001, 0.1, 0.002, "W"),
    ("leak_w", "Capacitor leakage", 0, 0.1, 0.003, "W"),
    ("tx_j", "Energy per transmission", 0.1, 50, 3.0, "J"),
    ("link_prob", "Radio link success probability", 0.5, 1.0, 0.95, ""),
    ("active_on", "Enter ACTIVE at charge >=", 30, 95, 60, "%"),
    ("active_off", "Leave ACTIVE below", 10, 90, 40, "%"),
    ("sleep_off", "Leave DEEP SLEEP at charge >=", 5, 60, 25, "%"),
    ("sleep_on", "Enter DEEP SLEEP below", 1, 50, 15, "%"),
]
DEFAULTS = {k: d for k, _, _, _, d, _ in SCHEMA}


def validate(raw):
    """Return (clean_params, errors). Unknown keys are ignored."""
    clean, errors = dict(DEFAULTS), []
    for key, label, lo, hi, _, _ in SCHEMA:
        if key not in raw:
            continue
        try:
            v = float(raw[key])
            if math.isnan(v) or math.isinf(v):
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{label}: must be a number")
            continue
        if not lo <= v <= hi:
            errors.append(f"{label}: must be between {lo} and {hi}")
        clean[key] = v
    if not errors:
        c = clean
        if c["vmin"] >= c["vmax"]:
            errors.append("Minimum voltage must be below maximum voltage")
            errors.append("Cut-in speed must be below cut-out speed")
        if not c["sleep_on"] < c["sleep_off"] < c["active_off"] < c["active_on"]:
            errors.append("Thresholds must satisfy: sleep-enter < sleep-exit < active-leave < active-enter")
    return clean, errors


def wind_power(v, p):
    """P = 0.5*rho*A*Cp*eta*v^3, zero outside [cut_in, cut_out), capped at rated power."""
    if v < p["cut_in"] or v >= p["cut_out"]:
        return 0.0
    return min(0.5 * p["rho"] * p["area"] * p["cp"] * p["eta"] * v ** 3, p["rated_power"])


class Simulator:
    def __init__(self, params=None, seed=1):
        self.p = dict(DEFAULTS)
        self.p.update(params or {})
        self.seed = seed
        self.reset()

    def reset(self):
        p = self.p
        self.emax = 0.5 * p["capacitance"] * p["vmax"] ** 2
        self.emin = 0.5 * p["capacitance"] * p["vmin"] ** 2
        self.E = self.emin + 0.5 * (self.emax - self.emin)  # start at 50 % charge
        self.E0 = self.E
        self.n = 0
        self.mode = "LOW POWER"
        self.ar = 0.0
        self.manual = None
        self.wr = random.Random(self.seed)
        self.tr = random.Random(self.seed + 1)
        self.harv = self.curt = self.used = 0.0
        self.up = self.att = self.ok = 0
        self.hours, self.recent = [], deque(maxlen=720)
        self.last = None
        self.last_tx = "none yet"

    def new_wind(self):
        """New random wind regime (seed + mean speed); energy state is kept."""
        r = random.Random()
        self.seed = r.randint(1, 10 ** 6)
        self.p["mean_wind"] = round(r.uniform(3.5, 8.0), 1)
        self.wr = random.Random(self.seed)
        self.ar = 0.0

    def _pct(self, E):
        return 100.0 * (E - self.emin) / (self.emax - self.emin)

    def _wind(self, hour):
        self.ar = 0.98 * self.ar + self.wr.gauss(0, 0.25)  # persistent turbulence, std ~1.25 m/s
        if self.manual is not None:
            return self.manual
        base = self.p["mean_wind"] + 1.5 * math.sin(2 * math.pi * (hour - 14) / 24)  # afternoon peak
        return max(0.0, base + self.ar)

    def _next_mode(self, pct):
        p, m = self.p, self.mode
        if m == "DEEP SLEEP" and pct >= p["sleep_off"]:
            m = "LOW POWER"
        if m == "LOW POWER":
            if pct >= p["active_on"]:
                m = "ACTIVE"
            elif pct < p["sleep_on"]:
                m = "DEEP SLEEP"
        elif m == "ACTIVE" and pct < p["active_off"]:
            m = "LOW POWER"
        return m

    def step(self):
        p, n = self.p, self.n
        hour = (n / 60.0) % 24
        v = self._wind(hour)
        gen = wind_power(v, p)
        harvested = gen * DT * p["conv_eff"]
        E = self.E + harvested
        curtailed = max(0.0, E - self.emax)  # storage full: surplus is spilled
        E -= curtailed
        self.mode = self._next_mode(self._pct(E))
        want = (p[LOAD_KEY[self.mode]] + p["leak_w"]) * DT
        avail = max(0.0, E - self.emin)
        used = min(want, avail)
        if want > avail:  # brown-out: node cannot be powered
            self.mode = "DEEP SLEEP"
        E -= used
        tx = None
        if self.mode in TX_EVERY and n % TX_EVERY[self.mode] == 0:
            self.att += 1
            if E - self.emin >= p["tx_j"]:
                E -= p["tx_j"]
                used += p["tx_j"]
                tx = self.tr.random() < p["link_prob"]
            else:
                tx = False
            self.ok += bool(tx)
        temp = 24 + 7 * math.sin(2 * math.pi * (hour - 9) / 24) + self.tr.gauss(0, 0.3)
        hum = min(100.0, max(10.0, 75 - 1.8 * (temp - 24) + self.tr.gauss(0, 1.0)))
        if tx is not None:
            self.last_tx = f"{'OK' if tx else 'FAILED'}: {temp:.1f} °C, {hum:.0f} % RH"
        self.E = E
        self.harv += harvested
        self.curt += curtailed
        self.used += used
        self.up += self.mode != "DEEP SLEEP"
        self._log(v, gen, used, harvested, curtailed, tx)
        self.last = dict(v=v, gen=gen, used=used, temp=temp, hum=hum)
        self.n += 1

    def _log(self, v, gen, used, harvested, curtailed, tx):
        i = self.n // 60
        if len(self.hours) <= i:
            self.hours.append({k: 0.0 for k in ("steps", "wind", "gen", "cons", "harv", "used", "curt",
                                                 "up", "act", "low", "sleep", "att", "ok", "pct")})
        h = self.hours[i]
        h["steps"] += 1; h["wind"] += v; h["gen"] += gen; h["cons"] += used / DT
        h["harv"] += harvested; h["used"] += used; h["curt"] += curtailed
        h["up"] += self.mode != "DEEP SLEEP"
        h["act"] += self.mode == "ACTIVE"; h["low"] += self.mode == "LOW POWER"; h["sleep"] += self.mode == "DEEP SLEEP"
        if tx is not None:
            h["att"] += 1; h["ok"] += bool(tx)
        h["pct"] = self._pct(self.E)
        self.recent.append((self.n, v, gen * p_eff(self.p), used / DT, self._pct(self.E)))

    def run(self, steps):
        for _ in range(steps):
            self.step()

    def snapshot(self):
        l = self.last or dict(v=0.0, gen=0.0, used=0.0, temp=0.0, hum=0.0)
        n = max(self.n, 1)
        t = self.n
        return dict(
            time=f"Day {t // 1440 + 1}, {t % 1440 // 60:02d}:{t % 60:02d}", steps=self.n,
            wind=round(l["v"], 2), gen_w=round(l["gen"], 3), harvest_w=round(l["gen"] * self.p["conv_eff"], 3),
            energy_j=round(self.E, 2), energy_max_j=round(self.emax, 1), energy_min_j=round(self.emin, 1),
            voltage=round(math.sqrt(2 * self.E / self.p["capacitance"]), 3), charge_pct=round(self._pct(self.E), 1),
            cons_w=round(l["used"] / DT, 4), mode=self.mode, uptime_pct=round(100 * self.up / n, 1),
            tx_attempts=self.att, tx_ok=self.ok, tx_rate=round(100 * self.ok / self.att, 1) if self.att else 0.0,
            temp=round(l["temp"], 1), hum=round(l["hum"], 1), last_tx=self.last_tx,
            harvested_j=round(self.harv, 1), consumed_j=round(self.used, 1), curtailed_j=round(self.curt, 1),
            balance_error_j=abs(self.E0 + self.harv - self.curt - self.used - self.E),
            manual=self.manual, mean_wind=self.p["mean_wind"])

    def chart(self, max_points=120):
        r = list(self.recent)
        stride = max(1, math.ceil(len(r) / max_points))
        r = r[::stride]
        return dict(labels=[f"{x[0] // 60 % 24:02d}:{x[0] % 60:02d}" for x in r], wind=[round(x[1], 2) for x in r],
                    gen=[round(x[2], 3) for x in r], cons=[round(x[3], 4) for x in r], pct=[round(x[4], 1) for x in r])

    def hourly(self):
        out = []
        for h in self.hours:
            s = h["steps"]
            out.append(dict(wind=round(h["wind"] / s, 2), gen=round(h["gen"] * self.p["conv_eff"] / s, 3),
                            cons=round(h["cons"] / s, 4), pct=round(h["pct"], 1)))
        return out

    def daily(self):
        out = []
        for d in range(0, len(self.hours), 24):
            hs = self.hours[d:d + 24]
            s = lambda k: sum(x[k] for x in hs)
            st = s("steps")
            out.append(dict(day=d // 24 + 1, uptime=round(100 * s("up") / st, 1), attempts=int(s("att")), ok=int(s("ok")),
                            tx_rate=round(100 * s("ok") / s("att"), 1) if s("att") else 0.0,
                            harvested_j=round(s("harv")), consumed_j=round(s("used")), curtailed_j=round(s("curt")),
                            avg_wind=round(s("wind") / st, 2), active_pct=round(100 * s("act") / st, 1),
                            low_pct=round(100 * s("low") / st, 1), sleep_pct=round(100 * s("sleep") / st, 1),
                            end_pct=round(hs[-1]["pct"], 1)))
        return out


def p_eff(p):
    return p["conv_eff"]


def run_days(params, seed, days=14):
    sim = Simulator(params, seed)
    sim.run(days * 1440)
    return sim


if __name__ == "__main__":
    s = run_days(DEFAULTS, 1)
    snap = s.snapshot()
    print({k: snap[k] for k in ("uptime_pct", "tx_rate", "tx_attempts", "harvested_j", "consumed_j", "curtailed_j", "balance_error_j")})
    for d in s.daily():
        print(d)

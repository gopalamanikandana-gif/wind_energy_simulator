# Wind Energy Harvesting and Smart Power Management Simulator

A wind-powered IoT sensor node: **wind turbine -> charger -> supercapacitor -> power manager -> sensor + radio**.
Pure Python simulation (1-minute time step), Flask JSON API, Chart.js dashboard. No hardware, ML, auth or external APIs.

## Install and run (Windows, VS Code)
```
cd wind_energy_simulator
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000. (If PowerShell blocks activation: `Set-ExecutionPolicy -Scope Process Bypass`.)
Chart.js loads from a CDN, so the browser needs internet once. For offline use, download `chart.umd.min.js` into `static/` and change the `<script>` tag in `templates/index.html`.

## Structure
```
wind_energy_simulator/
  app.py            Flask routes (JSON API)
  simulation.py     Physics, storage, power manager, statistics
  requirements.txt
  README.md
  templates/index.html
  static/style.css, static/script.js
```

## Formulas
- Wind power: `P = 0.5 * rho * A * Cp * eta * v^3` (rho 1.225 kg/m3, A 0.012 m2, Cp 0.35, eta 0.85).
  P = 0 below cut-in (3 m/s) and at/above cut-out (20 m/s); capped at rated power (5 W) up to cut-out.
- Harvested energy per step: `E_in = P * 60 s * charger_eff (0.9)`.
- Supercapacitor: `E = 0.5 * C * V^2` (100 F, 2.0-5.4 V -> 200 J to 1458 J). `V = sqrt(2E/C)`.
  Charge % = `(E - E_min) / (E_max - E_min)`. Surplus above E_max is spilled (recorded as "curtailed").
- Energy conservation (checked every run): `E_end = E_start + harvested - spilled - consumed`; the error shown is about 1e-7 J (floating point).
- Power manager (hysteresis, % of usable charge): LOW -> ACTIVE at >= 60, ACTIVE -> LOW below 40, any -> DEEP SLEEP below 15, DEEP SLEEP -> LOW at >= 25.
  Loads: ACTIVE 0.4 W, LOW 0.05 W, SLEEP 0.002 W, plus 3 mW leakage. If storage cannot supply a step, the node browns out into DEEP SLEEP.
- Radio: packet every 5 min (ACTIVE) or 30 min (LOW), costing 3 J; none in DEEP SLEEP. It fails if stored energy is too low, or with 5 % link-loss probability (seeded random generator).
- Wind: mean 5.5 m/s + daily cycle (afternoon peak) + correlated turbulence (seeded). Temperature/humidity follow a daily cycle with small noise.
- Uptime % = share of time not in DEEP SLEEP. Tx success % = delivered / attempted.

## Sample result (defaults, seed 1, 14 days)
| Metric | Value |
|---|---|
| System uptime | 99.1 % (days 2, 10, 12 had 3.8-4.7 % deep sleep) |
| Transmissions | 2790 delivered / 2937 attempted = 95.0 % |
| Energy harvested | 497.2 kJ |
| Energy consumed | 358.7 kJ |
| Spilled (storage full) | 138.6 kJ |
| Conservation error | 1.1e-7 J |

Spot values: 6 m/s -> 0.47 W; 11 m/s -> 2.91 W; the 5 W rated cap is reached near 13 m/s; below 3 m/s -> 0 W.

## Testing
1. Dashboard -> Start: cards and charts update each second (default 10 simulated minutes per second).
2. Tick "Manual wind", set 0 m/s, speed 1 h/s: charge falls, mode goes ACTIVE -> LOW POWER -> DEEP SLEEP. Raise wind to 10 m/s: it recovers LOW POWER at 25 %, ACTIVE at 60 % (hysteresis).
3. Pause / Reset / New Wind Conditions buttons act immediately.
4. Analytics -> Simulate 14 days: 4 charts, daily table, conservation error ~1e-7 J.
5. Settings: enter vmin 9 or swapped thresholds -> an error message appears and nothing changes.
6. `python simulation.py` prints a 14-day text report.

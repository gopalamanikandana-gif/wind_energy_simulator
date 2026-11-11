"""Flask backend for the Wind Energy Harvesting and Smart Power Management Simulator."""
import threading
from flask import Flask, jsonify, render_template, request
import simulation as sim_mod

app = Flask(__name__)
lock = threading.Lock()
SIM = sim_mod.Simulator(seed=1)


def payload():
    return dict(state=SIM.snapshot(), chart=SIM.chart())


def body():
    return request.get_json(silent=True) or {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def state():
    with lock:
        return jsonify(payload())


@app.route("/api/step", methods=["POST"])
def step():
    try:
        n = int(body().get("steps", 1))
    except (TypeError, ValueError):
        return jsonify(errors=["steps must be an integer"]), 400
    if not 1 <= n <= 1440:
        return jsonify(errors=["steps must be between 1 and 1440"]), 400
    with lock:
        SIM.run(n)
        return jsonify(payload())


@app.route("/api/reset", methods=["POST"])
def reset():
    with lock:
        SIM.reset()
        return jsonify(payload())


@app.route("/api/new_wind", methods=["POST"])
def new_wind():
    with lock:
        SIM.new_wind()
        return jsonify(payload())


@app.route("/api/wind", methods=["POST"])
def wind():
    b = body()
    with lock:
        if not b.get("manual"):
            SIM.manual = None
        else:
            try:
                v = float(b.get("speed"))
            except (TypeError, ValueError):
                return jsonify(errors=["Wind speed must be a number"]), 400
            if not 0 <= v <= 30:
                return jsonify(errors=["Wind speed must be between 0 and 30 m/s"]), 400
            SIM.manual = v
        return jsonify(payload())


@app.route("/api/config", methods=["GET", "POST"])
def config():
    global SIM
    with lock:
        if request.method == "GET":
            schema = [dict(key=k, label=l, min=lo, max=hi, unit=u) for k, l, lo, hi, _, u in sim_mod.SCHEMA]
            return jsonify(schema=schema, values=SIM.p)
        params, errors = sim_mod.validate({**SIM.p, **body()})
        if errors:
            return jsonify(errors=errors), 400
        SIM = sim_mod.Simulator(params, SIM.seed)  # electrical sizes changed -> restart
        return jsonify(payload())


@app.route("/api/analytics", methods=["POST"])
def analytics():
    with lock:
        run = sim_mod.run_days(SIM.p, SIM.seed, 14)  # independent copy, live sim untouched
        s = run.snapshot()
        return jsonify(hourly=run.hourly(), daily=run.daily(), summary={k: s[k] for k in (
            "uptime_pct", "tx_rate", "tx_attempts", "tx_ok", "harvested_j", "consumed_j", "curtailed_j", "balance_error_j")})


if __name__ == "__main__":
    app.run(debug=False, port=5000)

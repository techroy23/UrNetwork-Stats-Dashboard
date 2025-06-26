# ----------------------------------------
# Imports & Environment Setup
# ----------------------------------------
import os
import time
import datetime
import requests
from dotenv import load_dotenv, dotenv_values
from flask import (
    Flask, request, render_template_string,
    redirect, url_for, flash, current_app
)
from flask_sqlalchemy import SQLAlchemy
from flask_apscheduler import APScheduler

# Load .env variables into environment
load_dotenv()

API_BASE = "https://api.bringyour.com"
UR_USER  = os.getenv("UR_USER")
UR_PASS  = os.getenv("UR_PASS")
UR_JWT   = "UR_JWT"

# ----------------------------------------
# Flask & Extensions Configuration
# ----------------------------------------
class Config:
    SCHEDULER_API_ENABLED         = True
    SQLALCHEMY_DATABASE_URI       = "sqlite:///transfer_stats.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY                    = os.urandom(24)

app       = Flask(__name__)
app.config.from_object(Config)

# Initialize database and scheduler
db        = SQLAlchemy(app)
scheduler = APScheduler()
scheduler.init_app(app)

# ----------------------------------------
# Database Model
# ----------------------------------------
class Stats(db.Model):
    """
    Represents a snapshot of paid vs unpaid bytes at a given timestamp.
    Columns:
      - id           : Primary key
      - timestamp    : Auto-generated timestamp of the record
      - paid_bytes   : Total paid bytes provided
      - paid_gb      : Paid bytes converted to gigabytes
      - unpaid_bytes : Total unpaid bytes provided
      - unpaid_gb    : Unpaid bytes converted to gigabytes
    """
    id           = db.Column(db.Integer,   primary_key=True)
    timestamp    = db.Column(db.DateTime,  server_default=db.func.now())
    paid_bytes   = db.Column(db.BigInteger, nullable=False)
    paid_gb      = db.Column(db.Float,      nullable=False)
    unpaid_bytes = db.Column(db.BigInteger, nullable=False)
    unpaid_gb    = db.Column(db.Float,      nullable=False)

# ----------------------------------------
# Environment Token Management
# ----------------------------------------
def save_env_token(token: str):
    vals = dotenv_values(".env")
    vals["UR_JWT"] = token
    with open(".env", "w") as f:
        for k, v in vals.items():
            f.write(f"{k}={v}\n")


# ----------------------------------------
# HTTP Helper with Retries
# ----------------------------------------
def request_with_retry(
    method: str,
    url: str,
    retries: int = 3,
    backoff: int = 30,
    timeout: int = 60,
    **kwargs
):
    """
    Issue an HTTP request and retry on failure.
    - method : HTTP verb (get, post, etc.)
    - url    : Endpoint to hit
    - retries: Number of retry attempts
    - backoff: Seconds to wait before retry
    - timeout: Request timeout in seconds
    Raises:
      - RuntimeError if all attempts fail.
    """
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_exc = e
            current_app.logger.warning(
                f"[{method.upper()} {url}] attempt {attempt}/{retries} failed: {e}"
            )
            if attempt < retries:
                time.sleep(backoff)
    raise RuntimeError(f"All {retries} attempts to {method.upper()} {url} failed: {last_exc}")

# ----------------------------------------
# Authentication & JWT Handling
# ----------------------------------------
def login_check():
    """
    Ensure we have a valid JWT token. If stored token is invalid or missing,
    log in with username and password to obtain a fresh token.
    Returns:
      - A valid JWT token string.
    Raises:
      - RuntimeError if login fails.
    """
    token = os.getenv("UR_JWT")
    if token:
        try:
            resp = request_with_retry(
                "get",
                f"{API_BASE}/transfer/stats",
                headers={"Authorization": f"Bearer {token}", "Accept": "*/*"}
            )
            body = resp.json()
            if "not authorized" not in str(body.get("message","")).lower():
                return token
        except Exception:
            current_app.logger.info("Re-acquiring JWT (stored one invalid or stats check failed)")

    resp = request_with_retry(
        "post",
        f"{API_BASE}/auth/login-with-password",
        headers={"Content-Type": "application/json"},
        json={"user_auth": UR_USER, "password": UR_PASS},
    )
    data = resp.json()
    token = data.get("network", {}).get("by_jwt")
    if not token:
        err = data.get("message") or data.get("error") or str(data)
        raise RuntimeError(f"Login failed: {err}")
    save_env_token(token)
    return token

# ----------------------------------------
# Transfer Statistics Fetching
# ----------------------------------------
def fetch_transfer_stats(jwt_token: str):
    """
    Retrieve the latest transfer statistics using the provided JWT.
    Returns:
      - A dict with keys: paid_bytes, paid_gb, unpaid_bytes, unpaid_gb.
    """
    headers = {"Authorization": f"Bearer {jwt_token}", "Accept": "*/*"}
    resp = request_with_retry("get", f"{API_BASE}/transfer/stats", headers=headers)
    d = resp.json()
    paid   = d.get("paid_bytes_provided",   0)
    unpaid = d.get("unpaid_bytes_provided", 0)
    return {
        "paid_bytes":   paid,
        "paid_gb":      paid   / 1e9,
        "unpaid_bytes": unpaid,
        "unpaid_gb":    unpaid / 1e9
    }

# ----------------------------------------
# Scheduler Utilities
# ----------------------------------------
def get_next_quarter(dt=None):
    """
    Compute the next 15-minute boundary from now (or provided dt).
    Returns:
      - A datetime object aligned to the next quarter-hour.
    """
    dt = dt or datetime.datetime.now()
    q  = (dt.minute // 15 + 1) * 15
    if q == 60:
        return (dt.replace(minute=0, second=0, microsecond=0)
                + datetime.timedelta(hours=1))
    return dt.replace(minute=0, second=0, microsecond=0) \
           + datetime.timedelta(minutes=q)

# ----------------------------------------
# Scheduled Task: Periodic Logging
# ----------------------------------------
@scheduler.task(id="log_stats", trigger="cron", minute="0,15,30,45")
def log_stats():
    """
    Runs every quarter-hour:
      1. Ensures valid JWT.
      2. Fetches transfer stats.
      3. Persists a new Stats record in the database.
    """
    with app.app_context():
        try:
            token = login_check()
            stats = fetch_transfer_stats(token)
            entry = Stats(
                paid_bytes   = stats["paid_bytes"],
                paid_gb      = stats["paid_gb"],
                unpaid_bytes = stats["unpaid_bytes"],
                unpaid_gb    = stats["unpaid_gb"]
            )
            db.session.add(entry)
            db.session.commit()
            current_app.logger.info(f"Logged @ {entry.timestamp}")
        except Exception as e:
            current_app.logger.error(f"log_stats aborted: {e}")

# ----------------------------------------
# HTML Template
# ----------------------------------------
TEMPLATE = """
<!doctype html>
<html lang="en" data-bs-theme="{{ 'dark' if dark else 'light' }}">
<head>
  <meta charset="utf-8">
  <title>Transfer Stats</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/css/bootstrap.min.css"
        rel="stylesheet">
</head>
<body>

<!-- DARK/LIGHT HEADER -->
<div class="w-100 bg-dark text-white py-2">
  <div class="container d-flex justify-content-between">
    <div>Next fetch: {{ next_fetch_str }}</div>
    <div>Countdown: <span id="countdown">--:--:--</span></div>
  </div>
</div>

<div class="container py-4">

  <!-- TITLE + TOGGLE + BUTTONS -->
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h1 class="mb-0">Transfer Stats History</h1>
    <div class="d-flex align-items-center">
      <!-- Dark/Light Toggle -->
      <div class="form-check form-switch me-3">
        <input class="form-check-input" type="checkbox" id="darkSwitch"
               {{ 'checked' if dark else '' }}>
        <label class="form-check-label {{ 'text-white' if dark else 'text-dark' }}"
               for="darkSwitch">
          Dark Mode
        </label>
      </div>

      <!-- Fetch Now -->
      <form method="post" action="{{ url_for('trigger_fetch') }}?dark={{ '1' if dark else '0' }}"
            class="me-2">
        <button type="submit" class="btn btn-primary">Fetch Now</button>
      </form>

      <!-- Clear DB -->
      <form method="post" action="{{ url_for('clear_db') }}?dark={{ '1' if dark else '0' }}"
            onsubmit="return confirm('Are you sure you want to clear all records?');">
        <button type="submit" class="btn btn-danger">Clear DB</button>
      </form>
    </div>
  </div>

  {% with msgs = get_flashed_messages() %}
    {% if msgs %}
      <div class="alert alert-warning">{{ msgs[0] }}</div>
    {% endif %}
  {% endwith %}

  <!-- TABLE (newest first) -->
  <table class="table table-striped">
    <thead>
      <tr>
        <th title="Time the data was recorded">🗓️ Timestamp</th>
        <th title="Amount of paid traffic in gigabytes">💵 Paid (GB)</th>
        <th title="Total unpaid data in bytes">📦 Unpaid Bytes</th>
        <th title="Change from previous unpaid bytes">➕ Change Bytes</th>
        <th title="Total unpaid data in gigabytes">📦 Unpaid (GB)</th>
        <th title="Change from previous unpaid GB">➕ Change (GB)</th>
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
      <tr>
        <td>{{ row.ts_str }}</td>
        <td>{{ "%.3f"|format(row.e.paid_gb) }}</td>
        <td>{{ "{:,}".format(row.e.unpaid_bytes) }}</td>
        <td>
          {% if row.delta_bytes is not none %}
            {{ "{:,}".format(row.delta_bytes) }}
          {% else %}N/A{% endif %}
        </td>
        <td>{{ "%.3f"|format(row.e.unpaid_gb) }}</td>
        <td>
          {% if row.delta_gb is not none %}
            {{ "%.3f"|format(row.delta_gb) }}
          {% else %}N/A{% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<!-- TOGGLE + COUNTDOWN SCRIPTS -->
<script>
  // Theme toggle: flips ?dark= and reloads
  document.getElementById('darkSwitch').addEventListener('change', function(){
    const darkVal = this.checked ? '1' : '0';
    const url    = new URL(window.location.href);
    url.searchParams.set('dark', darkVal);
    window.location.href = url.toString();
  });

  // Countdown + auto-refresh (no POST)
  const target = new Date({{ next_fetch_ts }});
  let autoDone = false;
  function updateTimer(){
    const now  = new Date(),
          diff = target - now,
          span = document.getElementById('countdown');
    if(diff <= 0){
      span.innerHTML =
        '<span class="spinner-border spinner-border-sm text-white" role="status"></span> Refreshing...';
      if(!autoDone){
        autoDone = true;
        window.location.reload();
      }
      return;
    }
    const h = String(Math.floor(diff/3600000 )).padStart(2,'0'),
          m = String(Math.floor((diff%3600000)/60000)).padStart(2,'0'),
          s = String(Math.floor((diff%60000)/1000 )).padStart(2,'0');
    span.textContent = `${h}:${m}:${s}`;
  }
  updateTimer();
  setInterval(updateTimer, 1000);
</script>
</body>
</html>
"""

# ----------------------------------------
# Flask Routes & Views
# ----------------------------------------
@app.route("/")
def index():
    """
    Render the stats history page.
    - toggles dark mode based on query param
    - computes deltas between consecutive entries
    - calculates next scheduled-fetch timestamp
    """
    dark    = request.args.get('dark', '0') == '1'
    entries = Stats.query.order_by(Stats.timestamp.desc()).all()
    local_tz = datetime.datetime.now().astimezone().tzinfo
    rows = []
    for i, e in enumerate(entries):
        utc_dt   = e.timestamp.replace(tzinfo=datetime.timezone.utc)
        local_dt = utc_dt.astimezone(local_tz)
        ts_str   = local_dt.strftime("%m/%d/%Y %I:%M:%S %p")

        if i < len(entries) - 1:
            nxt     = entries[i+1]
            delta_b = e.unpaid_bytes - nxt.unpaid_bytes
            delta_g = e.unpaid_gb    - nxt.unpaid_gb
        else:
            delta_b = delta_g = None

        rows.append({
            "e": e,
            "ts_str": ts_str,
            "delta_bytes": delta_b,
            "delta_gb":   delta_g
        })

    nxt = get_next_quarter()
    return render_template_string(
        TEMPLATE,
        dark            = dark,
        rows            = rows,
        next_fetch_str  = nxt.strftime("%m/%d/%Y %I:%M %p"),
        next_fetch_ts   = int(nxt.timestamp() * 1000)
    )

@app.route("/trigger", methods=["POST"])
def trigger_fetch():
    """
    Manually fetch latest stats and redirect back to index.
    Flash an error on failure.
    """
    dark = request.args.get('dark', '0')
    try:
        token = login_check()
        stats = fetch_transfer_stats(token)
        entry = Stats(
            paid_bytes   = stats["paid_bytes"],
            paid_gb      = stats["paid_gb"],
            unpaid_bytes = stats["unpaid_bytes"],
            unpaid_gb    = stats["unpaid_gb"]
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f"Manual fetch aborted: {e}")
        flash("Unable to fetch stats; check logs.")
    return redirect(url_for('index', dark=dark))

@app.route("/clear", methods=["POST"])
def clear_db():
    """
    Delete all Stats records and redirect back to index.
    """
    dark = request.args.get('dark', '0')
    Stats.query.delete()
    db.session.commit()
    flash("All records cleared.")
    return redirect(url_for('index', dark=dark))

# ----------------------------------------
# Application Entry Point
# ----------------------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    scheduler.start()
    app.run(host="0.0.0.0", port=3000, debug=False)

#!/usr/bin/env python3
"""Race the Sun replacement server.

Serves the two endpoints the game needs:
  - POST /LatestNews/News.php  (monkeytech.flippfly.com)  — news banner
  - POST /parse/functions/get_current_server_info (tech.flippfly.com) — daily world info

All other requests are logged and given an empty 200 response so we can
discover any endpoints we haven't seen yet.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging
import os
import sys
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PORT = int(os.environ.get("PORT", 8080))
LOG_DIR = os.environ.get("LOG_DIR", os.path.join(os.path.dirname(__file__), "logs"))
NEWS_FILE = os.environ.get("NEWS_FILE", os.path.join(os.path.dirname(__file__), "news.json"))
MAX_BODY_BYTES = 4096  # game sends at most a few bytes; reject anything larger

# Day resets at midnight in this timezone (DST-aware).
# All players on the same server get the same world seed and leaderboard slot.
# Different servers with different timezones will briefly diverge around reset.
# See: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
RESET_TZ = ZoneInfo(os.environ.get("RESET_TIMEZONE", "America/Chicago"))
LEADERBOARD_DAILY_COUNT = 7  # hardcoded in game client
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Portal world pool — seeded by dateCode so every player gets the same world
# each day, but the sequence doesn't follow a predictable repeating pattern.
# Workshop IDs serve that level from Steam. 0 = use built-in Flippfly world
# (client picks from Void/Sky City/Undersea/Mysterious Forest/Sunrise via dateCode).
PORTAL_WORKSHOP = [
    237874411,   # DLV Sky Machine
    238139200,   # DLV Fast Future
    239831012,   # mayan_prophecy
    241141798,   # Mainframe
    263730650,   # Dark Forest
    324930343,   # Forest Run
    393616080,   # DreamScape
    498624231,   # Kings Way
    662666275,   # Maria's Sonnet
]

# Paths the game actually hits — everything else gets 404
KNOWN_PATHS = {
    "/LatestNews/News.php",
    "/parse/functions/get_current_server_info",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("racethesun")
logger.setLevel(logging.DEBUG)

fmt = logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

console = logging.StreamHandler(sys.stdout)
console.setFormatter(fmt)
logger.addHandler(console)

fileh = logging.FileHandler(os.path.join(LOG_DIR, "server.log"))
fileh.setFormatter(fmt)
logger.addHandler(fileh)

reqlog = logging.getLogger("racethesun.requests")
reqlog.setLevel(logging.DEBUG)
reqfh = logging.FileHandler(os.path.join(LOG_DIR, "requests.log"))
reqfh.setFormatter(fmt)
reqlog.addHandler(reqfh)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_news():
    """Read news from news.json, falling back to a default item.

    The game expects a JSON array of objects with fields:
      id, headline, text, linkurl, imageurl
    """
    try:
        raw = Path(NEWS_FILE).read_text().strip()
        # Validate it's a JSON array
        items = json.loads(raw)
        if isinstance(items, list):
            return json.dumps(items)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return json.dumps([{
        "id": "1",
        "headline": "Welcome back!",
        "text": "Race the Sun community server is online.",
        "linkurl": "",
        "imageurl": "",
    }])


def get_server_info():
    """Compute the current dateCode, timeLeft, and leaderboard index.

    The "game day" is defined by midnight Central Time (America/Chicago),
    which automatically handles CST (UTC-6) and CDT (UTC-5) transitions.
    """
    now_utc = datetime.now(timezone.utc)
    now_ct = now_utc.astimezone(RESET_TZ)

    # dateCode = number of days since epoch in Central Time.
    # Note: the game subtracts 1 day when displaying this as a date
    # (see Assembly-CSharp: .AddDays(-1.0)), so the in-game date label
    # will show 1 day behind. This is cosmetic -- do NOT add +1 here,
    # as it shifts the leaderboard slot mapping and breaks score persistence.
    date_code = (now_ct.replace(hour=0, minute=0, second=0, microsecond=0) - EPOCH).days

    # Time left until next midnight CT
    today_midnight_ct = now_ct.replace(hour=0, minute=0, second=0, microsecond=0)
    next_midnight_ct = today_midnight_ct + timedelta(days=1)
    time_left_ms = int((next_midnight_ct - now_ct).total_seconds() * 1000)

    leaderboard_index = date_code % LEADERBOARD_DAILY_COUNT

    # 50/50 Workshop vs built-in, seeded so all players match
    rng = random.Random(date_code)
    if rng.random() < 0.5:
        portal_world = 0  # built-in Flippfly world
    else:
        portal_world = rng.choice(PORTAL_WORKSHOP)

    return {
        "dateCode": date_code,
        "dateTimeLeft": time_left_ms,
        "leaderboardDailyCount": LEADERBOARD_DAILY_COUNT,
        "leaderboardIndex": leaderboard_index,
        "portal_world_steam": portal_world,
    }


def route(method, path, host, body):
    """Return (status_code, content_type, response_body) for a request."""

    # Only allow POST — that's all the game uses
    if method != "POST":
        return (405, "text/plain", "")

    # News endpoint
    if path == "/LatestNews/News.php":
        return (200, "application/json", get_news())

    # Parse cloud function: get_current_server_info
    if path == "/parse/functions/get_current_server_info":
        return (200, "application/json", json.dumps({"result": get_server_info()}))

    # Unknown path — 404
    return (404, "text/plain", "")


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    # Cap header size (Python default is 65536, tighten it)
    max_request_line = 2048

    def _handle(self):
        host = self.headers.get("Host", "unknown")

        # Reject oversized bodies before reading them
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > MAX_BODY_BYTES:
            self.send_response(413)
            self.end_headers()
            logger.warning(f"{self.address_string()}  REJECTED Content-Length={content_length}")
            return

        body = self.rfile.read(content_length) if content_length > 0 else b""
        body_text = body.decode("utf-8", errors="replace") if body else ""

        status, content_type, response_body = route(self.command, self.path, host, body_text)

        # Log
        line = f"{self.address_string()}  {self.command} http://{host}{self.path}  -> {status}"
        logger.info(line)

        # Detailed request log (only for known paths to avoid disk-fill from scanners)
        if self.path in KNOWN_PATHS:
            reqlog.info(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "src": self.address_string(),
                "host": host,
                "path": self.path,
                "body": body_text[:2000] if body_text else None,
                "status": status,
            }))

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body.encode("utf-8"))

    # Silence default access log — we handle our own
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    # Reject everything else
    def do_PUT(self):
        self.send_response(405)
        self.end_headers()

    def do_DELETE(self):
        self.send_response(405)
        self.end_headers()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    info = get_server_info()
    logger.info(f"Starting racethesun-server on 0.0.0.0:{PORT}")
    logger.info(f"  dateCode={info['dateCode']}  leaderboardIndex={info['leaderboardIndex']}  timeLeft={info['dateTimeLeft']}ms")
    logger.info(f"  news file: {NEWS_FILE}")
    logger.info(f"  log dir:   {LOG_DIR}")

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        server.server_close()

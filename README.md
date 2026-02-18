# racethesun-server

Community replacement server for [Race the Sun](https://store.steampowered.com/app/253030/Race_The_Sun/) by Flippfly.

The original game servers are no longer maintained, which breaks leaderboard indexing and in-game news. This is a minimal server that restores that functionality. Score submission and friend leaderboards still work through Steam.

## What it does

- Serves the daily world seed (`dateCode`) so all connected players get the same procedurally generated world
- Provides the correct leaderboard index so Steam daily leaderboards work
- Serves in-game news (configurable via `news.json`)
- Day resets at midnight in a configurable timezone (default: US Central, DST-aware)

## What it doesn't do

- Store scores — that's handled entirely by Steam
- Manage user accounts — the game uses Steam for authentication
- Anything else — the original server only provided these two endpoints

## Requirements

- Python 3.9+ (for `zoneinfo`)
- nginx (for port 80 proxying and rate limiting)

## Setup

### Client side (each player)

Add to your hosts file (`C:\Windows\System32\drivers\etc\hosts` on Windows):

```
YOUR_SERVER_IP   tech.flippfly.com
YOUR_SERVER_IP   monkeytech.flippfly.com
```

Or configure equivalent DNS overrides on your router.

### Server side

```bash
# Clone and configure
git clone https://github.com/plasticsmoke/racethesun-server.git
cd racethesun-server
cp deploy.conf.example deploy.conf
# Edit deploy.conf with your VPS details

# Deploy to VPS
./deploy.sh --setup    # first time: creates systemd service, starts server
./deploy.sh            # subsequent: syncs code, restarts service

# On the VPS, install the nginx config
sudo cp nginx-racethesun.conf /etc/nginx/sites-available/racethesun
sudo ln -s /etc/nginx/sites-available/racethesun /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default  # if this is a dedicated server
sudo nginx -t && sudo systemctl reload nginx
```

### Running locally (for testing)

```bash
python3 mock_server.py              # listens on port 8080
PORT=80 sudo python3 mock_server.py # listens on port 80
```

## Files

| File | Purpose |
|---|---|
| `mock_server.py` | The server |
| `news.json` | In-game news (edit to post messages to players) |
| `deploy.sh` | Deploy script (`--setup` for first time, no args for updates) |
| `deploy.conf.example` | Template for VPS connection settings (including timezone) |
| `nginx-racethesun.conf` | nginx reverse proxy config with rate limiting |

## API endpoints

The game makes exactly two HTTP POST requests on startup:

| Endpoint | Host | Purpose |
|---|---|---|
| `/LatestNews/News.php` | monkeytech.flippfly.com | News feed (JSON array) |
| `/parse/functions/get_current_server_info` | tech.flippfly.com | Daily world info |

## News format

Edit `news.json` on the server. Each item needs these fields:

```json
[
  {
    "id": "1",
    "headline": "Title shown in bold",
    "text": "Description text shown below the headline.",
    "linkurl": "https://example.com",
    "imageurl": ""
  }
]
```

The `linkurl` opens in the system browser when clicked. The `imageurl` field is accepted but not displayed (the game fetches the image but the rendering callback is a no-op in the current build). You can leave it empty.

## Timezone / daily reset

The world resets at midnight in the configured timezone (set `RESET_TIMEZONE` in `deploy.conf`). The default is `America/Chicago` (US Central, DST-aware). All players on the same server always get the same world and leaderboard slot.

If two people run separate servers with different timezones, there's a brief window around each reset where their players would see different worlds. Outside that window, the `dateCode` converges and everyone is on the same seed. Steam leaderboards are just named buckets — they don't have a concept of "today."

For a list of valid timezone names, see the [tz database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

## How it works

Race the Sun uses a Parse Server backend for one thing: telling all players which day it is (the `dateCode`). This seed drives the procedural world generation so everyone plays the same level each day. The `leaderboardIndex` tells the game which of 7 rotating Steam daily leaderboard slots to use.

Score submission, friend leaderboards, achievements, and cloud saves all go through Steam directly and don't need this server.

## License

MIT

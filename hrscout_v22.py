import asyncio
import datetime
import re
import aiohttp
from telegram import Bot

# ============================================================
#  TOMMY'S SHEET PARSER
# ============================================================
def parse_tommy_sheet(text):
    """
    Parse Tommy's cheat sheet and extract players by tier.
    Tier 1: Barrel % 15%+ vs PM (bold players)
    Tier 2: EV logs with 100mph+ balls
    Tier 3: PA% 20%+
    """
    import re

    tier1 = []  # Elite barrel %
    tier2 = []  # Hot EV logs
    tier3 = []  # High PA%
    all_players = []

    lines = text.split("\n")
    current_pitcher = ""
    current_game = ""

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Detect game header
        game_match = re.search(r"([A-Z]{2,3})@([A-Z]{2,3})", line)
        if game_match:
            current_game = line[:20].strip()
            continue

        # Detect pitcher line
        if "Pitcher:" in line:
            pitcher_match = re.search(r"Pitcher:\s*([A-Z]\.\s*\w+)", line)
            if pitcher_match:
                current_pitcher = pitcher_match.group(1).strip()
            continue

        # Parse player line — format: Name - B%, ISO, EV, HRs vs PM - PA%
        # Example: K. Carpenter - 14B%, .438ISO, 93EV, 9HRs vs PM (21/73) - 22PA%
        player_match = re.match(
            r"([A-Z][a-z]?\.\s*[A-Za-z\s\.\-]+?)\s*[-–]\s*(\d+\.?\d*)B%,\s*\.?(\d+)ISO,\s*(\d+)EV",
            line
        )

        if player_match:
            name = player_match.group(1).strip()
            barrel = float(player_match.group(2))
            iso = int(player_match.group(3))
            ev = int(player_match.group(4))

            # Extract HR count
            hr_match = re.search(r"(\d+)HR", line)
            hrs = int(hr_match.group(1)) if hr_match else 0

            # Extract PA%
            pa_match = re.search(r"(\d+\.?\d*)PA%", line)
            pa_pct = float(pa_match.group(1)) if pa_match else 0

            player = {
                "name": name,
                "barrel": barrel,
                "iso": iso,
                "ev": ev,
                "hrs_vs_pm": hrs,
                "pa_pct": pa_pct,
                "pitcher": current_pitcher,
                "game": current_game,
                "ev_logs": [],
            }

            all_players.append(player)

            # Tier 1: barrel 15%+
            if barrel >= 15:
                tier1.append(player)
            # Tier 3: PA% 20%+
            if pa_pct >= 20:
                if player not in tier3:
                    tier3.append(player)

            continue

        # Parse EV logs — format: (Name - 100,105,97)
        ev_log_match = re.match(r"\(?([A-Z][a-z]?\.\s*[A-Za-z\s\.\-]+?)\s*[-–]\s*([\d,SO\s]+)\)?", line)
        if ev_log_match:
            log_name = ev_log_match.group(1).strip()
            log_str = ev_log_match.group(2)
            # Extract numeric EV values
            ev_values = []
            for v in log_str.split(","):
                v = v.strip()
                if v.isdigit():
                    ev_values.append(int(v))

            # Check for 100mph+ balls
            hot_balls = [v for v in ev_values if v >= 100]

            if len(hot_balls) >= 2:
                # Find matching player
                for p in all_players:
                    if log_name.lower() in p["name"].lower() or p["name"].lower() in log_name.lower():
                        p["ev_logs"] = ev_values
                        p["hot_balls"] = len(hot_balls)
                        if p not in tier2:
                            tier2.append(p)
                        break
                else:
                    # New player from EV logs only
                    tier2.append({
                        "name": log_name,
                        "barrel": 0,
                        "iso": 0,
                        "ev": max(ev_values) if ev_values else 0,
                        "hrs_vs_pm": 0,
                        "pa_pct": 0,
                        "pitcher": current_pitcher,
                        "game": current_game,
                        "ev_logs": ev_values,
                        "hot_balls": len(hot_balls),
                    })

    return tier1, tier2, tier3, all_players


def build_sheet_parlay(tier1, tier2, tier3, odds_cache):
    """
    Build parlay recommendations from Tommy's sheet.
    Priority: Tier1 barrel% + PA% + EV logs + odds value
    """
    # Score each player
    def player_score(p):
        score = 0
        # Barrel % — primary factor
        b = p.get("barrel", 0)
        if b >= 25: score += 40
        elif b >= 20: score += 32
        elif b >= 15: score += 24
        elif b >= 10: score += 15

        # PA% — pulled airballs
        pa = p.get("pa_pct", 0)
        if pa >= 30: score += 20
        elif pa >= 25: score += 15
        elif pa >= 20: score += 10

        # EV logs — hot right now
        hot = p.get("hot_balls", 0)
        if hot >= 3: score += 20
        elif hot >= 2: score += 15
        elif hot >= 1: score += 8

        # ISO power
        iso = p.get("iso", 0)
        if iso >= 400: score += 15
        elif iso >= 300: score += 12
        elif iso >= 200: score += 8
        elif iso >= 150: score += 4

        # HRs vs pitch mix
        hrs = p.get("hrs_vs_pm", 0)
        if hrs >= 8: score += 10
        elif hrs >= 5: score += 7
        elif hrs >= 3: score += 4

        # EV average
        ev = p.get("ev", 0)
        if ev >= 95: score += 8
        elif ev >= 92: score += 5
        elif ev >= 90: score += 3

        return score

    # Combine all tiers, deduplicate
    seen = set()
    pool = []
    for p in tier1 + tier2 + tier3:
        if p["name"] not in seen:
            seen.add(p["name"])
            p["score"] = player_score(p)
            # Get odds if available
            odds = None
            for k, v in odds_cache.items():
                if p["name"].lower().split()[-1] in k:
                    odds = v
                    break
            p["fd_odds"] = odds["fd"] if odds else None
            pool.append(p)

    # Sort by score — EV tiebreaker when within 5 points
    pool.sort(key=lambda x: (x["score"], x.get("fd_odds", 0) or 0), reverse=True)

    # When two players within 5 score points — higher odds wins
    for i in range(len(pool) - 1):
        if abs(pool[i]["score"] - pool[i+1]["score"]) <= 5:
            p1_odds = pool[i].get("fd_odds") or 200
            p2_odds = pool[i+1].get("fd_odds") or 200
            if p2_odds > p1_odds + 30:
                pool[i], pool[i+1] = pool[i+1], pool[i]

    return pool


async def handle_sheet_command(bot, text):
    """Handle /sheet command — parse Tommy's sheet and return parlay picks."""
    await bot.send_message(chat_id=CHAT_ID, text="📋 Parsing Tommy's sheet...")

    tier1, tier2, tier3, all_players = parse_tommy_sheet(text)
    pool = build_sheet_parlay(tier1, tier2, tier3, hr_odds_cache)

    if not pool:
        await bot.send_message(chat_id=CHAT_ID, text="❌ Could not parse sheet. Check format and try again.")
        return

    # Build response
    msg = "📋 TOMMY'S SHEET PARSED\n━━━━━━━━━━━━━━━━━━━━━━\n"

    if tier1:
        msg += "\n🔥 TIER 1 — Elite Barrel % vs PM\n"
        for p in sorted(tier1, key=lambda x: x["barrel"], reverse=True)[:6]:
            pa = f" {p['pa_pct']}PA%" if p["pa_pct"] >= 20 else ""
            msg += f"• {p['name']} — {p['barrel']}B% {p['ev']}EV{pa}\n"

    if tier2:
        msg += "\n⚡ TIER 2 — Hot EV Logs (100mph+)\n"
        for p in tier2[:5]:
            logs = ",".join(str(v) for v in p.get("ev_logs", []))
            msg += f"• {p['name']} — ({logs})\n"

    if tier3:
        t3_unique = [p for p in tier3 if p not in tier1]
        if t3_unique:
            msg += "\n🎯 TIER 3 — High PA% Only\n"
            for p in sorted(t3_unique, key=lambda x: x["pa_pct"], reverse=True)[:4]:
                msg += f"• {p['name']} — {p['pa_pct']}PA%\n"

    msg += "\n━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "🎯 PARLAY RECOMMENDATIONS\n━━━━━━━━━━━━━━━━━━━━━━\n"

    def leg(p, i):
        fd = f"+{p['fd_odds']}" if p.get("fd_odds") and p["fd_odds"] > 0 else "N/A"
        pa = f" {p['pa_pct']}PA%" if p["pa_pct"] >= 20 else ""
        hot = " 🔥" if p.get("hot_balls", 0) >= 2 else ""
        return f"{i}. {p['name']} — {p['barrel']}B%{pa}{hot} | FD:{fd}"

    if len(pool) >= 2:
        msg += "\n2️⃣ 2-LEG\n"
        msg += "\n".join(leg(pool[i], i+1) for i in range(min(2, len(pool))))

    if len(pool) >= 3:
        msg += "\n\n3️⃣ 3-LEG\n"
        msg += "\n".join(leg(pool[i], i+1) for i in range(min(3, len(pool))))

    if len(pool) >= 4:
        msg += "\n\n4️⃣ 4-LEG\n"
        msg += "\n".join(leg(pool[i], i+1) for i in range(min(4, len(pool))))

    # EV 3-leg — best odds from pool
    ev_pool = sorted(pool, key=lambda x: x.get("fd_odds") or 0, reverse=True)
    std_names = {pool[i]["name"] for i in range(min(4, len(pool)))}
    ev_alt = [p for p in ev_pool if p["name"] not in std_names]
    if len(ev_alt) >= 3:
        msg += "\n\n💰 EV 3-LEG (VALUE)\n"
        msg += "\n".join(leg(ev_alt[i], i+1) for i in range(3))

    msg += "\n━━━━━━━━━━━━━━━━━━━━━━"
    await bot.send_message(chat_id=CHAT_ID, text=msg)


TELEGRAM_TOKEN = "8720993049:AAEimQD4PUDFlMA2bpxXsyW3IMcTZ5ak0PY"
CHAT_ID = "919904024"
SCAN_INTERVAL = 300
HOT_MIN = 3
INTERCHANGE_GAP = 3
PARLAY_MIN_CONF = 62

PARK_FACTORS = {
    "COL": 120, "CIN": 112, "PHI": 110, "NYY": 108, "BOS": 106,
    "MIL": 104, "HOU": 103, "ATL": 102, "CHC": 102, "LAD": 100,
    "NYM": 100, "STL": 98, "MIN": 98, "DET": 97, "PIT": 97,
    "TOR": 97, "BAL": 97, "CLE": 96, "CWS": 96, "SEA": 95,
    "MIA": 95, "WSH": 95, "ARI": 95, "KC": 94, "LAA": 94,
    "TB": 94, "SD": 93, "SF": 92, "OAK": 92, "TEX": 91,
}

TEAM_ABBREV = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET",
    "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB", "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
    "Athletics": "OAK",
}

# ============================================================
#  ODDS CACHE
# ============================================================
hr_odds_cache = {}

async def load_hr_odds(session):
    global hr_odds_cache
    urls = [
        "https://fantasyteamadvice.com/mlb/props/home-runs",
        "https://www.rotowire.com/betting/mlb/player-props.php",
    ]
    for url in urls:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                html = await resp.text()
            pattern = r"([A-Z][a-z]+ [A-Z][a-zA-Z\-\.]+)\s*(?:<[^>]+>\s*){1,10}([+]\d{3,4})\s*(?:<[^>]+>\s*){1,10}([+]\d{3,4})"
            matches = re.findall(pattern, html)
            for m in matches:
                try:
                    name = m[0].strip()
                    fd = int(m[1].replace("+", ""))
                    mgm = int(m[2].replace("+", ""))
                    if name and len(name) > 4:
                        hr_odds_cache[name.lower()] = {"fd": fd, "mgm": mgm}
                except:
                    continue
            if hr_odds_cache:
                break
        except:
            continue

def get_odds(name):
    key = name.lower()
    if key in hr_odds_cache:
        return hr_odds_cache[key]
    parts = key.split()
    if len(parts) >= 2:
        last = parts[-1]
        for k, v in hr_odds_cache.items():
            if last in k and len(last) > 3:
                return v
    return None

def american_to_prob(odds):
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)

def calc_ev(conf, odds):
    return round((conf / 100 - american_to_prob(odds)) * 100, 1)

# ============================================================
#  SAVANT CACHE
# ============================================================
savant_cache = {}

async def load_savant(session):
    global savant_cache
    url = "https://baseballsavant.mlb.com/leaderboard/expected_statistics?type=batter&year=2026&position=&team=&min=100&csv=true"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            text = await resp.text()
        lines = text.strip().split("\n")
        if len(lines) < 2:
            return
        headers = [h.strip().strip('"').lower() for h in lines[0].split(",")]
        for line in lines[1:]:
            try:
                vals = line.split(",")
                row = dict(zip(headers, vals))
                pid = row.get("player_id", "").strip().strip('"')
                if pid:
                    savant_cache[pid] = row
            except:
                continue
    except:
        pass

def get_savant(player_id):
    row = savant_cache.get(str(player_id), {})
    if not row:
        return None
    try:
        barrel = float(row.get("brl_percent", 0) or 0)
        ev = float(row.get("exit_velocity_avg", 0) or 0)
        hh = float(row.get("hard_hit_percent", 0) or 0)
        if barrel > 0 or ev > 0:
            return {"barrel": barrel, "ev": ev, "hh": hh}
    except:
        pass
    return None

# ============================================================
#  SCORING — Recalibrated for 80-90% top plays
# ============================================================
def score_barrel(b):
    # 20%+ = 100, scales down
    if b >= 20: return 100
    if b >= 15: return 92
    if b >= 12: return 82
    if b >= 10: return 72
    if b >= 7:  return 55
    if b >= 5:  return 38
    return 18

def score_ev(e):
    if e >= 96: return 100
    if e >= 93: return 92
    if e >= 91: return 82
    if e >= 89: return 72
    if e >= 87: return 55
    if e >= 85: return 38
    return 18

def score_hh(h):
    if h >= 55: return 100
    if h >= 50: return 90
    if h >= 45: return 80
    if h >= 40: return 68
    if h >= 35: return 52
    if h >= 30: return 35
    return 18

def score_fb(f):
    if f >= 50: return 100
    if f >= 44: return 88
    if f >= 38: return 75
    if f >= 32: return 60
    if f >= 26: return 42
    return 22

def score_iso(i):
    if i >= 300: return 100
    if i >= 260: return 90
    if i >= 220: return 80
    if i >= 180: return 68
    if i >= 140: return 52
    if i >= 100: return 35
    return 18

def score_pull(p):
    if p >= 52: return 100
    if p >= 45: return 90
    if p >= 38: return 78
    if p >= 32: return 62
    if p >= 26: return 42
    return 20

def score_recent_hr(hr, games):
    r = (hr / max(games, 1)) * 14
    if r >= 6: return 100
    if r >= 4: return 88
    if r >= 3: return 75
    if r >= 2: return 58
    if r >= 1: return 40
    return 18

def score_batter_form(avg7, hr7):
    if hr7 >= 4: return 100
    if hr7 >= 3: return 90
    if hr7 >= 2: return 78
    if hr7 >= 1 and avg7 >= 0.300: return 65
    if hr7 >= 1: return 55
    if avg7 >= 0.320: return 42
    if avg7 >= 0.260: return 30
    return 15

def score_p_hr9(h):
    if h >= 2.0: return 100
    if h >= 1.7: return 90
    if h >= 1.4: return 80
    if h >= 1.2: return 68
    if h >= 1.0: return 52
    if h >= 0.7: return 32
    return 15

def score_p_barrel(b):
    if b >= 14: return 100
    if b >= 12: return 88
    if b >= 10: return 75
    if b >= 8:  return 60
    if b >= 6:  return 42
    return 22

def score_p_form(last3, era):
    d = last3 - era
    if d >= 3.0: return 100
    if d >= 2.0: return 88
    if d >= 1.0: return 75
    if d >= 0.0: return 58
    if d >= -1.0: return 38
    return 20

def score_platoon(bhand, splits):
    if not splits:
        return 58
    if bhand == "S":
        hr9 = max(splits.get("rhb_hr9", 1.2), splits.get("lhb_hr9", 1.2))
    elif bhand == "R":
        hr9 = splits.get("rhb_hr9", 1.2)
    else:
        hr9 = splits.get("lhb_hr9", 1.2)
    if hr9 >= 2.0: return 100
    if hr9 >= 1.7: return 90
    if hr9 >= 1.4: return 80
    if hr9 >= 1.2: return 68
    if hr9 >= 0.9: return 52
    if hr9 >= 0.6: return 32
    return 15

def score_park(abbrev):
    f = PARK_FACTORS.get(abbrev, 100)
    if f >= 115: return 100
    if f >= 110: return 88
    if f >= 105: return 78
    if f >= 100: return 65
    if f >= 95:  return 50
    if f >= 90:  return 35
    return 20

def score_order(spot):
    if spot <= 0: return 62
    if spot in [3, 4]: return 95
    if spot in [1, 2, 5]: return 82
    if spot in [6, 7]: return 70
    if spot in [8, 9]: return 55
    return 50

# ============================================================
#  WEIGHTED CONFIDENCE ENGINE — RECALIBRATED
#  Same weighted system as before but scores spread wider
#  Elite: 80-95% | Strong: 70-79% | Good: 60-69%
#  Average: 50-59% | Weak: below 50%
# ============================================================
def score_barrel(b):
    if b >= 20: return 100
    if b >= 15: return 88
    if b >= 12: return 78
    if b >= 10: return 68
    if b >= 7:  return 50
    if b >= 5:  return 32
    return 15

def score_ev(e):
    if e >= 96: return 100
    if e >= 93: return 88
    if e >= 91: return 78
    if e >= 89: return 65
    if e >= 87: return 50
    if e >= 85: return 32
    return 15

def score_hh(h):
    if h >= 55: return 100
    if h >= 50: return 88
    if h >= 45: return 78
    if h >= 40: return 65
    if h >= 35: return 50
    if h >= 30: return 32
    return 15

def score_fb(f):
    if f >= 50: return 100
    if f >= 44: return 85
    if f >= 38: return 72
    if f >= 32: return 58
    if f >= 26: return 42
    return 20

def score_iso(i):
    if i >= 300: return 100
    if i >= 250: return 88
    if i >= 200: return 75
    if i >= 150: return 60
    if i >= 100: return 42
    return 20

def score_pull(p):
    if p >= 52: return 100
    if p >= 45: return 88
    if p >= 38: return 75
    if p >= 32: return 60
    if p >= 26: return 42
    return 20

def score_recent_hr(hr, games):
    r = (hr / max(games, 1)) * 14
    if r >= 6: return 100
    if r >= 4: return 85
    if r >= 3: return 72
    if r >= 2: return 58
    if r >= 1: return 40
    return 18

def score_batter_form(avg7, hr7):
    if hr7 >= 4: return 100
    if hr7 >= 3: return 88
    if hr7 >= 2: return 75
    if hr7 >= 1 and avg7 >= 0.300: return 62
    if hr7 >= 1: return 52
    if avg7 >= 0.320: return 40
    if avg7 >= 0.260: return 28
    return 12

def score_p_hr9(h):
    if h >= 2.0: return 100
    if h >= 1.7: return 88
    if h >= 1.4: return 78
    if h >= 1.2: return 65
    if h >= 1.0: score = 50
    if h >= 0.7: return 32
    return 12

def score_p_barrel(b):
    if b >= 14: return 100
    if b >= 11: return 85
    if b >= 8:  return 68
    if b >= 6:  return 50
    return 25

def score_p_form(last3, era):
    d = last3 - era
    if d >= 3.0:    return 100
    if d >= 2.0:    return 85
    if d >= 1.0:    return 70
    if d >= 0.0:    return 55
    if d >= -1.0:   return 38
    return 20

def score_platoon(bhand, splits):
    if not splits:
        return 55
    if bhand == "S":
        hr9 = max(splits.get("rhb_hr9", 1.2), splits.get("lhb_hr9", 1.2))
    elif bhand == "R":
        hr9 = splits.get("rhb_hr9", 1.2)
    else:
        hr9 = splits.get("lhb_hr9", 1.2)
    if hr9 >= 2.5: return 100
    if hr9 >= 2.0: return 88
    if hr9 >= 1.5: return 75
    if hr9 >= 1.2: return 62
    if hr9 >= 0.9: return 48
    if hr9 < 0.6:  return 20
    return 35

def score_park(abbrev):
    f = PARK_FACTORS.get(abbrev, 100)
    if f >= 115: return 100
    if f >= 108: return 82
    if f >= 103: return 68
    if f >= 98:  return 55
    if f >= 93:  return 40
    return 22

def score_order(spot):
    if spot <= 0:           return 60
    if spot in [3, 4]:      return 95
    if spot in [1, 2, 5]:   return 80
    if spot in [6, 7]:      return 65
    if spot in [8, 9]:      return 50
    return 45

def calculate_confidence(b, p, park, spot=0, splits=None):
    # Weighted system — situation over reputation
    # Savant metrics weighted lower so missing data doesn't skew rankings
    weights = {
        "p_hr9":       13,  # Pitcher vulnerability
        "platoon":     13,  # Real platoon splits
        "p_form":      10,  # Pitcher recent trend
        "batter_form": 10,  # Batter hot last 7 days
        "p_barrel":     7,  # Barrel allowed
        "recent_hr":    8,  # Season HR rate
        "barrel":       8,  # Savant barrel — capped weight so missing data doesn't hurt
        "ev":           6,  # Savant EV
        "hh":           4,  # Hard hit
        "fb":           4,  # Flyball
        "pull":         4,  # Pull rate
        "iso":          3,  # Raw power — low weight prevents chalk bias
        "park":         4,  # Park factor
        "order":        2,  # Batting order
    }
    scores = {
        "p_hr9":       score_p_hr9(p.get("hr9", 1.2)),
        "platoon":     score_platoon(b.get("hand", "R"), splits),
        "p_form":      score_p_form(p.get("last3_era", 4.0), p.get("era", 4.0)),
        "batter_form": score_batter_form(b.get("avg7", 0.250), b.get("hr7", 0)),
        "p_barrel":    score_p_barrel(p.get("barrel_against", 8)),
        "recent_hr":   score_recent_hr(b.get("hr", 0), b.get("games", 1)),
        "barrel":      score_barrel(b.get("barrel", 8)),
        "ev":          score_ev(b.get("ev", 88)),
        "hh":          score_hh(b.get("hh", 35)),
        "fb":          score_fb(b.get("fb", 35)),
        "pull":        score_pull(b.get("pull", 35)),
        "iso":         score_iso(b.get("iso", 140)),
        "park":        score_park(park),
        "order":       score_order(spot),
    }
    raw = sum(scores[k] * weights[k] / 100 for k in scores)
    # Scale to target range: 50-95%
    scaled = 45 + (raw * 0.55)
    return min(95, max(25, round(scaled)))

def pitcher_trend(era, last3):
    d = last3 - era
    if d >= 1.5: return "📈 TRENDING WORSE"
    if d >= 0.5: return "⚠️ SLIGHTLY WORSE"
    if d <= -1.5: return "📉 IMPROVING"
    if d <= -0.5: return "✅ SLIGHTLY BETTER"
    return "➡️ STABLE"

def vuln_flag(hr9, barrel):
    if hr9 >= 1.5 or barrel >= 11: return "🚨 VULNERABLE"
    if hr9 >= 1.2 or barrel >= 8: return "⚠️ ELEVATED RISK"
    return "✅ SOLID"

def platoon_gap_label(rhb, lhb):
    g = abs(rhb - lhb)
    if g >= 0.8: return "MASSIVE"
    if g >= 0.4: return "SIGNIFICANT"
    if g >= 0.2: return "MODERATE"
    return "MINIMAL"

# ============================================================
#  TIEBREAKER — Core logic
#  Within 3%: higher odds wins automatically
#  Beyond 3%: confidence wins
# ============================================================
def resolve_tiebreaker(p1, p2):
    gap = abs(p1["conf"] - p2["conf"])

    if gap > INTERCHANGE_GAP:
        # Clear winner by confidence
        winner = p1 if p1["conf"] >= p2["conf"] else p2
        return winner, None, "CLEAR"

    # Within 3% — HIGHER ODDS ALWAYS WINS
    # This is the core fix — same data = take the value
    p1_odds = p1.get("fd_odds")
    p2_odds = p2.get("fd_odds")

    if p1_odds and p2_odds:
        # Any odds difference — higher odds wins
        if p1_odds > p2_odds:
            return p1, p2, "VALUE_WIN"
        elif p2_odds > p1_odds:
            return p2, p1, "VALUE_SWAP"

    # No odds data — check platoon splits
    p1_platoon = p1.get("platoon_hr9", 1.2)
    p2_platoon = p2.get("platoon_hr9", 1.2)
    platoon_diff = abs(p1_platoon - p2_platoon)

    if platoon_diff >= 0.4:
        if p1_platoon >= p2_platoon:
            return p1, p2, "PLATOON_WIN"
        else:
            return p2, p1, "PLATOON_SWAP"

    # Truly interchangeable — no odds data, similar platoon
    winner = p1 if p1["conf"] >= p2["conf"] else p2
    loser = p2 if p1["conf"] >= p2["conf"] else p1
    return winner, loser, "INTERCHANGEABLE"

# ============================================================
#  API CALLS
# ============================================================
# ============================================================
#  PROJECTED LINEUPS — lineups.com scraper
#  Runs in morning before confirmed lineups drop
# ============================================================
projected_lineups_cache = {}

async def load_projected_lineups(session):
    """Scrape lineups.com for projected lineups early in the day."""
    global projected_lineups_cache
    url = "https://www.lineups.com/mlb/lineups/"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            html = await resp.text()

        import re
        # Extract team matchups and projected lineups
        # lineups.com format: team names and player names in order
        # Look for lineup sections
        team_pattern = r'([A-Z]{2,3})\s+@\s+([A-Z]{2,3})'
        player_pattern = r'[A-Za-z][a-z]+ [A-Z][a-z]+'

        teams = re.findall(team_pattern, html)
        players = re.findall(player_pattern, html)

        # Store raw data — will be matched against MLB API games
        projected_lineups_cache = {
            "teams": teams,
            "players": players,
            "loaded": True,
            "timestamp": datetime.datetime.now().isoformat()
        }

        # Alternative: try Baseball Press which has cleaner HTML
        bp_url = "https://www.baseballpress.com/lineups"
        async with session.get(bp_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp2:
            html2 = await resp2.text()

        # Baseball Press format: player names in lineup order per team
        lineup_section = re.findall(
            r"class=\"player[^\"]*\"[^>]*>.*?<span[^>]*>([A-Za-z .'-]+)</span>",
            html2, re.DOTALL
        )
        if lineup_section:
            projected_lineups_cache["bp_players"] = lineup_section

    except Exception as e:
        pass

def get_projected_lineup(team_abbrev):
    """Get projected lineup for a team from cache."""
    return projected_lineups_cache.get(team_abbrev, [])


async def get_team_roster(session, team_id):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster?rosterType=active"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
        return data.get("roster", [])
    except:
        return []


async def get_todays_games(session):
    today = datetime.date.today().strftime("%Y-%m-%d")
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today}&hydrate=probablePitcher,team,lineups"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
        games = []
        for date in data.get("dates", []):
            for game in date.get("games", []):
                gt = game.get("gameDate", "")
                try:
                    dt = datetime.datetime.fromisoformat(gt.replace("Z", "+00:00"))
                    # Convert to ET and filter 1am-6am games
                    et_hour = (dt.hour - 4) % 24
                    if 1 <= et_hour <= 6:
                        continue
                except:
                    pass
                games.append(game)
        return games
    except:
        return []

async def get_batter_stats(session, player_id):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season,lastXGames&group=hitting&season=2026&gameType=R&limit=7"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        season = {}
        recent = {}
        for block in data.get("stats", []):
            t = block.get("type", {}).get("displayName", "")
            splits = block.get("splits", [])
            if splits:
                s = splits[0].get("stat", {})
                if "season" in t.lower(): season = s
                elif "last" in t.lower(): recent = s
        if not season:
            return None
        hr = int(season.get("homeRuns", 0))
        games = int(season.get("gamesPlayed", 1))
        ab = int(season.get("atBats", 1))
        slg = float(season.get("sluggingPercentage", 0.350) or 0.350)
        avg = float(season.get("avg", 0.230) or 0.230)
        iso = round((slg - avg) * 1000)
        hr_rate = hr / max(ab, 1)
        # Better estimates
        barrel = min(25, max(3, (hr_rate * 180) + (iso - 100) * 0.04))
        ev = min(98, max(83, 87 + (iso - 130) * 0.04 + (slg - 0.350) * 8))
        hh = min(65, max(22, 32 + (iso - 130) * 0.06 + (slg - 0.350) * 30))
        fb = min(55, max(22, 30 + hr_rate * 200 + (iso - 130) * 0.03))
        pull = min(60, max(25, 36 + hr_rate * 180 + (iso - 130) * 0.02))
        hr7 = int(recent.get("homeRuns", 0))
        avg7 = float(recent.get("avg", avg) or avg)
        # Override with Savant if available — mark as real
        sv = get_savant(player_id)
        savant_real = False
        if sv:
            if sv["barrel"] > 0:
                barrel = sv["barrel"]
                savant_real = True
            if sv["ev"] > 0: ev = sv["ev"]
            if sv["hh"] > 0: hh = sv["hh"]
        # Get batter hand
        hand = "R"
        try:
            async with session.get(
                f"https://statsapi.mlb.com/api/v1/people/{player_id}",
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r2:
                pd = await r2.json()
            hand = pd.get("people", [{}])[0].get("batSide", {}).get("code", "R")
        except:
            pass
        return {
            "barrel": barrel, "ev": ev, "hh": hh, "fb": fb,
            "hr": hr, "games": games, "iso": iso,
            "pull": pull, "hand": hand,
            "hr7": hr7, "avg7": avg7,
            "savant_real": savant_real,  # True = real Statcast, False = estimated
        }
    except:
        pass
    return None

async def get_pitcher_stats(session, player_id):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season,gameLog&group=pitching&season=2026&gameType=R"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        season = {}
        game_log = []
        for block in data.get("stats", []):
            t = block.get("type", {}).get("displayName", "")
            splits = block.get("splits", [])
            if "season" in t.lower() and splits:
                season = splits[0].get("stat", {})
            elif "log" in t.lower():
                game_log = splits
        if not season:
            return None
        hr9 = float(season.get("homeRunsPer9", 1.2) or 1.2)
        era = float(season.get("era", 4.00) or 4.00)
        whip = float(season.get("whip", 1.30) or 1.30)
        k9 = float(season.get("strikeoutsPer9Inn", 7.0) or 7.0)
        barrel_against = min(18, max(4, (era - 3.0) * 3 + 8))
        hh_against = min(50, max(25, 30 + (era - 3.5) * 4))
        # Real last 3 starts ERA
        last3_era = era
        if game_log:
            recent = game_log[-3:] if len(game_log) >= 3 else game_log
            er = sum(int(g.get("stat", {}).get("earnedRuns", 0)) for g in recent)
            ip = sum(float(g.get("stat", {}).get("inningsPitched", 0) or 0) for g in recent)
            if ip > 0:
                last3_era = round((er / ip) * 9, 2)
        # Pitcher hand
        hand = "R"
        try:
            async with session.get(
                f"https://statsapi.mlb.com/api/v1/people/{player_id}",
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r2:
                pd = await r2.json()
            hand = pd.get("people", [{}])[0].get("pitchHand", {}).get("code", "R")
        except:
            pass
        # Real platoon splits
        rhb_hr9 = lhb_hr9 = hr9
        rhb_slg = lhb_slg = 0.400
        rhb_avg = lhb_avg = 0.250
        try:
            surl = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=statSplits&group=pitching&season=2026&sitCodes=vr,vl"
            async with session.get(surl, timeout=aiohttp.ClientTimeout(total=10)) as r3:
                sd = await r3.json()
            for block in sd.get("stats", []):
                for split in block.get("splits", []):
                    sit = split.get("split", {}).get("code", "")
                    s = split.get("stat", {})
                    h = int(s.get("homeRuns", 0))
                    ip = float(s.get("inningsPitched", 1) or 1)
                    c_hr9 = round((h / max(ip, 1)) * 9, 2)
                    if sit == "vr":
                        rhb_hr9 = c_hr9
                        rhb_slg = float(s.get("sluggingPercentage", 0.400) or 0.400)
                        rhb_avg = float(s.get("avg", 0.250) or 0.250)
                    elif sit == "vl":
                        lhb_hr9 = c_hr9
                        lhb_slg = float(s.get("sluggingPercentage", 0.400) or 0.400)
                        lhb_avg = float(s.get("avg", 0.250) or 0.250)
        except:
            pass
        return {
            "hr9": hr9, "era": era, "whip": whip, "k9": k9,
            "barrel_against": barrel_against, "hh_against": hh_against,
            "last3_era": last3_era, "hand": hand,
            "splits": {
                "rhb_hr9": rhb_hr9, "lhb_hr9": lhb_hr9,
                "rhb_slg": rhb_slg, "lhb_slg": lhb_slg,
                "rhb_avg": rhb_avg, "lhb_avg": lhb_avg,
            }
        }
    except:
        pass
    return None

# ============================================================
#  GAME STATE
# ============================================================
def game_fingerprint(game, home_lineup, away_lineup):
    hp = game.get("teams", {}).get("home", {}).get("probablePitcher", {}).get("id", "")
    ap = game.get("teams", {}).get("away", {}).get("probablePitcher", {}).get("id", "")
    hi = tuple(p.get("id") for p in home_lineup)
    ai = tuple(p.get("id") for p in away_lineup)
    return f"{hp}_{ap}_{hi}_{ai}"

# ============================================================
#  MAIN SCAN
# ============================================================
async def run_scan(bot, states=None, parlay_sent=False):
    if states is None:
        states = {}

    new_states = dict(states)
    all_top_picks = []
    first_game_time = None

    async with aiohttp.ClientSession() as session:
        await load_savant(session)
        await load_hr_odds(session)
        await load_projected_lineups(session)

        games = await get_todays_games(session)
        if not games:
            return states, parlay_sent

        for game in games:
            if game.get("status", {}).get("abstractGameState", "") == "Final":
                continue
            gt = game.get("gameDate", "")
            try:
                dt = datetime.datetime.fromisoformat(gt.replace("Z", "+00:00"))
                if first_game_time is None or dt < first_game_time:
                    first_game_time = dt
            except:
                pass

        for game in games:
            game_id = str(game.get("gamePk", ""))
            if game.get("status", {}).get("abstractGameState", "") == "Final":
                continue

            home_name = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "")
            away_name = game.get("teams", {}).get("away", {}).get("team", {}).get("name", "")
            home_abbrev = TEAM_ABBREV.get(home_name, "???")
            away_abbrev = TEAM_ABBREV.get(away_name, "???")
            home_pitcher = game.get("teams", {}).get("home", {}).get("probablePitcher", {})
            away_pitcher = game.get("teams", {}).get("away", {}).get("probablePitcher", {})

            lineups = game.get("lineups", {})
            home_lineup = lineups.get("homePlayers", [])
            away_lineup = lineups.get("awayPlayers", [])

            if not home_lineup and not away_lineup:
                # Try projected lineups from lineups.com
                # Use full roster as fallback — bot will rescore when confirmed
                home_team_id = game.get("teams", {}).get("home", {}).get("team", {}).get("id")
                away_team_id = game.get("teams", {}).get("away", {}).get("team", {}).get("id")
                if not home_team_id or not away_team_id:
                    continue
                # Only skip if no pitcher data either — can't score without pitcher
                if not home_pitcher.get("id") and not away_pitcher.get("id"):
                    continue
                # Use roster as projected lineup
                try:
                    home_roster = await get_team_roster(session, home_team_id)
                    away_roster = await get_team_roster(session, away_team_id)
                    home_lineup = [p.get("person", {}) for p in home_roster
                                  if p.get("position", {}).get("type") != "Pitcher"][:9]
                    away_lineup = [p.get("person", {}) for p in away_roster
                                  if p.get("position", {}).get("type") != "Pitcher"][:9]
                    is_projected = True
                except:
                    continue
            else:
                is_projected = False

            is_projected = False  # Default — will be set to True if using roster
            fp = game_fingerprint(game, home_lineup, away_lineup)
            if states.get(game_id) == fp:
                continue

            change = ""
            prev = states.get(game_id, "")
            if prev:
                pp = prev.split("_")
                cp = fp.split("_")
                if pp[0] != cp[0]: change = f"\n🚨 PITCHER CHANGE — {home_abbrev}"
                elif pp[1] != cp[1]: change = f"\n🚨 PITCHER CHANGE — {away_abbrev}"
                else: change = "\n🔄 LINEUP CHANGE"

            new_states[game_id] = fp

            gt_str = game.get("gameDate", "")
            try:
                dt = datetime.datetime.fromisoformat(gt_str.replace("Z", "+00:00"))
                et_dt = dt + datetime.timedelta(hours=-4)
                local_time = et_dt.strftime("%-I:%M %p ET")
                game_dt = dt
            except:
                local_time = "TBD"
                game_dt = None

            def dp():
                return {
                    "hr9": 1.2, "barrel_against": 8.0, "hh_against": 34,
                    "era": 4.00, "whip": 1.30, "k9": 7.0,
                    "last3_era": 4.00, "hand": "R", "splits": None
                }

            home_p = await get_pitcher_stats(session, home_pitcher.get("id")) if home_pitcher.get("id") else dp()
            away_p = await get_pitcher_stats(session, away_pitcher.get("id")) if away_pitcher.get("id") else dp()
            if not home_p: home_p = dp()
            if not away_p: away_p = dp()

            home_p_name = home_pitcher.get("fullName", "TBD")
            away_p_name = away_pitcher.get("fullName", "TBD")

            async def score_lineup(lineup, opp_p, park):
                ranked = []
                for i, player in enumerate(lineup):
                    pid = player.get("id")
                    pname = player.get("fullName", "Unknown")
                    if not pid: continue
                    b = await get_batter_stats(session, pid)
                    if not b or b.get("hr", 0) < 2: continue
                    splits = opp_p.get("splits")
                    bhand = b.get("hand", "R")
                    platoon_hr9 = opp_p["hr9"]
                    if splits:
                        if bhand == "R": platoon_hr9 = splits.get("rhb_hr9", opp_p["hr9"])
                        elif bhand == "L": platoon_hr9 = splits.get("lhb_hr9", opp_p["hr9"])
                        else: platoon_hr9 = max(splits.get("rhb_hr9", 0), splits.get("lhb_hr9", 0))
                    conf = calculate_confidence(b, opp_p, park, i+1, splits)
                    odds_data = get_odds(pname)
                    fd_odds = mgm_odds = ev_score = None
                    if odds_data:
                        fd_odds = odds_data["fd"]
                        mgm_odds = odds_data["mgm"]
                        ev_score = calc_ev(conf, fd_odds)
                    ranked.append({
                        "name": pname,
                        "conf": conf,
                        "hand": bhand,
                        "platoon_hr9": platoon_hr9,
                        "hr7": b.get("hr7", 0),
                        "hr": b.get("hr", 0),
                        "fd_odds": fd_odds,
                        "mgm_odds": mgm_odds,
                        "ev_score": ev_score,
                        "p_vulnerable": opp_p.get("hr9", 1.2) >= 1.2 or opp_p.get("barrel_against", 8) >= 8,
                        "game_dt": game_dt,
                        "savant_real": b.get("savant_real", False),
                        "barrel": b.get("barrel", 0),
                        "ev": b.get("ev", 0),
                        "hh": b.get("hh", 0),
                    })
                ranked.sort(key=lambda x: x["conf"], reverse=True)
                return ranked

            away_ranked = await score_lineup(away_lineup, home_p, home_abbrev)
            home_ranked = await score_lineup(home_lineup, away_p, home_abbrev)

            if not away_ranked and not home_ranked:
                continue

            def make_lines(ranked):
                lines = []
                for i, p in enumerate(ranked):
                    # 🔥 for hot streak, ✅ for good spot, nothing otherwise
                    if p["hr7"] >= HOT_MIN:
                        badge = "🔥"
                    elif p["conf"] >= 70:
                        badge = "✅"
                    else:
                        badge = ""

                    # Odds display
                    odds_str = ""
                    if p.get("fd_odds"):
                        fd = f"+{p['fd_odds']}" if p['fd_odds'] > 0 else str(p['fd_odds'])
                        mgm = f"+{p['mgm_odds']}" if p.get('mgm_odds') and p['mgm_odds'] > 0 else ""
                        odds_str = f" | FD:{fd}"
                        if mgm:
                            odds_str += f" MGM:{mgm}"

                    line = f"{i+1}. {p['name']} ({p['hand']}) — {p['conf']}% {badge}{odds_str}".strip()
                    # Only show Statcast metrics if real — not estimated
                    if p.get("savant_real"):
                        line += f"\n   Barrel:{p.get('barrel',0):.1f}% EV:{p.get('ev',0):.1f}mph HH:{p.get('hh',0):.1f}%"

                    # Tiebreaker only on #1 pick
                    if i == 0 and len(ranked) > 1:
                        _, partner, decision = resolve_tiebreaker(p, ranked[1])
                        if decision == "VALUE_SWAP":
                            p2 = ranked[1]
                            fd2 = f"+{p2['fd_odds']}" if p2.get('fd_odds') and p2['fd_odds'] > 0 else "N/A"
                            line += f"\n   💰 VALUE EDGE: #{2} {p2['name']} {fd2} — better odds, consider both"
                        elif decision == "INTERCHANGEABLE":
                            line += f"\n   🔄 INTERCHANGE: {ranked[1]['name']} ({ranked[1]['conf']}%)"
                        elif "PLATOON" in decision:
                            line += f"\n   ⚔️ PLATOON LOCKS: {p['platoon_hr9']} vs {ranked[1]['platoon_hr9']} HR/9"

                    lines.append(line)
                return lines

            away_lines = make_lines(away_ranked)
            home_lines = make_lines(home_ranked)

            # Game top pick — apply tiebreaker
            all_cands = sorted(away_ranked + home_ranked, key=lambda x: x["conf"], reverse=True)
            game_top = None
            game_top_partner = None

            if all_cands:
                winner, partner, decision = resolve_tiebreaker(
                    all_cands[0],
                    all_cands[1] if len(all_cands) > 1 else all_cands[0]
                )
                t = winner
                team = away_abbrev if t in away_ranked else home_abbrev
                vs = home_p_name if t in away_ranked else away_p_name
                game_top = {**t, "team": team, "vs": vs,
                           "matchup": f"{away_abbrev} @ {home_abbrev}"}
                all_top_picks.append(game_top)

                # Add partner to pool if interchangeable
                if partner and decision in ["VALUE_SWAP", "INTERCHANGEABLE", "PLATOON_SWAP"]:
                    p2_team = away_abbrev if partner in away_ranked else home_abbrev
                    p2_vs = home_p_name if partner in away_ranked else away_p_name
                    game_top_partner = {**partner, "team": p2_team, "vs": p2_vs,
                                       "matchup": f"{away_abbrev} @ {home_abbrev}",
                                       "is_alt": True}
                    all_top_picks.append(game_top_partner)

            # Pitcher splits display
            def splits_line(p_stats):
                s = p_stats.get("splits")
                if not s: return ""
                gap = platoon_gap_label(s["rhb_hr9"], s["lhb_hr9"])
                vuln = "RHB" if s["rhb_hr9"] > s["lhb_hr9"] else "LHB"
                return (
                    f"  vs RHB: {s['rhb_avg']:.3f} AVG / {s['rhb_hr9']} HR9\n"
                    f"  vs LHB: {s['lhb_avg']:.3f} AVG / {s['lhb_hr9']} HR9\n"
                    f"  ⚔️ {gap} gap — vulnerable to {vuln}"
                )

            lineup_status = "⏰ PROJECTED" if is_projected else "✅ CONFIRMED"
            msg = f"""
⚾ {away_abbrev} @ {home_abbrev} — {local_time} | {lineup_status}{change}
🏟️ {home_name}
━━━━━━━━━━━━━━━━━━━━━━
🔱 PITCHING MATCHUP
━━━━━━━━━━━━━━━━━━━━━━
{away_abbrev} → {away_p_name} {vuln_flag(away_p['hr9'], away_p['barrel_against'])}
• HR/9:{away_p['hr9']} ERA:{away_p['era']} WHIP:{away_p['whip']} K/9:{away_p['k9']}
• L3 ERA:{away_p['last3_era']} {pitcher_trend(away_p['era'],away_p['last3_era'])}
{splits_line(away_p)}
{home_abbrev} → {home_p_name} {vuln_flag(home_p['hr9'], home_p['barrel_against'])}
• HR/9:{home_p['hr9']} ERA:{home_p['era']} WHIP:{home_p['whip']} K/9:{home_p['k9']}
• L3 ERA:{home_p['last3_era']} {pitcher_trend(home_p['era'],home_p['last3_era'])}
{splits_line(home_p)}
━━━━━━━━━━━━━━━━━━━━━━
📊 {away_abbrev} vs {home_p_name}
{chr(10).join(away_lines) if away_lines else "Lineup pending"}
━━━━━━━━━━━━━━━━━━━━━━
📊 {home_abbrev} vs {away_p_name}
{chr(10).join(home_lines) if home_lines else "Lineup pending"}
━━━━━━━━━━━━━━━━━━━━━━
🏆 GAME TOP PICK: {game_top['name']} ({game_top['team']}) — {game_top['conf']}%
━━━━━━━━━━━━━━━━━━━━━━""".strip()

            await bot.send_message(chat_id=CHAT_ID, text=msg)
            await asyncio.sleep(2)

    # ============================================================
    #  PARLAYS
    # ============================================================
    if not parlay_sent and all_top_picks and first_game_time:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_et = now_utc + datetime.timedelta(hours=-4)
        now_et_hour = now_et.hour
        mins_to_first = (first_game_time.replace(tzinfo=datetime.timezone.utc) - now_utc).total_seconds() / 60

        should_send = (10 <= mins_to_first <= 35) or (now_et_hour >= 12 and mins_to_first <= 120)

        if should_send:
            # Deduplicate
            seen = set()
            pool = []
            for p in all_top_picks:
                if p["name"] not in seen:
                    seen.add(p["name"])
                    if p.get("conf", 0) >= PARLAY_MIN_CONF:
                        pool.append(p)

            # Add lower ranked players meeting at least 1 criterion
            for p in all_top_picks:
                if p["name"] not in seen and p.get("conf", 0) >= 55:
                    crit = 0
                    if p.get("hr7", 0) >= HOT_MIN: crit += 1
                    if p.get("platoon_hr9", 1.2) >= 1.2: crit += 1
                    if p.get("p_vulnerable", False): crit += 1
                    if crit >= 1:
                        seen.add(p["name"])
                        pool.append(p)

            if len(pool) < 2:
                return new_states, parlay_sent

            # STANDARD: confidence + slight EV boost when close
            def std_sort(p):
                conf = p.get("conf", 0)
                ev = p.get("ev_score") or 0
                return conf + (ev * 0.1 if ev > 0 else 0)

            # EV: pure value
            def ev_sort(p):
                ev = p.get("ev_score") or 0
                fd = p.get("fd_odds") or 300
                return ev + (fd / 100)

            std = sorted(pool, key=std_sort, reverse=True)
            ev_sorted = sorted(pool, key=ev_sort, reverse=True)

            # EV 3-leg uses different players
            std_names = {p["name"] for p in std[:4]}
            ev_alt = [p for p in ev_sorted if p["name"] not in std_names]
            if len(ev_alt) < 3:
                ev_alt = ev_sorted

            # Detect full slate vs same window
            game_times = [p.get("game_dt") for p in std[:4] if p.get("game_dt")]
            is_full_slate = False
            if len(game_times) >= 2:
                earliest = min(game_times)
                latest = max(game_times)
                spread = (latest.replace(tzinfo=datetime.timezone.utc) - earliest.replace(tzinfo=datetime.timezone.utc)).total_seconds() / 3600
                is_full_slate = spread >= 3

            slate_label = "🌅➡️🌙 FULL SLATE" if is_full_slate else "⚡ SAME WINDOW"

            def leg(p, i):
                fd = f"+{p['fd_odds']}" if p.get("fd_odds") and p["fd_odds"] > 0 else "N/A"
                mgm = f"+{p['mgm_odds']}" if p.get("mgm_odds") and p["mgm_odds"] > 0 else "N/A"
                ev_str = f" | EV:+{p['ev_score']}%" if p.get("ev_score") and p["ev_score"] > 0 else ""
                hot = " 🔥" if p.get("hr7", 0) >= HOT_MIN else ""
                alt = " ↔️" if p.get("is_alt") else ""
                gt = p.get("game_dt")
                time_str = ""
                if gt:
                    try:
                        et = gt + datetime.timedelta(hours=-4)
                        time_str = f" | {et.strftime('%-I:%M %p ET')}"
                    except:
                        pass
                return (
                    f"{i}. {p['name']} ({p.get('hand','')}) — {p['conf']}%{hot}{alt}\n"
                    f"   ⚾ vs {p.get('vs','?')} | {p.get('matchup','?')}{time_str}\n"
                    f"   FD:{fd} MGM:{mgm}{ev_str}"
                )

            if len(std) >= 2:
                msg = f"🎯 PARLAYS OF THE DAY\n{slate_label} | 🚫 No chalk bias\n━━━━━━━━━━━━━━━━━━━━━━"

                msg += "\n\n2️⃣ 2-LEG\n"
                msg += "\n".join(leg(std[i], i+1) for i in range(min(2, len(std))))

                if len(std) >= 3:
                    msg += "\n\n3️⃣ 3-LEG\n"
                    msg += "\n".join(leg(std[i], i+1) for i in range(min(3, len(std))))

                if len(std) >= 4:
                    msg += "\n\n4️⃣ 4-LEG\n"
                    msg += "\n".join(leg(std[i], i+1) for i in range(min(4, len(std))))

                if len(ev_alt) >= 3:
                    msg += "\n\n💰 EV 3-LEG (VALUE)\n"
                    msg += "\n".join(leg(ev_alt[i], i+1) for i in range(min(3, len(ev_alt))))

                msg += "\n━━━━━━━━━━━━━━━━━━━━━━"
                await bot.send_message(chat_id=CHAT_ID, text=msg)
                parlay_sent = True

    return new_states, parlay_sent

# ============================================================
#  MAIN LOOP
# ============================================================
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID,
        text="✅ HR SCOUT V5 — FINAL\n\n"
             "📊 Scores recalibrated — top plays 80-90%\n"
             "💰 Within 3%: higher odds wins the spot\n"
             "🔥 Hot streak (3+ HR last 7 days)\n"
             "✅ Good matchup spot\n"
             "↔️ Alt/interchangeable player\n"
             "🎯 4 parlays before first pitch\n"
             "⚡ Same window or 🌅 Full slate\n\n"
             "Waiting for confirmed lineups...")
    await asyncio.sleep(2)

    states = {}
    parlay_sent = False
    last_date = None

    last_update_id = 0

    while True:
        now = datetime.datetime.now()
        today = now.date()
        if last_date != today:
            parlay_sent = False
            last_date = today
            states = {}

        # Check for incoming Telegram messages (/sheet command)
        try:
            updates = await bot.get_updates(offset=last_update_id + 1, timeout=1)
            for update in updates:
                last_update_id = update.update_id
                msg = update.message
                if msg and msg.text:
                    text = msg.text.strip()
                    if text.startswith("/sheet"):
                        sheet_text = text[6:].strip()
                        if sheet_text:
                            await handle_sheet_command(bot, sheet_text)
                        else:
                            await bot.send_message(
                                chat_id=CHAT_ID,
                                text="📋 Paste Tommy\'s sheet after /sheet\n\nExample:\n/sheet\n[paste sheet here]"
                            )
        except Exception:
            pass

        try:
            states, parlay_sent = await run_scan(bot, states, parlay_sent)
        except Exception as e:
            await bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Error: {str(e)[:200]}")

        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())

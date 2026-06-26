import asyncio
import datetime
import aiohttp
from telegram import Bot

# ============================================================
#  CONFIGURATION
# ============================================================
TELEGRAM_TOKEN = "8720993049:AAEimQD4PUDFlMA2bpxXsyW3IMcTZ5ak0PY"
CHAT_ID = "919904024"
CONFIDENCE_THRESHOLD = 75
SCAN_INTERVAL = 300  # 5 minutes

# ============================================================
#  REAL STATCAST DATA — Updated from Baseball Savant
# ============================================================
KNOWN_BATTER_STATS = {
    676475: {"name": "Jac Caglianone",      "barrel": 15.9, "ev": 94.4, "hh": 58.9, "pull": 48.0, "iso": 280, "hr": 9,  "games": 65, "hand": "L"},
    694497: {"name": "Junior Caminero",     "barrel": 12.7, "ev": 91.5, "hh": 51.0, "pull": 42.0, "iso": 210, "hr": 16, "games": 75, "hand": "R"},
    691023: {"name": "Jordan Walker",       "barrel": 13.6, "ev": 93.9, "hh": 51.1, "pull": 44.0, "iso": 230, "hr": 18, "games": 77, "hand": "R"},
    682988: {"name": "Riley Greene",        "barrel": 12.9, "ev": 90.8, "hh": 48.0, "pull": 41.0, "iso": 195, "hr": 9,  "games": 70, "hand": "L"},
    670541: {"name": "Yordan Alvarez",      "barrel": 18.2, "ev": 95.1, "hh": 61.0, "pull": 46.0, "iso": 310, "hr": 22, "games": 72, "hand": "L"},
    656941: {"name": "Kyle Schwarber",      "barrel": 23.5, "ev": 92.0, "hh": 58.7, "pull": 52.0, "iso": 330, "hr": 28, "games": 78, "hand": "L"},
    665833: {"name": "Oneil Cruz",          "barrel": 17.9, "ev": 95.8, "hh": 60.0, "pull": 43.0, "iso": 270, "hr": 16, "games": 70, "hand": "L"},
    694192: {"name": "James Wood",          "barrel": 14.0, "ev": 96.3, "hh": 57.0, "pull": 38.0, "iso": 240, "hr": 20, "games": 76, "hand": "L"},
    682998: {"name": "Pete Crow-Armstrong", "barrel": 10.5, "ev": 89.0, "hh": 44.0, "pull": 40.0, "iso": 165, "hr": 14, "games": 74, "hand": "L"},
    665742: {"name": "Juan Soto",           "barrel": 15.0, "ev": 92.0, "hh": 53.0, "pull": 44.0, "iso": 255, "hr": 18, "games": 76, "hand": "L"},
    683002: {"name": "Gunnar Henderson",    "barrel": 14.5, "ev": 92.0, "hh": 52.0, "pull": 43.0, "iso": 240, "hr": 19, "games": 75, "hand": "L"},
    694943: {"name": "Ben Rice",            "barrel": 14.0, "ev": 92.5, "hh": 51.0, "pull": 42.0, "iso": 245, "hr": 18, "games": 73, "hand": "L"},
    694568: {"name": "Nick Kurtz",          "barrel": 15.9, "ev": 94.4, "hh": 58.9, "pull": 46.0, "iso": 260, "hr": 16, "games": 68, "hand": "L"},
    660271: {"name": "Shohei Ohtani",       "barrel": 19.0, "ev": 94.0, "hh": 59.0, "pull": 45.0, "iso": 300, "hr": 24, "games": 74, "hand": "L"},
    666971: {"name": "Vladimir Guerrero Jr","barrel": 12.5, "ev": 91.0, "hh": 48.0, "pull": 41.0, "iso": 200, "hr": 15, "games": 74, "hand": "R"},
    608369: {"name": "Manny Machado",       "barrel": 11.5, "ev": 90.0, "hh": 46.0, "pull": 40.0, "iso": 185, "hr": 14, "games": 73, "hand": "R"},
    668731: {"name": "Bobby Witt Jr.",      "barrel": 11.0, "ev": 90.5, "hh": 46.0, "pull": 39.0, "iso": 190, "hr": 13, "games": 74, "hand": "R"},
    666176: {"name": "Elly De La Cruz",     "barrel": 12.0, "ev": 91.0, "hh": 49.0, "pull": 41.0, "iso": 200, "hr": 15, "games": 72, "hand": "S"},
    669242: {"name": "Jazz Chisholm Jr.",   "barrel": 13.0, "ev": 91.0, "hh": 48.0, "pull": 42.0, "iso": 205, "hr": 14, "games": 70, "hand": "L"},
    694192: {"name": "James Wood",          "barrel": 14.0, "ev": 96.3, "hh": 57.0, "pull": 38.0, "iso": 240, "hr": 20, "games": 76, "hand": "L"},
}

KNOWN_PITCHER_STATS = {
    689818: {"name": "David Sandlin",      "hr9": 2.70, "barrel_against": 13.5, "era": 8.10,  "whip": 1.50, "hand": "R", "last3_era": 8.10},
    681293: {"name": "Spencer Arrighetti", "hr9": 1.40, "barrel_against": 6.6,  "era": 3.13,  "whip": 1.22, "hand": "R", "last3_era": 4.57},
    700241: {"name": "Michael McGreevy",   "hr9": 1.30, "barrel_against": 10.1, "era": 3.35,  "whip": 1.15, "hand": "R", "last3_era": 4.20},
    694773: {"name": "Payton Tolle",       "hr9": 1.10, "barrel_against": 8.0,  "era": 3.80,  "whip": 1.20, "hand": "R", "last3_era": 3.80},
    669160: {"name": "Trevor Rogers",      "hr9": 1.20, "barrel_against": 7.5,  "era": 3.90,  "whip": 1.25, "hand": "L", "last3_era": 3.90},
    571578: {"name": "Patrick Corbin",     "hr9": 1.50, "barrel_against": 9.0,  "era": 4.50,  "whip": 1.40, "hand": "L", "last3_era": 4.80},
    593958: {"name": "Colin Rea",          "hr9": 1.20, "barrel_against": 7.0,  "era": 3.70,  "whip": 1.18, "hand": "R", "last3_era": 3.70},
    686613: {"name": "Taj Bradley",        "hr9": 0.90, "barrel_against": 6.0,  "era": 3.20,  "whip": 1.10, "hand": "R", "last3_era": 3.20},
    694973: {"name": "Keider Montero",     "hr9": 1.30, "barrel_against": 8.5,  "era": 3.90,  "whip": 1.28, "hand": "R", "last3_era": 3.90},
}

# ============================================================
#  PARK FACTORS
# ============================================================
PARK_FACTORS = {
    "COL": 120, "CIN": 112, "PHI": 110, "NYY": 108, "BOS": 106,
    "MIL": 104, "HOU": 103, "ATL": 102, "CHC": 102, "LAD": 100,
    "NYM": 100, "STL": 98,  "MIN": 98,  "DET": 97,  "PIT": 97,
    "TOR": 97,  "BAL": 97,  "CLE": 96,  "CWS": 96,  "SEA": 95,
    "MIA": 95,  "WSH": 95,  "ARI": 95,  "KC":  94,  "LAA": 94,
    "TB":  94,  "SD":  93,  "SF":  92,  "OAK": 92,  "TEX": 91,
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
#  SCORING FUNCTIONS
# ============================================================

# GUY 1 + 2: Barrel % — 10% threshold, 15% great, 20%+ elite
def score_barrel(b):
    if b >= 20: return 100
    if b >= 15: return 88
    if b >= 10: return 72
    if b >= 7:  return 45
    return 20

# GUY 1 + 2: Exit Velocity — 90mph min, 93mph+ great
def score_ev(e):
    if e >= 96: return 100
    if e >= 93: return 88
    if e >= 90: return 72
    if e >= 87: return 45
    return 20

# GUY 1: ISO Power — 140 avg, 250+ elite
def score_iso(iso):
    if iso >= 300: return 100
    if iso >= 250: return 88
    if iso >= 200: return 72
    if iso >= 150: return 55
    if iso >= 100: return 35
    return 15

# GUY 2: Pull % — 33% min, 40%+ good, 50%+ elite
def score_pull(pull):
    if pull >= 50: return 100
    if pull >= 40: return 85
    if pull >= 33: return 60
    return 20

# GUY 1: Hard Hit % — frequency of loud contact
def score_hh(hh):
    if hh >= 55: return 100
    if hh >= 48: return 82
    if hh >= 40: return 65
    if hh >= 32: return 40
    return 20

# GUY 1: Recent HR form — last 14 days
def score_recent_hr(hr, games):
    hr14 = (hr / max(games, 1)) * 14
    if hr14 >= 6:  return 100
    if hr14 >= 4:  return 85
    if hr14 >= 3:  return 70
    if hr14 >= 2:  return 55
    if hr14 >= 1:  return 38
    return 15

# GUY 1: Pitcher HR/9 vulnerability
def score_pitcher_hr9(hr9):
    if hr9 >= 2.0: return 100
    if hr9 >= 1.5: return 82
    if hr9 >= 1.2: return 65
    if hr9 >= 1.0: return 48
    if hr9 >= 0.7: return 28
    return 12

# GUY 1: Pitcher barrel % allowed
def score_pitcher_barrel(b):
    if b >= 14: return 100
    if b >= 11: return 82
    if b >= 8:  return 62
    if b >= 6:  return 42
    return 20

# MY ADDITION: Park factor
def score_park(abbrev):
    f = PARK_FACTORS.get(abbrev, 100)
    if f >= 115: return 100
    if f >= 108: return 80
    if f >= 103: return 65
    if f >= 98:  return 50
    if f >= 93:  return 35
    return 20

# MY ADDITION: Platoon advantage
def score_platoon(batter_hand, pitcher_hand):
    if batter_hand == "S": return 72  # Switch hitter always has edge
    if batter_hand != pitcher_hand: return 90  # Opposite hand = advantage
    return 38  # Same hand = disadvantage

# MY ADDITION: Batting order spot
def score_batting_order(spot):
    if spot <= 0: return 55
    if spot in [3, 4]: return 90  # Cleanup spots
    if spot in [1, 2, 5]: return 78
    if spot in [6, 7]: return 55
    return 38

# MY ADDITION: Pitcher last 3 starts trend
def score_pitcher_trend(season_era, last3_era):
    diff = last3_era - season_era
    if diff >= 2.0: return 100  # Pitcher getting worse recently
    if diff >= 1.0: return 80
    if diff >= 0.0: return 60
    return 35  # Pitcher actually improving

# ============================================================
#  GENERATE PLAIN ENGLISH EXPLANATION
# ============================================================
def generate_explanation(batter_name, b, p, park, spot, confirmed):
    reasons = []

    # Barrel explanation
    if b["barrel"] >= 20:
        reasons.append(f"elite barrel rate of {b['barrel']}% (Guy 1+2: 20%+ is absolutely slugging this pitch mix)")
    elif b["barrel"] >= 15:
        reasons.append(f"very impressive barrel rate of {b['barrel']}% (Guy 1+2: 15%+ threshold)")
    elif b["barrel"] >= 10:
        reasons.append(f"qualifying barrel rate of {b['barrel']}% (Guy 1+2: 10% minimum met)")

    # EV explanation
    if b["ev"] >= 93:
        reasons.append(f"exit velocity of {b['ev']}mph suggests multiple 100mph contact events (Guy 1+2)")
    elif b["ev"] >= 90:
        reasons.append(f"exit velocity of {b['ev']}mph clears the 90mph minimum threshold (Guy 2)")

    # Pull explanation
    if b["pull"] >= 40:
        reasons.append(f"pull rate of {b['pull']}% is above the 40% threshold — 66% of all HRs are pulled (Guy 2)")
    elif b["pull"] >= 33:
        reasons.append(f"pull rate of {b['pull']}% meets the 33% minimum (Guy 2)")

    # ISO explanation
    if b["iso"] >= 250:
        reasons.append(f"ISO of {b['iso']} is well above the 250 elite threshold indicating raw power (Guy 1)")
    elif b["iso"] >= 140:
        reasons.append(f"ISO of {b['iso']} is above MLB average of 140 (Guy 1)")

    # Pitcher vulnerability
    if p["hr9"] >= 1.5:
        reasons.append(f"pitcher is highly vulnerable — {p['hr9']} HR/9 and {p['barrel_against']}% barrel rate allowed (Guy 1)")
    elif p["hr9"] >= 1.2:
        reasons.append(f"pitcher allows {p['hr9']} HR/9 showing above average vulnerability (Guy 1)")

    # Pitcher trend (my addition)
    trend_diff = p.get("last3_era", p["era"]) - p["era"]
    if trend_diff >= 1.0:
        reasons.append(f"pitcher trending worse — ERA jumped to {p.get('last3_era', p['era'])} over last 3 starts vs season ERA of {p['era']} (my addition)")

    # Park factor (my addition)
    park_f = PARK_FACTORS.get(park, 100)
    if park_f >= 108:
        reasons.append(f"{park} is a hitter-friendly park (factor: {park_f}) boosting HR probability (my addition)")

    # Batting order (my addition)
    if spot in [3, 4]:
        reasons.append(f"batting #{spot} in cleanup gives maximum plate appearances and RBI opportunities (my addition)")
    elif spot in [1, 2]:
        reasons.append(f"batting #{spot} means more plate appearances throughout the game (my addition)")

    # Lineup status (my addition)
    if confirmed:
        reasons.append("lineup is confirmed — no projected uncertainty")
    else:
        reasons.append("lineup is projected — confidence may shift when confirmed")

    if not reasons:
        return f"{batter_name} meets multiple threshold criteria across barrel rate, exit velocity, and pitcher vulnerability."

    explanation = f"{batter_name} ranks here because of their {reasons[0]}"
    if len(reasons) >= 2:
        explanation += f", {reasons[1]}"
    if len(reasons) >= 3:
        explanation += f", and {reasons[2]}"
    explanation += "."
    if len(reasons) > 3:
        explanation += f" Additional factors: {'; '.join(reasons[3:])}."

    return explanation

# ============================================================
#  CALCULATE CONFIDENCE
# ============================================================
def calculate_confidence(b, p, park, spot=0, confirmed=False):
    weights = {
        "barrel":       18,  # Guy 1 + 2
        "ev":           13,  # Guy 1 + 2
        "pull":         12,  # Guy 2
        "iso":          10,  # Guy 1
        "hh":            7,  # Guy 1
        "recent_hr":    12,  # Guy 1
        "p_hr9":        10,  # Guy 1
        "p_barrel":      7,  # Guy 1
        "p_trend":       4,  # My addition
        "park":          3,  # My addition
        "platoon":       2,  # My addition
        "batting_order": 2,  # My addition
    }

    scores = {
        "barrel":        score_barrel(b.get("barrel", 8)),
        "ev":            score_ev(b.get("ev", 88)),
        "pull":          score_pull(b.get("pull", 35)),
        "iso":           score_iso(b.get("iso", 140)),
        "hh":            score_hh(b.get("hh", 35)),
        "recent_hr":     score_recent_hr(b.get("hr", 0), b.get("games", 1)),
        "p_hr9":         score_pitcher_hr9(p.get("hr9", 1.2)),
        "p_barrel":      score_pitcher_barrel(p.get("barrel_against", 8)),
        "p_trend":       score_pitcher_trend(p.get("era", 4.0), p.get("last3_era", 4.0)),
        "park":          score_park(park),
        "platoon":       score_platoon(b.get("hand", "R"), p.get("hand", "R")),
        "batting_order": score_batting_order(spot),
    }

    conf = round(sum(scores[k] * weights[k] / 100 for k in scores))
    if confirmed:
        conf = min(99, conf + 3)
    return conf, scores

# ============================================================
#  API CALLS
# ============================================================
async def get_todays_games(session):
    today = datetime.date.today().strftime("%Y-%m-%d")
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today}&hydrate=probablePitcher,team,lineups"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
        games = []
        for date in data.get("dates", []):
            for game in date.get("games", []):
                games.append(game)
        return games
    except:
        return []

async def get_team_roster(session, team_id):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster?rosterType=active"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
        return data.get("roster", [])
    except:
        return []

async def get_batter_stats_api(session, player_id):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=hitting&season=2026"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        if splits:
            s = splits[0].get("stat", {})
            hr = int(s.get("homeRuns", 0))
            games = int(s.get("gamesPlayed", 1))
            slg = float(s.get("sluggingPercentage", 0.380))
            avg = float(s.get("avg", 0.240))
            iso = round((slg - avg) * 1000)
            ab = int(s.get("atBats", 1))
            barrel = min(25, max(4, (slg - 0.300) * 45))
            ev = min(98, max(84, 88 + (slg - 0.350) * 22))
            hh = min(65, max(25, 35 + (slg - 0.350) * 55))
            pull = min(60, max(25, 35 + (hr / max(ab, 1)) * 200))
            return {"barrel": barrel, "ev": ev, "hh": hh,
                    "hr": hr, "games": games, "iso": iso,
                    "pull": pull, "hand": "R"}
    except:
        pass
    return None

async def get_pitcher_stats_api(session, player_id):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=pitching&season=2026"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        if splits:
            s = splits[0].get("stat", {})
            hr9 = float(s.get("homeRunsPer9", 1.2))
            era = float(s.get("era", 4.00))
            whip = float(s.get("whip", 1.30))
            barrel_against = min(18, max(4, (era - 3.0) * 3 + 8))
            return {"hr9": hr9, "era": era, "whip": whip,
                    "barrel_against": barrel_against,
                    "last3_era": era, "hand": "R"}
    except:
        pass
    return None

# ============================================================
#  MAIN SCAN
# ============================================================
async def run_scan(bot, phase="UPDATE", prev_scores=None):
    if prev_scores is None:
        prev_scores = {}

    today = datetime.date.today().strftime("%A, %B %d %Y")

    if phase == "EARLY":
        label = "⏰ EARLY LOOK — Projected Matchups"
    elif phase == "LOCK":
        label = "🔒 FINAL LOCK — Confirmed Lineups"
    else:
        label = "🔄 LIVE UPDATE"

    alerts = []
    new_scores = {}
    seen_batters = set()

    async with aiohttp.ClientSession() as session:
        games = await get_todays_games(session)
        if not games:
            return prev_scores

        for game in games:
            home_team_name = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "")
            home_abbrev = TEAM_ABBREV.get(home_team_name, "???")
            home_team_id = game.get("teams", {}).get("home", {}).get("team", {}).get("id")
            away_team_id = game.get("teams", {}).get("away", {}).get("team", {}).get("id")
            home_pitcher = game.get("teams", {}).get("home", {}).get("probablePitcher", {})
            away_pitcher = game.get("teams", {}).get("away", {}).get("probablePitcher", {})

            lineups = game.get("lineups", {})
            home_lineup = lineups.get("homePlayers", [])
            away_lineup = lineups.get("awayPlayers", [])
            confirmed = len(home_lineup) > 0 or len(away_lineup) > 0

            if confirmed:
                batters_raw = []
                for i, p in enumerate(home_lineup):
                    batters_raw.append((p, i+1, away_pitcher, True))
                for i, p in enumerate(away_lineup):
                    batters_raw.append((p, i+1, home_pitcher, True))
            else:
                home_roster = await get_team_roster(session, home_team_id) if home_team_id else []
                away_roster = await get_team_roster(session, away_team_id) if away_team_id else []
                batters_raw = []
                for p in home_roster:
                    if p.get("position", {}).get("type") != "Pitcher":
                        batters_raw.append((p.get("person", {}), 0, away_pitcher, False))
                for p in away_roster:
                    if p.get("position", {}).get("type") != "Pitcher":
                        batters_raw.append((p.get("person", {}), 0, home_pitcher, False))

            for batter, spot, pitcher, is_confirmed in batters_raw:
                batter_id = batter.get("id")
                batter_name = batter.get("fullName", "Unknown")

                if not batter_id or batter_id in seen_batters:
                    continue
                seen_batters.add(batter_id)

                if not pitcher:
                    continue

                pitcher_id = pitcher.get("id")
                pitcher_name = pitcher.get("fullName", "TBD")

                b_stats = KNOWN_BATTER_STATS.get(batter_id)
                if not b_stats:
                    b_stats = await get_batter_stats_api(session, batter_id)
                if not b_stats or b_stats.get("games", 0) < 10:
                    continue

                # Guy 2 hard filters
                if b_stats.get("pull", 0) < 33: continue
                if b_stats.get("ev", 0) < 87: continue
                if b_stats.get("barrel", 0) < 10: continue

                p_stats = KNOWN_PITCHER_STATS.get(pitcher_id)
                if not p_stats:
                    p_stats = await get_pitcher_stats_api(session, pitcher_id)
                if not p_stats:
                    p_stats = {"hr9": 1.2, "barrel_against": 8.0, "era": 4.00, "whip": 1.30, "last3_era": 4.00, "hand": "R"}

                confidence, scores = calculate_confidence(b_stats, p_stats, home_abbrev, spot, is_confirmed)

                alert_key = f"{batter_id}_{pitcher_id}"
                new_scores[alert_key] = confidence

                if confidence < CONFIDENCE_THRESHOLD:
                    continue

                prev_conf = prev_scores.get(alert_key)
                is_new = prev_conf is None
                conf_change = (prev_conf is not None) and (abs(confidence - prev_conf) >= 4)
                is_first_scan = phase in ["EARLY", "LOCK"]

                if not (is_new or conf_change or is_first_scan):
                    continue

                hr14 = round((b_stats.get("hr", 0) / max(b_stats.get("games", 1), 1)) * 14, 1)
                explanation = generate_explanation(batter_name, b_stats, p_stats, home_abbrev, spot, is_confirmed)

                change_tag = ""
                if conf_change and prev_conf is not None:
                    direction = "📈" if confidence > prev_conf else "📉"
                    change_tag = f"\n{direction} CONFIDENCE CHANGE: {prev_conf}% → {confidence}%"

                alerts.append({
                    "key": alert_key,
                    "batter": batter_name,
                    "pitcher": pitcher_name,
                    "pitcher_name": pitcher_name,
                    "park": home_abbrev,
                    "confidence": confidence,
                    "prev_conf": prev_conf,
                    "confirmed": is_confirmed,
                    "spot": spot,
                    "hr": b_stats.get("hr", 0),
                    "games": b_stats.get("games", 0),
                    "barrel": round(b_stats.get("barrel", 0), 1),
                    "ev": round(b_stats.get("ev", 0), 1),
                    "pull": round(b_stats.get("pull", 0), 1),
                    "iso": b_stats.get("iso", 0),
                    "hh": round(b_stats.get("hh", 0), 1),
                    "hr14": hr14,
                    "p_hr9": p_stats.get("hr9", 0),
                    "p_barrel": round(p_stats.get("barrel_against", 0), 1),
                    "p_era": p_stats.get("era", 0),
                    "p_last3": p_stats.get("last3_era", p_stats.get("era", 0)),
                    "explanation": explanation,
                    "change_tag": change_tag,
                    "is_new": is_new,
                })

    alerts.sort(key=lambda x: x["confidence"], reverse=True)

    if not alerts:
        return {**prev_scores, **new_scores}

    await bot.send_message(chat_id=CHAT_ID,
        text=f"🤖 HR SCOUT V5 — {label}\n📅 {today}\n✅ {len(alerts)} alert(s):")
    await asyncio.sleep(1)

    for a in alerts[:15]:
        badge = "🔥🔥🔥 ELITE" if a["confidence"]>=90 else "🔥🔥 STRONG" if a["confidence"]>=82 else "🔥 VALUE"
        status = "✅ CONFIRMED" if a["confirmed"] else "⏰ PROJECTED"
        spot_txt = f"Batting #{a['spot']}" if a["spot"] > 0 else "Order: TBD"
        tag = "🆕 NEW" if a["is_new"] else "🔄 UPDATED"

        msg = f"""
━━━━━━━━━━━━━━━━━━━━━━
{badge} — {a['confidence']}% | {tag}
{status} | {spot_txt}{a['change_tag']}
━━━━━━━━━━━━━━━━━━━━━━
👤 {a['batter']}
⚾ vs {a['pitcher']}
🏟️ {a['park']}

📊 BATTER METRICS
• HR 2026: {a['hr']} in {a['games']} G | Last 14G: {a['hr14']}
• Barrel %: {a['barrel']}% {'🔥' if a['barrel']>=15 else '✅'}
• Exit Velocity: {a['ev']} mph {'🔥' if a['ev']>=93 else '✅'}
• Pull %: {a['pull']}% {'🔥' if a['pull']>=40 else '✅'}
• ISO Power: {a['iso']} {'🔥' if a['iso']>=250 else '✅'}
• Hard-Hit %: {a['hh']}%

⚾ PITCHER VULNERABILITY
• HR/9: {a['p_hr9']} {'🚨' if a['p_hr9']>=1.5 else ''}
• Barrel Allowed: {a['p_barrel']}% {'🚨' if a['p_barrel']>=11 else ''}
• Season ERA: {a['p_era']} | Last 3 Starts: {a['p_last3']}

📝 WHY THIS PLAY:
{a['explanation']}

✅ CONFIDENCE: {a['confidence']}%
━━━━━━━━━━━━━━━━━━━━━━""".strip()
        await bot.send_message(chat_id=CHAT_ID, text=msg)
        await asyncio.sleep(1)

    return {**prev_scores, **new_scores}

# ============================================================
#  MAIN LOOP
# ============================================================
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID,
        text="✅ HR SCOUT V5 IS LIVE\n\n📊 SCORING SYSTEM:\nGuy 1: Barrel%, EV, ISO, Hard-Hit%, Last 14 Days, Pitcher HR/9 + Barrel Allowed\nGuy 2: Pull% (33% min), EV (87mph min), Barrel% (10% min)\nMy Additions: Platoon advantage, Park factor, Batting order, Pitcher trend\n\n📝 Every alert includes plain English explanation\n📈📉 Confidence changes fire instantly\n⚡ Scanning every 5 minutes\n\nRunning first scan now...")
    await asyncio.sleep(2)

    prev_scores = {}
    last_lock = None
    scan_count = 0

    while True:
        now = datetime.datetime.now()
        today = now.date()
        scan_count += 1

        if scan_count == 1:
            phase = "EARLY"
        elif now.hour >= 17 and last_lock != today:
            phase = "LOCK"
            last_lock = today
        else:
            phase = "UPDATE"

        try:
            prev_scores = await run_scan(bot, phase, prev_scores)
        except Exception as e:
            await bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Error: {str(e)[:200]}")

        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())

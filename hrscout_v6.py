import asyncio
import datetime
import aiohttp
from telegram import Bot

TELEGRAM_TOKEN = "8720993049:AAEimQD4PUDFlMA2bpxXsyW3IMcTZ5ak0PY"
CHAT_ID = "919904024"
SCAN_INTERVAL = 300  # 5 minutes
MIN_DISPLAY = 55     # Fix #1: minimum display threshold
HOT_STREAK_MIN = 3   # Fix #2: hot flag only 3+ HR last 7 days
PARLAY_HOUR = 12     # Fix #8: parlay fires at noon ET

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
#  FIX #6: EV SCRAPER — fantasyteamadvice.com
#  Pulls FanDuel + BetMGM HR odds for EV calculation
# ============================================================
hr_odds_cache = {}

async def load_hr_odds(session):
    global hr_odds_cache
    url = "https://fantasyteamadvice.com/mlb/props/home-runs"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            html = await resp.text()
        import re
        pattern = r"<td[^>]*>([A-Za-z '.]+)</td>[^<]*<td[^>]*>([+\-]\d+)</td>[^<]*<td[^>]*>([+\-]\d+)</td>"
        matches = re.findall(pattern, html)
        for match in matches:
            try:
                name = match[0].strip()
                fd_odds = int(match[1])
                mgm_odds = int(match[2])
                if name and len(name) > 3:
                    hr_odds_cache[name.lower()] = {"fd": fd_odds, "mgm": mgm_odds}
            except:
                continue
    except:
        pass

def get_player_odds(name):
    """Get FD and BetMGM odds for a player."""
    key = name.lower()
    # Try exact match first
    if key in hr_odds_cache:
        return hr_odds_cache[key]
    # Try last name match
    last = key.split()[-1] if key.split() else ""
    for k, v in hr_odds_cache.items():
        if last and last in k:
            return v
    return None

def american_to_prob(odds):
    """Convert American odds to implied probability."""
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)

def calculate_ev(confidence_pct, odds):
    """
    Calculate Expected Value.
    EV = (our probability - market implied probability)
    Positive EV = value bet. Higher = better value.
    """
    our_prob = confidence_pct / 100
    market_prob = american_to_prob(odds)
    return round((our_prob - market_prob) * 100, 1)

# ============================================================
#  BASEBALL SAVANT CACHE
# ============================================================
savant_cache = {}

async def load_savant_data(session):
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
                values = line.split(",")
                row = dict(zip(headers, values))
                pid = row.get("player_id", "").strip().strip('"')
                if pid:
                    savant_cache[pid] = row
            except:
                continue
    except:
        pass

async def get_savant_stats(player_id):
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
#  SCORING — Fix #5: Recalibrated for wider spread
# ============================================================
def score_barrel(b):
    if b >= 20: return 100
    if b >= 15: return 90
    if b >= 10: return 75
    if b >= 7:  return 55
    if b >= 5:  return 35
    return 15

def score_ev(e):
    if e >= 96: return 100
    if e >= 93: return 90
    if e >= 90: return 75
    if e >= 87: return 55
    if e >= 85: return 35
    return 15

def score_hh(hh):
    if hh >= 55: return 100
    if hh >= 48: return 85
    if hh >= 40: return 68
    if hh >= 32: return 45
    return 20

def score_flyball(fb):
    if fb >= 50: return 100
    if fb >= 42: return 85
    if fb >= 35: return 68
    if fb >= 28: return 45
    return 20

def score_iso(iso):
    if iso >= 300: return 100
    if iso >= 250: return 88
    if iso >= 200: return 72
    if iso >= 150: return 55
    if iso >= 100: return 35
    return 15

def score_pull(pull):
    if pull >= 50: return 100
    if pull >= 40: return 85
    if pull >= 33: return 65
    if pull >= 25: return 40
    return 15

def score_recent_hr(hr, games):
    hr14 = (hr / max(games, 1)) * 14
    if hr14 >= 6: return 100
    if hr14 >= 4: return 85
    if hr14 >= 3: return 70
    if hr14 >= 2: return 52
    if hr14 >= 1: return 35
    return 15

def score_batter_form(avg7, hr7):
    if hr7 >= 4: return 100
    if hr7 >= 3: return 88
    if hr7 >= 2: return 72
    if hr7 >= 1 and avg7 >= 0.300: return 60
    if hr7 >= 1: return 50
    if avg7 >= 0.320: return 40
    if avg7 >= 0.260: return 28
    return 12

def score_pitcher_hr9(hr9):
    if hr9 >= 2.0: return 100
    if hr9 >= 1.5: return 85
    if hr9 >= 1.2: return 68
    if hr9 >= 1.0: return 50
    if hr9 >= 0.7: return 30
    return 12

def score_pitcher_barrel(b):
    if b >= 14: return 100
    if b >= 11: return 85
    if b >= 8:  return 65
    if b >= 6:  return 45
    return 20

def score_pitcher_form(last3, era):
    diff = last3 - era
    if diff >= 2.5: return 100
    if diff >= 1.5: return 85
    if diff >= 0.5: return 65
    if diff >= -0.5: return 50
    if diff >= -1.5: return 32
    return 15

def score_platoon_splits(bhand, splits):
    if not splits:
        return 55
    if bhand == "S":
        hr9 = max(splits.get("rhb_hr9", 1.2), splits.get("lhb_hr9", 1.2))
    elif bhand == "R":
        hr9 = splits.get("rhb_hr9", 1.2)
    else:
        hr9 = splits.get("lhb_hr9", 1.2)
    if hr9 >= 2.0: return 100
    if hr9 >= 1.5: return 85
    if hr9 >= 1.2: return 70
    if hr9 >= 0.9: return 52
    if hr9 >= 0.6: return 32
    return 15

def score_park(abbrev):
    f = PARK_FACTORS.get(abbrev, 100)
    if f >= 115: return 100
    if f >= 108: return 82
    if f >= 103: return 68
    if f >= 98:  return 52
    if f >= 93:  return 35
    return 18

def score_batting_order(spot):
    if spot <= 0: return 55
    if spot in [3, 4]: return 92
    if spot in [1, 2, 5]: return 78
    if spot in [6, 7]: return 55
    return 35

def calculate_confidence(b, p, park, spot=0, splits=None):
    # Fix #6: Situation weighted heavily over reputation
    weights = {
        "p_hr9":         12,  # Pitcher vulnerability
        "platoon":       12,  # Real platoon splits
        "p_form":        10,  # Pitcher recent trend
        "batter_form":   10,  # Batter hot last 7 days
        "p_barrel":       8,  # Barrel allowed
        "barrel":        10,  # Guy 1+2
        "ev":             8,  # Guy 1+2
        "hard_hit":       5,  # Guy 1
        "flyball":        5,  # Guy 1
        "pull":           5,  # Guy 2
        "iso":            3,  # Reduced — limits chalk bias
        "recent_hr":      5,  # Season HR rate
        "park":           4,  # Park factor
        "batting_order":  3,  # Lineup spot
    }
    scores = {
        "p_hr9":        score_pitcher_hr9(p.get("hr9", 1.2)),
        "platoon":      score_platoon_splits(b.get("hand", "R"), splits),
        "p_form":       score_pitcher_form(p.get("last3_era", 4.0), p.get("era", 4.0)),
        "batter_form":  score_batter_form(b.get("avg7", 0.250), b.get("hr7", 0)),
        "p_barrel":     score_pitcher_barrel(p.get("barrel_against", 8)),
        "barrel":       score_barrel(b.get("barrel", 8)),
        "ev":           score_ev(b.get("ev", 88)),
        "hard_hit":     score_hh(b.get("hh", 35)),
        "flyball":      score_flyball(b.get("fb", 35)),
        "pull":         score_pull(b.get("pull", 35)),
        "iso":          score_iso(b.get("iso", 140)),
        "recent_hr":    score_recent_hr(b.get("hr", 0), b.get("games", 1)),
        "park":         score_park(park),
        "batting_order": score_batting_order(spot),
    }
    return round(sum(scores[k] * weights[k] / 100 for k in scores))

def pitcher_trend(era, last3):
    diff = last3 - era
    if diff >= 1.5: return "📈 TRENDING WORSE"
    if diff >= 0.5: return "⚠️ SLIGHTLY WORSE"
    if diff <= -1.5: return "📉 IMPROVING"
    if diff <= -0.5: return "✅ SLIGHTLY BETTER"
    return "➡️ STABLE"

def vuln_flag(hr9, barrel):
    if hr9 >= 1.5 or barrel >= 11: return "🚨 VULNERABLE"
    if hr9 >= 1.2 or barrel >= 8: return "⚠️ ELEVATED RISK"
    return "✅ SOLID"

def platoon_gap(rhb, lhb):
    g = abs(rhb - lhb)
    if g >= 0.8: return "MASSIVE"
    if g >= 0.4: return "SIGNIFICANT"
    if g >= 0.2: return "MODERATE"
    return "MINIMAL"

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
                # Fix #3: Filter out games past midnight ET
                gt = game.get("gameDate", "")
                try:
                    dt = datetime.datetime.fromisoformat(gt.replace("Z", "+00:00"))
                    hour_et = (dt.hour - 4) % 24  # Rough ET conversion
                    if hour_et >= 1 and hour_et <= 5:  # 1am-5am ET = skip
                        continue
                except:
                    pass
                games.append(game)
        return games
    except:
        return []

async def get_batter_stats(session, player_id):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season,lastXGames&group=hitting&season=2026&gameType=R"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
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
        fb = min(55, max(22, 30 + (hr / max(ab, 1)) * 150 + (slg - 0.350) * 30))
        pull = min(60, max(25, 37 + (hr / max(ab, 1)) * 160))
        barrel = min(25, max(3, (slg - 0.280) * 50))
        ev = min(98, max(83, 87 + (slg - 0.320) * 25))
        hh = min(65, max(22, 33 + (slg - 0.320) * 60))
        hr7 = int(recent.get("homeRuns", 0))
        avg7 = float(recent.get("avg", avg) or avg)
        savant = await get_savant_stats(player_id)
        if savant:
            if savant["barrel"] > 0: barrel = savant["barrel"]
            if savant["ev"] > 0: ev = savant["ev"]
            if savant["hh"] > 0: hh = savant["hh"]
        # Get hand
        hand = "R"
        try:
            async with session.get(f"https://statsapi.mlb.com/api/v1/people/{player_id}", timeout=aiohttp.ClientTimeout(total=8)) as r2:
                pd = await r2.json()
            hand = pd.get("people", [{}])[0].get("batSide", {}).get("code", "R")
        except:
            pass
        return {
            "barrel": barrel, "ev": ev, "hh": hh, "fb": fb,
            "hr": hr, "games": games, "iso": iso,
            "pull": pull, "hand": hand,
            "hr7": hr7, "avg7": avg7,
        }
    except:
        pass
    return None

async def get_pitcher_stats(session, player_id):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season,gameLog&group=pitching&season=2026&gameType=R"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
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
            async with session.get(f"https://statsapi.mlb.com/api/v1/people/{player_id}", timeout=aiohttp.ClientTimeout(total=8)) as r2:
                pd = await r2.json()
            hand = pd.get("people", [{}])[0].get("pitchHand", {}).get("code", "R")
        except:
            pass
        # Platoon splits
        splits_url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=statSplits&group=pitching&season=2026&sitCodes=vr,vl"
        rhb_hr9 = hr9
        lhb_hr9 = hr9
        rhb_slg = 0.400
        lhb_slg = 0.400
        rhb_avg = 0.250
        lhb_avg = 0.250
        try:
            async with session.get(splits_url, timeout=aiohttp.ClientTimeout(total=10)) as r3:
                sd = await r3.json()
            for block in sd.get("stats", []):
                for split in block.get("splits", []):
                    sit = split.get("split", {}).get("code", "")
                    s = split.get("stat", {})
                    hr = int(s.get("homeRuns", 0))
                    ip = float(s.get("inningsPitched", 1) or 1)
                    calc_hr9 = round((hr / max(ip, 1)) * 9, 2)
                    if sit == "vr":
                        rhb_hr9 = calc_hr9
                        rhb_slg = float(s.get("sluggingPercentage", 0.400) or 0.400)
                        rhb_avg = float(s.get("avg", 0.250) or 0.250)
                    elif sit == "vl":
                        lhb_hr9 = calc_hr9
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
#  TIEBREAKER — Only for #1 pick
# ============================================================
def resolve_tiebreaker(p1, p2):
    gap = abs(p1["conf"] - p2["conf"])
    if gap > 3:
        return p1, None, "CLEAR"

    p1_platoon = p1.get("platoon_hr9", 1.2)
    p2_platoon = p2.get("platoon_hr9", 1.2)
    platoon_diff = abs(p1_platoon - p2_platoon)

    # Check EV first if available
    p1_ev = p1.get("ev_score")
    p2_ev = p2.get("ev_score")
    if p1_ev is not None and p2_ev is not None:
        if abs(p1_ev - p2_ev) >= 5:
            winner = p1 if p1_ev >= p2_ev else p2
            loser = p2 if p1_ev >= p2_ev else p1
            return winner, loser, "EV_SWAP" if winner == p2 else "EV_WIN"

    if platoon_diff >= 0.4:
        if p1_platoon >= p2_platoon:
            return p1, p2, "PLATOON_WIN"
        else:
            return p2, p1, "PLATOON_SWAP"

    return p1, p2, "INTERCHANGEABLE"

# ============================================================
#  GAME STATE
# ============================================================
def game_state(game, home_lineup, away_lineup):
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
        # Load data sources
        await load_savant_data(session)
        await load_hr_odds(session)

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
                continue

            curr_state = game_state(game, home_lineup, away_lineup)
            prev_state = states.get(game_id)

            if prev_state == curr_state:
                continue

            # Detect change
            change = ""
            if prev_state:
                pp = prev_state.split("_")
                cp = curr_state.split("_")
                if pp[0] != cp[0]: change = f"\n🚨 PITCHER CHANGE — {home_abbrev} starter changed"
                elif pp[1] != cp[1]: change = f"\n🚨 PITCHER CHANGE — {away_abbrev} starter changed"
                else: change = f"\n🔄 LINEUP CHANGE"

            new_states[game_id] = curr_state

            gt = game.get("gameDate", "")
            try:
                dt = datetime.datetime.fromisoformat(gt.replace("Z", "+00:00"))
                local_time = dt.strftime("%-I:%M %p ET")
            except:
                local_time = "TBD"

            home_p = await get_pitcher_stats(session, home_pitcher.get("id")) if home_pitcher.get("id") else None
            away_p = await get_pitcher_stats(session, away_pitcher.get("id")) if away_pitcher.get("id") else None

            def dp():
                return {"hr9": 1.2, "barrel_against": 8.0, "hh_against": 34, "era": 4.00, "whip": 1.30, "k9": 7.0, "last3_era": 4.00, "hand": "R", "splits": None}

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
                    if not b or b.get("hr", 0) < 3: continue
                    splits = opp_p.get("splits")
                    bhand = b.get("hand", "R")
                    platoon_hr9 = opp_p["hr9"]
                    if splits:
                        if bhand == "R": platoon_hr9 = splits.get("rhb_hr9", opp_p["hr9"])
                        elif bhand == "L": platoon_hr9 = splits.get("lhb_hr9", opp_p["hr9"])
                        else: platoon_hr9 = max(splits.get("rhb_hr9", 0), splits.get("lhb_hr9", 0))
                    conf = calculate_confidence(b, opp_p, park, i+1, splits)
                    # Fix #1: Only include players above MIN_DISPLAY
                    if conf < MIN_DISPLAY: continue
                    # Get EV from odds scraper
                    odds_data = get_player_odds(pname)
                    ev_score = None
                    fd_odds = None
                    mgm_odds = None
                    if odds_data:
                        fd_odds = odds_data["fd"]
                        mgm_odds = odds_data["mgm"]
                        ev_score = calculate_ev(conf, fd_odds)
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
                    badge = "🔥" if p["conf"] >= 82 else "✅" if p["conf"] >= 70 else "▪️"
                    # Fix #2: Hot only 3+ HR last 7 days
                    hot = " 🌶️" if p["hr7"] >= HOT_STREAK_MIN else ""
                    # Odds display
                    odds_str = ""
                    if p["fd_odds"]:
                        fd = f"+{p['fd_odds']}" if p['fd_odds'] > 0 else str(p['fd_odds'])
                        mgm = f"+{p['mgm_odds']}" if p['mgm_odds'] > 0 else str(p['mgm_odds'])
                        odds_str = f" | FD:{fd} MGM:{mgm}"
                    ev_str = ""
                    if p["ev_score"] is not None:
                        ev_str = f" | EV:+{p['ev_score']}%" if p["ev_score"] > 0 else f" | EV:{p['ev_score']}%"
                    line = f"{i+1}. {p['name']} ({p['hand']}) — {p['conf']}% {badge}{hot}{odds_str}{ev_str}"
                    # Fix #4: Tiebreaker only on #1 pick — one clean line
                    if i == 0 and len(ranked) > 1:
                        w, l, decision = resolve_tiebreaker(p, ranked[1])[:3]
                        if decision == "INTERCHANGEABLE":
                            line += f"\n   🔄 INTERCHANGE: {ranked[1]['name']} ({ranked[1]['conf']}%)"
                        elif decision == "PLATOON_SWAP":
                            line += f"\n   ⚔️ PLATOON LOCKS: {p['platoon_hr9']} HR/9 vs {ranked[1]['platoon_hr9']}"
                        elif decision == "EV_SWAP":
                            line += f"\n   💰 EV LOCKS: +{p['ev_score']}% vs +{ranked[1]['ev_score']}%"
                    lines.append(line)
                return lines

            away_lines = make_lines(away_ranked)
            home_lines = make_lines(home_ranked)

            # Game top pick
            all_candidates = away_ranked + home_ranked
            all_candidates.sort(key=lambda x: x["conf"], reverse=True)
            game_top = None
            if all_candidates:
                t = all_candidates[0]
                team = away_abbrev if t in away_ranked else home_abbrev
                vs = home_p_name if t in away_ranked else away_p_name
                game_top = {**t, "team": team, "vs": vs, "matchup": f"{away_abbrev} @ {home_abbrev}"}
                all_top_picks.append(game_top)

            # Pitcher splits display
            def splits_line(p_stats, abbrev):
                s = p_stats.get("splits")
                if not s: return ""
                gap = platoon_gap(s["rhb_hr9"], s["lhb_hr9"])
                vuln = "RHB" if s["rhb_hr9"] > s["lhb_hr9"] else "LHB"
                return (
                    f"  vs RHB: {s['rhb_avg']:.3f}AVG/{s['rhb_slg']:.3f}SLG/{s['rhb_hr9']}HR9\n"
                    f"  vs LHB: {s['lhb_avg']:.3f}AVG/{s['lhb_slg']:.3f}SLG/{s['lhb_hr9']}HR9\n"
                    f"  ⚔️ {gap} gap — vulnerable to {vuln}"
                )

            msg = f"""
⚾ {away_abbrev} @ {home_abbrev} — {local_time}{change}
🏟️ {home_name}
━━━━━━━━━━━━━━━━━━━━━━
🔱 PITCHING MATCHUP
━━━━━━━━━━━━━━━━━━━━━━
{away_abbrev} → {away_p_name} {vuln_flag(away_p['hr9'], away_p['barrel_against'])}
• HR/9:{away_p['hr9']} ERA:{away_p['era']} WHIP:{away_p['whip']} K/9:{away_p['k9']}
• Barrel:{away_p['barrel_against']}% HH:{away_p['hh_against']}% L3:{away_p['last3_era']} {pitcher_trend(away_p['era'],away_p['last3_era'])}
{splits_line(away_p, away_abbrev)}
{home_abbrev} → {home_p_name} {vuln_flag(home_p['hr9'], home_p['barrel_against'])}
• HR/9:{home_p['hr9']} ERA:{home_p['era']} WHIP:{home_p['whip']} K/9:{home_p['k9']}
• Barrel:{home_p['barrel_against']}% HH:{home_p['hh_against']}% L3:{home_p['last3_era']} {pitcher_trend(home_p['era'],home_p['last3_era'])}
{splits_line(home_p, home_abbrev)}
━━━━━━━━━━━━━━━━━━━━━━
📊 {away_abbrev} vs {home_p_name}
{chr(10).join(away_lines) if away_lines else "No qualified batters"}
━━━━━━━━━━━━━━━━━━━━━━
📊 {home_abbrev} vs {away_p_name}
{chr(10).join(home_lines) if home_lines else "No qualified batters"}
━━━━━━━━━━━━━━━━━━━━━━
🏆 GAME TOP PICK: {game_top['name']} ({game_top['team']}) — {game_top['conf']}%
━━━━━━━━━━━━━━━━━━━━━━""".strip()

            await bot.send_message(chat_id=CHAT_ID, text=msg)
            await asyncio.sleep(2)

    # ============================================================
    #  PARLAY OF THE DAY
    #  Fix #8: Fires at noon or 2hrs before first pitch
    #  Fix #9: Picks highest EV not just highest confidence
    # ============================================================
    if not parlay_sent and all_top_picks:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_et_hour = (now_utc.hour - 4) % 24

        should_send = False
        if now_et_hour >= PARLAY_HOUR:  # After noon ET
            should_send = True
        if first_game_time:
            mins_to_first = (first_game_time.replace(tzinfo=datetime.timezone.utc) - now_utc).total_seconds() / 60
            if mins_to_first <= 120:
                should_send = True

        if should_send:
            # Deduplicate
            seen = set()
            unique = []
            for p in all_top_picks:
                if p["name"] not in seen:
                    seen.add(p["name"])
                    unique.append(p)

            # Fix #9: Sort by EV first, then confidence
            def parlay_sort(p):
                ev = p.get("ev_score") or 0
                conf = p.get("conf", 0)
                return (ev * 0.6) + (conf * 0.4)

            unique.sort(key=parlay_sort, reverse=True)

            if len(unique) >= 2:
                def leg(p, i):
                    fd = f"+{p['fd_odds']}" if p.get("fd_odds") and p["fd_odds"] > 0 else str(p.get("fd_odds", "N/A"))
                    mgm = f"+{p['mgm_odds']}" if p.get("mgm_odds") and p["mgm_odds"] > 0 else str(p.get("mgm_odds", "N/A"))
                    ev = f"+{p['ev_score']}% EV" if p.get("ev_score") and p["ev_score"] > 0 else ""
                    return (
                        f"{i}. {p['name']} ({p['hand']}) — {p['conf']}%\n"
                        f"   ⚾ vs {p['vs']} | {p['matchup']}\n"
                        f"   FD:{fd} | MGM:{mgm} {ev}"
                    )

                msg = f"🎯 PARLAY OF THE DAY\n🚫 No chalk bias — EV ranked\n━━━━━━━━━━━━━━━━━━━━━━\n"

                if len(unique) >= 2:
                    msg += "\n2️⃣ 2-LEG\n" + "\n".join(leg(unique[i], i+1) for i in range(2))
                if len(unique) >= 3:
                    msg += "\n\n3️⃣ 3-LEG\n" + "\n".join(leg(unique[i], i+1) for i in range(3))
                if len(unique) >= 4:
                    msg += "\n\n4️⃣ 4-LEG\n" + "\n".join(leg(unique[i], i+1) for i in range(4))

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
        text="✅ HR SCOUT V5 — FULL REBUILD\n\n✅ All 13 fixes applied:\n• 55% minimum display threshold\n• Hot flag = 3+ HR last 7 days only\n• Japan/overnight games filtered\n• Tiebreaker one line only on #1\n• Scores recalibrated — wider spread\n• Chalk bias removed\n• FD + BetMGM EV layer live\n• Parlay fires at noon ET\n• EV ranked parlays\n• Both book odds shown\n• Compressed scores fixed\n• Low confidence players cut\n• Overnight games excluded\n\nWaiting for confirmed lineups...")
    await asyncio.sleep(2)

    states = {}
    parlay_sent = False
    last_date = None

    while True:
        now = datetime.datetime.now()
        today = now.date()
        if last_date != today:
            parlay_sent = False
            last_date = today
            states = {}  # Reset daily

        try:
            states, parlay_sent = await run_scan(bot, states, parlay_sent)
        except Exception as e:
            await bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Error: {str(e)[:200]}")

        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())

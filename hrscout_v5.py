import asyncio
import datetime
import re
import aiohttp
from telegram import Bot

TELEGRAM_TOKEN = "8720993049:AAEimQD4PUDFlMA2bpxXsyW3IMcTZ5ak0PY"
CHAT_ID = "919904024"
SCAN_INTERVAL = 300
MIN_DISPLAY = 55
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
#  HR ODDS CACHE
# ============================================================
hr_odds_cache = {}

async def load_hr_odds(session):
    global hr_odds_cache
    url = "https://fantasyteamadvice.com/mlb/props/home-runs"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
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
    except:
        pass

def get_odds(name):
    key = name.lower()
    if key in hr_odds_cache:
        return hr_odds_cache[key]
    last = key.split()[-1] if key.split() else ""
    for k, v in hr_odds_cache.items():
        if last and last in k and len(last) > 3:
            return v
    return None

def american_to_prob(odds):
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)

def calc_ev(conf_pct, odds):
    return round((conf_pct / 100 - american_to_prob(odds)) * 100, 1)

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
#  SCORING — Exact version that produced 3-for-4 parlay
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

def score_hh(h):
    if h >= 55: return 100
    if h >= 48: return 85
    if h >= 40: return 68
    if h >= 32: return 45
    return 20

def score_fb(f):
    if f >= 50: return 100
    if f >= 42: return 85
    if f >= 35: return 68
    if f >= 28: return 45
    return 20

def score_iso(i):
    if i >= 300: return 100
    if i >= 250: return 88
    if i >= 200: return 72
    if i >= 150: return 55
    if i >= 100: return 35
    return 15

def score_pull(p):
    if p >= 50: return 100
    if p >= 40: return 85
    if p >= 33: return 65
    if p >= 25: return 40
    return 15

def score_recent_hr(hr, games):
    r = (hr / max(games, 1)) * 14
    if r >= 6: return 100
    if r >= 4: return 85
    if r >= 3: return 70
    if r >= 2: return 52
    if r >= 1: return 35
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

def score_p_hr9(h):
    if h >= 2.0: return 100
    if h >= 1.5: return 85
    if h >= 1.2: return 68
    if h >= 1.0: return 50
    if h >= 0.7: return 30
    return 12

def score_p_barrel(b):
    if b >= 14: return 100
    if b >= 11: return 85
    if b >= 8:  return 65
    if b >= 6:  return 45
    return 20

def score_p_form(last3, era):
    d = last3 - era
    if d >= 2.5: return 100
    if d >= 1.5: return 85
    if d >= 0.5: return 65
    if d >= -0.5: return 50
    if d >= -1.5: return 32
    return 15

def score_platoon(bhand, splits):
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

def score_order(spot):
    if spot <= 0: return 60
    if spot in [3, 4]: return 92
    if spot in [1, 2, 5]: return 80
    if spot in [6, 7]: return 68
    if spot in [8, 9]: return 52
    return 48

# Exact weights from 3-for-4 version
def calculate_confidence(b, p, park, spot=0, splits=None):
    weights = {
        "p_hr9": 12, "platoon": 12, "p_form": 10,
        "batter_form": 10, "p_barrel": 8,
        "barrel": 10, "ev": 8, "hh": 5, "fb": 5,
        "pull": 5, "iso": 3, "recent_hr": 5,
        "park": 4, "order": 3,
    }
    scores = {
        "p_hr9":       score_p_hr9(p.get("hr9", 1.2)),
        "platoon":     score_platoon(b.get("hand", "R"), splits),
        "p_form":      score_p_form(p.get("last3_era", 4.0), p.get("era", 4.0)),
        "batter_form": score_batter_form(b.get("avg7", 0.250), b.get("hr7", 0)),
        "p_barrel":    score_p_barrel(p.get("barrel_against", 8)),
        "barrel":      score_barrel(b.get("barrel", 8)),
        "ev":          score_ev(b.get("ev", 88)),
        "hh":          score_hh(b.get("hh", 35)),
        "fb":          score_fb(b.get("fb", 35)),
        "pull":        score_pull(b.get("pull", 35)),
        "iso":         score_iso(b.get("iso", 140)),
        "recent_hr":   score_recent_hr(b.get("hr", 0), b.get("games", 1)),
        "park":        score_park(park),
        "order":       score_order(spot),
    }
    return round(sum(scores[k] * weights[k] / 100 for k in scores))

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
#  TIEBREAKER
# ============================================================
def resolve_tiebreaker(p1, p2):
    gap = abs(p1["conf"] - p2["conf"])
    if gap > INTERCHANGE_GAP:
        return p1, None, "CLEAR"

    p1_platoon = p1.get("platoon_hr9", 1.2)
    p2_platoon = p2.get("platoon_hr9", 1.2)
    platoon_diff = abs(p1_platoon - p2_platoon)

    p1_ev = p1.get("ev_score")
    p2_ev = p2.get("ev_score")
    if p1_ev is not None and p2_ev is not None:
        ev_gap = abs(p1_ev - p2_ev)
        if ev_gap >= 5:
            winner = p1 if p1_ev >= p2_ev else p2
            loser = p2 if p1_ev >= p2_ev else p1
            decision = "EV_SWAP" if winner == p2 else "EV_WIN"
            return winner, loser, decision

    if platoon_diff >= 0.4:
        if p1_platoon >= p2_platoon:
            return p1, p2, "PLATOON_WIN"
        else:
            return p2, p1, "PLATOON_SWAP"

    return p1, p2, "INTERCHANGEABLE"

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
                gt = game.get("gameDate", "")
                try:
                    dt = datetime.datetime.fromisoformat(gt.replace("Z", "+00:00"))
                    hour_et = (dt.hour - 4) % 24
                    if 1 <= hour_et <= 5:
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
        fb = min(55, max(22, 30 + (hr / max(ab, 1)) * 150 + (slg - 0.350) * 30))
        pull = min(60, max(25, 37 + (hr / max(ab, 1)) * 160))
        barrel = min(25, max(3, (slg - 0.280) * 50))
        ev = min(98, max(83, 87 + (slg - 0.320) * 25))
        hh = min(65, max(22, 33 + (slg - 0.320) * 60))
        hr7 = int(recent.get("homeRuns", 0))
        avg7 = float(recent.get("avg", avg) or avg)
        sv = get_savant(player_id)
        if sv:
            if sv["barrel"] > 0: barrel = sv["barrel"]
            if sv["ev"] > 0: ev = sv["ev"]
            if sv["hh"] > 0: hh = sv["hh"]
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
        ip = float(season.get("inningsPitched", 0) or 0)
        barrel_against = min(18, max(4, (era - 3.0) * 3 + 8))
        hh_against = min(50, max(25, 30 + (era - 3.5) * 4))
        last3_era = era
        if game_log:
            recent = game_log[-3:] if len(game_log) >= 3 else game_log
            er = sum(int(g.get("stat", {}).get("earnedRuns", 0)) for g in recent)
            pip = sum(float(g.get("stat", {}).get("inningsPitched", 0) or 0) for g in recent)
            if pip > 0:
                last3_era = round((er / pip) * 9, 2)
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
                    sip = float(s.get("inningsPitched", 1) or 1)
                    c_hr9 = round((h / max(sip, 1)) * 9, 2)
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
            "last3_era": last3_era, "hand": hand, "ip": ip,
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
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    async with aiohttp.ClientSession() as session:
        await load_savant(session)
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
                mins_since = (now_utc - dt.replace(tzinfo=datetime.timezone.utc)).total_seconds() / 60
                if mins_since > 0:
                    continue
                if first_game_time is None or dt < first_game_time:
                    first_game_time = dt
            except:
                pass

        for game in games:
            game_id = str(game.get("gamePk", ""))
            status = game.get("status", {}).get("abstractGameState", "")
            detailed = game.get("status", {}).get("detailedState", "")

            if status in ["Final", "Live"]:
                continue
            if detailed in ["In Progress", "Final", "Game Over", "Completed Early",
                            "Postponed", "Suspended", "Cancelled"]:
                continue

            gt_str = game.get("gameDate", "")
            try:
                dt = datetime.datetime.fromisoformat(gt_str.replace("Z", "+00:00"))
                et_dt = dt + datetime.timedelta(hours=-4)
                local_time = et_dt.strftime("%-I:%M %p ET")
                game_dt = dt
                mins_since = (now_utc - dt.replace(tzinfo=datetime.timezone.utc)).total_seconds() / 60
                if mins_since > 0:
                    continue
            except:
                local_time = "TBD"
                game_dt = None

            home_name = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "")
            away_name = game.get("teams", {}).get("away", {}).get("team", {}).get("name", "")
            home_abbrev = TEAM_ABBREV.get(home_name, "???")
            away_abbrev = TEAM_ABBREV.get(away_name, "???")
            home_pitcher = game.get("teams", {}).get("home", {}).get("probablePitcher", {})
            away_pitcher = game.get("teams", {}).get("away", {}).get("probablePitcher", {})
            matchup = f"{away_abbrev} @ {home_abbrev}"

            lineups = game.get("lineups", {})
            home_lineup = lineups.get("homePlayers", [])
            away_lineup = lineups.get("awayPlayers", [])

            if not home_lineup and not away_lineup:
                continue

            fp = game_fingerprint(game, home_lineup, away_lineup)
            prev_fp = states.get(game_id)
            send_alert = prev_fp != fp

            change = ""
            if prev_fp and prev_fp != fp:
                pp = prev_fp.split("_")
                cp = fp.split("_")
                if pp[0] != cp[0]: change = f"\n🚨 PITCHER CHANGE — {home_abbrev} starter changed"
                elif pp[1] != cp[1]: change = f"\n🚨 PITCHER CHANGE — {away_abbrev} starter changed"
                else: change = "\n🔄 LINEUP CHANGE"

            new_states[game_id] = fp

            def dp():
                return {"hr9": 1.2, "barrel_against": 8.0, "hh_against": 34,
                        "era": 4.00, "whip": 1.30, "k9": 7.0,
                        "last3_era": 4.00, "hand": "R", "ip": 0, "splits": None}

            home_p = await get_pitcher_stats(session, home_pitcher.get("id")) if home_pitcher.get("id") else dp()
            away_p = await get_pitcher_stats(session, away_pitcher.get("id")) if away_pitcher.get("id") else dp()
            if not home_p: home_p = dp()
            if not away_p: away_p = dp()

            home_p_name = home_pitcher.get("fullName", "TBD")
            away_p_name = away_pitcher.get("fullName", "TBD")

            async def score_lineup(lineup, opp_p, park, team_abbrev, opp_name):
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
                    odds_data = get_odds(pname)
                    fd_odds = mgm_odds = ev_score = None
                    if odds_data:
                        fd_odds = odds_data["fd"]
                        mgm_odds = odds_data["mgm"]
                        ev_score = calc_ev(conf, fd_odds)
                    is_vulnerable = opp_p.get("hr9", 1.2) >= 1.2 or opp_p.get("barrel_against", 8) >= 8
                    # Parlay eligible: 20+ IP filter to avoid small sample pitchers
                    pitcher_ip = opp_p.get("ip", 0)
                    parlay_eligible = pitcher_ip >= 20
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
                        "p_vulnerable": is_vulnerable,
                        "parlay_eligible": parlay_eligible,
                        "game_dt": game_dt,
                        "matchup": matchup,
                        "vs": opp_name,
                        "team": team_abbrev,
                    })
                ranked.sort(key=lambda x: x["conf"], reverse=True)
                return ranked

            away_ranked = await score_lineup(away_lineup, home_p, home_abbrev, away_abbrev, home_p_name)
            home_ranked = await score_lineup(home_lineup, away_p, home_abbrev, home_abbrev, away_p_name)

            # Add to parlay pool
            for p in away_ranked + home_ranked:
                if p["parlay_eligible"]:
                    all_top_picks.append(p)

            if not away_ranked and not home_ranked:
                continue

            def make_lines(ranked):
                lines = []
                for i, p in enumerate(ranked[:3]):
                    if p["conf"] < MIN_DISPLAY:
                        continue
                    badge = "🔥" if p["conf"] >= 82 else "✅" if p["conf"] >= 70 else ""
                    hot = " 🌶️" if p["hr7"] >= HOT_MIN else ""
                    vuln_note = f" 🚨{p['platoon_hr9']}HR9" if p["platoon_hr9"] >= 1.5 else ""
                    odds_str = ""
                    if p.get("fd_odds"):
                        fd = f"+{p['fd_odds']}" if p['fd_odds'] > 0 else str(p['fd_odds'])
                        mgm = f"+{p['mgm_odds']}" if p.get('mgm_odds') and p['mgm_odds'] > 0 else ""
                        odds_str = f" | FD:{fd}"
                        if mgm: odds_str += f" MGM:{mgm}"
                    line = f"{i+1}. {p['name']} ({p['hand']}) — {p['conf']}% {badge}{hot}{vuln_note}{odds_str}".strip()
                    if i == 0 and len(ranked) > 1:
                        _, _, decision = resolve_tiebreaker(p, ranked[1])
                        if decision == "INTERCHANGEABLE":
                            line += f"\n   🔄 INTERCHANGE: {ranked[1]['name']} ({ranked[1]['conf']}%)"
                        elif "PLATOON" in decision:
                            line += f"\n   ⚔️ PLATOON: {p['platoon_hr9']} vs {ranked[1]['platoon_hr9']} HR9"
                        elif "EV" in decision:
                            line += f"\n   💰 EV EDGE: {p['ev_score']}% vs {ranked[1]['ev_score']}%"
                    lines.append(line)
                return lines

            away_lines = make_lines(away_ranked)
            home_lines = make_lines(home_ranked)

            all_cands = sorted(away_ranked + home_ranked, key=lambda x: x["conf"], reverse=True)
            game_top = None
            if all_cands:
                t = all_cands[0]
                team = away_abbrev if t in away_ranked else home_abbrev
                vs = home_p_name if t in away_ranked else away_p_name
                game_top = {**t, "team": team, "vs": vs, "matchup": matchup}

                if len(all_cands) > 1:
                    _, partner, decision = resolve_tiebreaker(all_cands[0], all_cands[1])
                    if partner and decision in ["INTERCHANGEABLE", "PLATOON_SWAP", "EV_SWAP"]:
                        p2 = all_cands[1]
                        team2 = away_abbrev if p2 in away_ranked else home_abbrev
                        vs2 = home_p_name if p2 in away_ranked else away_p_name
                        all_top_picks.append({
                            **p2, "team": team2, "vs": vs2,
                            "matchup": matchup, "is_interchange": True,
                        })

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

            lineup_status = "✅ CONFIRMED"

            if send_alert and game_top:
                msg = f"""
⚾ {away_abbrev} @ {home_abbrev} — {local_time} | {lineup_status}{change}
🏟️ {home_name}
━━━━━━━━━━━━━━━━━━━━━━
🔱 PITCHING MATCHUP
━━━━━━━━━━━━━━━━━━━━━━
{away_abbrev} → {away_p_name} {vuln_flag(away_p['hr9'], away_p['barrel_against'])}
• HR/9:{away_p['hr9']} ERA:{away_p['era']} WHIP:{away_p['whip']} K/9:{away_p['k9']}
• L3 ERA:{away_p['last3_era']} {pitcher_trend(away_p['era'], away_p['last3_era'])}
{splits_line(away_p)}
{home_abbrev} → {home_p_name} {vuln_flag(home_p['hr9'], home_p['barrel_against'])}
• HR/9:{home_p['hr9']} ERA:{home_p['era']} WHIP:{home_p['whip']} K/9:{home_p['k9']}
• L3 ERA:{home_p['last3_era']} {pitcher_trend(home_p['era'], home_p['last3_era'])}
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
    #  PARLAYS — 15-30 mins before first pitch, full slate
    # ============================================================
    if not parlay_sent and all_top_picks and first_game_time:
        mins_to_first = (first_game_time.replace(tzinfo=datetime.timezone.utc) - now_utc).total_seconds() / 60

        if 10 <= mins_to_first <= 35:
            seen = set()
            pool = []
            for p in all_top_picks:
                if p["name"] not in seen and p.get("conf", 0) >= PARLAY_MIN_CONF:
                    seen.add(p["name"])
                    pool.append(p)

            for p in all_top_picks:
                if p["name"] not in seen and p.get("conf", 0) >= 55:
                    criteria = 0
                    if p.get("hr7", 0) >= HOT_MIN: criteria += 1
                    if p.get("platoon_hr9", 1.2) >= 1.2: criteria += 1
                    if p.get("p_vulnerable", False): criteria += 1
                    if criteria >= 2:
                        seen.add(p["name"])
                        pool.append(p)

            if not pool or len(pool) < 2:
                return new_states, parlay_sent

            # EXACT sort from 3-for-4 version: confidence + small EV bonus
            def std_sort(p):
                conf = p.get("conf", 0)
                ev = p.get("ev_score") or 0
                ev_bonus = ev * 0.1 if ev > 0 else 0
                return conf + ev_bonus

            def ev_sort(p):
                ev = p.get("ev_score") or 0
                fd = p.get("fd_odds") or 300
                return ev + (fd / 100)

            std_pool = sorted(pool, key=std_sort, reverse=True)
            ev_pool = sorted(pool, key=ev_sort, reverse=True)

            std_names = {p["name"] for p in std_pool[:4]}
            ev_alt = [p for p in ev_pool if p["name"] not in std_names]
            if len(ev_alt) < 3:
                ev_alt = ev_pool

            # One player per game
            def one_per_game(picks, n):
                used = set()
                result = []
                for p in picks:
                    gk = p.get("matchup", "")
                    if gk not in used:
                        used.add(gk)
                        result.append(p)
                    if len(result) >= n:
                        break
                return result

            std_2 = one_per_game(std_pool, 2)
            std_3 = one_per_game(std_pool, 3)
            std_4 = one_per_game(std_pool, 4)
            ev_3 = one_per_game(ev_alt, 3)

            game_times = [p.get("game_dt") for p in std_pool[:4] if p.get("game_dt")]
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
                hot = " 🌶️" if p.get("hr7", 0) >= HOT_MIN else ""
                alt = " ↔️" if p.get("is_interchange") else ""
                vuln = f" 🚨{p['platoon_hr9']}HR9" if p.get("platoon_hr9", 0) >= 1.5 else ""
                gt = p.get("game_dt")
                time_str = ""
                if gt:
                    try:
                        et = gt + datetime.timedelta(hours=-4)
                        time_str = f" | {et.strftime('%-I:%M %p ET')}"
                    except:
                        pass
                return (
                    f"{i}. {p['name']} ({p.get('hand', '')}) — {p['conf']}%{hot}{alt}{vuln}\n"
                    f"   ⚾ vs {p.get('vs', '?')} | {p.get('matchup', '?')}{time_str}\n"
                    f"   FD:{fd} MGM:{mgm}{ev_str}"
                )

            if len(std_2) >= 2:
                msg = f"🎯 PARLAYS OF THE DAY\n{slate_label} | 🚫 No chalk bias\n🔒 One player per game\n━━━━━━━━━━━━━━━━━━━━━━"
                msg += "\n\n2️⃣ 2-LEG\n" + "\n".join(leg(std_2[i], i+1) for i in range(len(std_2)))
                if len(std_3) >= 3:
                    msg += "\n\n3️⃣ 3-LEG\n" + "\n".join(leg(std_3[i], i+1) for i in range(len(std_3)))
                if len(std_4) >= 4:
                    msg += "\n\n4️⃣ 4-LEG\n" + "\n".join(leg(std_4[i], i+1) for i in range(len(std_4)))
                if len(ev_3) >= 3:
                    msg += "\n\n💰 EV 3-LEG (VALUE)\n" + "\n".join(leg(ev_3[i], i+1) for i in range(len(ev_3)))
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
        text="✅ HR SCOUT V5 — RESTORED\n\n"
             "📊 Exact scoring that produced 3/4 parlay\n"
             "🔒 One player per game\n"
             "🌅 Full slate — all games considered\n"
             "🚫 No alerts for started games\n"
             "⛽ 20+ IP filter on pitchers\n"
             "🎯 Parlays 15-30 mins before first pitch\n\n"
             "Scanning...")
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
            states = {}

        try:
            states, parlay_sent = await run_scan(bot, states, parlay_sent)
        except Exception as e:
            await bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Error: {str(e)[:200]}")

        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())

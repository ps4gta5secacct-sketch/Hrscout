import asyncio
import datetime
import re
import aiohttp
from telegram import Bot

# ============================================================
#  CONFIGURATION
# ============================================================
TELEGRAM_TOKEN = "8720993049:AAEimQD4PUDFlMA2bpxXsyW3IMcTZ5ak0PY"
CHAT_ID = "919904024"
SCAN_INTERVAL = 300
HOT_MIN = 3
INTERCHANGE_GAP = 3
PARLAY_MIN_PLATOON_HR9 = 1.5   # Minimum HR/9 to batter's hand for parlay
PARLAY_MIN_IP = 20              # Minimum innings pitched — filters small sample pitchers

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
    url = "https://fantasyteamadvice.com/mlb/props/home-runs"
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
    except:
        pass

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
#  SCORING
# ============================================================
def pitcher_vulnerability_score(p):
    score = 0
    hr9 = p.get("hr9", 1.2)
    if hr9 >= 2.0:   score += 40
    elif hr9 >= 1.7: score += 32
    elif hr9 >= 1.5: score += 25
    elif hr9 >= 1.2: score += 18
    elif hr9 >= 1.0: score += 10
    elif hr9 < 0.7:  score -= 15
    last3 = p.get("last3_era", p.get("era", 4.0))
    era = p.get("era", 4.0)
    diff = last3 - era
    if diff >= 4.0:   score += 25
    elif diff >= 3.0: score += 20
    elif diff >= 2.0: score += 15
    elif diff >= 1.0: score += 10
    elif diff >= 0.0: score += 3
    elif diff <= -2.0: score -= 10
    barrel = p.get("barrel_against", 8)
    if barrel >= 14:  score += 15
    elif barrel >= 11: score += 10
    elif barrel >= 8:  score += 5
    return score

def batter_matchup_score(b, p, park, spot, splits, platoon_hr9):
    score = 0
    if platoon_hr9 >= 2.5:   score += 30
    elif platoon_hr9 >= 2.0: score += 24
    elif platoon_hr9 >= 1.7: score += 18
    elif platoon_hr9 >= 1.5: score += 14
    elif platoon_hr9 >= 1.2: score += 8
    elif platoon_hr9 >= 1.0: score += 3
    else: score -= 8
    hr7 = b.get("hr7", 0)
    if hr7 >= 4:   score += 25
    elif hr7 >= 3: score += 20
    elif hr7 >= 2: score += 14
    elif hr7 >= 1: score += 6
    hr = b.get("hr", 0)
    games = max(b.get("games", 1), 1)
    hr14 = (hr / games) * 14
    if hr14 >= 6:   score += 15
    elif hr14 >= 4: score += 12
    elif hr14 >= 3: score += 9
    elif hr14 >= 2: score += 6
    elif hr14 >= 1: score += 3
    barrel = b.get("barrel", 0)
    if barrel >= 20:   score += 15
    elif barrel >= 15: score += 11
    elif barrel >= 12: score += 8
    elif barrel >= 10: score += 5
    ev = b.get("ev", 0)
    if ev >= 95:   score += 8
    elif ev >= 93: score += 6
    elif ev >= 91: score += 4
    elif ev >= 89: score += 2
    pf = PARK_FACTORS.get(park, 100)
    if pf >= 115:   score += 8
    elif pf >= 108: score += 6
    elif pf >= 103: score += 4
    elif pf >= 100: score += 2
    elif pf <= 93:  score -= 3
    if spot in [3, 4]:      score += 6
    elif spot in [1, 2, 5]: score += 4
    elif spot in [6, 7]:    score += 2
    return score

def calculate_confidence(b, p, park, spot=0, splits=None, platoon_hr9=None):
    if platoon_hr9 is None:
        platoon_hr9 = p.get("hr9", 1.2)
    p_score = pitcher_vulnerability_score(p)
    b_score = batter_matchup_score(b, p, park, spot, splits, platoon_hr9)
    raw = (p_score * 0.45) + (b_score * 0.55)
    scaled = 25 + (raw / 140) * 70
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
#  TIEBREAKER — Within 3%: higher odds ALWAYS wins
# ============================================================
def resolve_tiebreaker(p1, p2):
    gap = abs(p1["conf"] - p2["conf"])
    if gap > INTERCHANGE_GAP:
        winner = p1 if p1["conf"] >= p2["conf"] else p2
        return winner, None, "CLEAR"
    p1_odds = p1.get("fd_odds")
    p2_odds = p2.get("fd_odds")
    if p1_odds and p2_odds:
        if p1_odds > p2_odds:
            return p1, p2, "VALUE_WIN"
        elif p2_odds > p1_odds:
            return p2, p1, "VALUE_SWAP"
    p1_platoon = p1.get("platoon_hr9", 1.2)
    p2_platoon = p2.get("platoon_hr9", 1.2)
    if abs(p1_platoon - p2_platoon) >= 0.4:
        if p1_platoon >= p2_platoon:
            return p1, p2, "PLATOON_WIN"
        else:
            return p2, p1, "PLATOON_SWAP"
    winner = p1 if p1["conf"] >= p2["conf"] else p2
    loser = p2 if p1["conf"] >= p2["conf"] else p1
    return winner, loser, "INTERCHANGEABLE"

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
                    et_hour = (dt.hour - 4) % 24
                    if 1 <= et_hour <= 6:
                        continue
                except:
                    pass
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
        barrel = min(25, max(3, (hr_rate * 180) + (iso - 100) * 0.04))
        ev = min(98, max(83, 87 + (iso - 130) * 0.04 + (slg - 0.350) * 8))
        hh = min(65, max(22, 32 + (iso - 130) * 0.06 + (slg - 0.350) * 30))
        hr7 = int(recent.get("homeRuns", 0))
        avg7 = float(recent.get("avg", avg) or avg)
        savant_real = False
        sv = get_savant(player_id)
        if sv:
            if sv["barrel"] > 0:
                barrel = sv["barrel"]
                savant_real = True
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
            "barrel": barrel, "ev": ev, "hh": hh,
            "hr": hr, "games": games, "iso": iso,
            "hand": hand, "hr7": hr7, "avg7": avg7,
            "savant_real": savant_real,
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
                        rhb_avg = float(s.get("avg", 0.250) or 0.250)
                    elif sit == "vl":
                        lhb_hr9 = c_hr9
                        lhb_avg = float(s.get("avg", 0.250) or 0.250)
        except:
            pass
        return {
            "hr9": hr9, "era": era, "whip": whip, "k9": k9,
            "barrel_against": barrel_against, "ip": ip,
            "last3_era": last3_era, "hand": hand,
            "splits": {
                "rhb_hr9": rhb_hr9, "lhb_hr9": lhb_hr9,
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
            status = game.get("status", {}).get("abstractGameState", "")
            if status in ["Final", "Live"]:
                continue
            gt = game.get("gameDate", "")
            try:
                dt = datetime.datetime.fromisoformat(gt.replace("Z", "+00:00"))
                mins_since = (now_utc - dt.replace(tzinfo=datetime.timezone.utc)).total_seconds() / 60
                if mins_since > 0:  # Game already started
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
                # Skip games that have already started
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
            is_projected = False

            if not home_lineup and not away_lineup:
                home_team_id = game.get("teams", {}).get("home", {}).get("team", {}).get("id")
                away_team_id = game.get("teams", {}).get("away", {}).get("team", {}).get("id")
                if not home_pitcher.get("id") and not away_pitcher.get("id"):
                    continue
                try:
                    home_roster = await get_team_roster(session, home_team_id) if home_team_id else []
                    away_roster = await get_team_roster(session, away_team_id) if away_team_id else []
                    home_lineup = [p.get("person", {}) for p in home_roster
                                   if p.get("position", {}).get("type") != "Pitcher"][:9]
                    away_lineup = [p.get("person", {}) for p in away_roster
                                   if p.get("position", {}).get("type") != "Pitcher"][:9]
                    is_projected = True
                except:
                    continue

            fp = game_fingerprint(game, home_lineup, away_lineup)
            send_alert = states.get(game_id) != fp

            change = ""
            prev = states.get(game_id, "")
            if prev and prev != fp:
                pp = prev.split("_")
                cp = fp.split("_")
                if pp[0] != cp[0]: change = f"\n🚨 PITCHER CHANGE — {home_abbrev}"
                elif pp[1] != cp[1]: change = f"\n🚨 PITCHER CHANGE — {away_abbrev}"
                else: change = "\n🔄 LINEUP CHANGE"

            new_states[game_id] = fp

            def dp():
                return {"hr9": 1.2, "barrel_against": 8.0, "era": 4.00,
                        "whip": 1.30, "k9": 7.0, "last3_era": 4.00,
                        "hand": "R", "splits": None, "ip": 0}

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
                    if not b or b.get("hr", 0) < 2: continue

                    splits = opp_p.get("splits")
                    bhand = b.get("hand", "R")
                    platoon_hr9 = opp_p["hr9"]
                    if splits:
                        if bhand == "R": platoon_hr9 = splits.get("rhb_hr9", opp_p["hr9"])
                        elif bhand == "L": platoon_hr9 = splits.get("lhb_hr9", opp_p["hr9"])
                        else: platoon_hr9 = max(splits.get("rhb_hr9", 0), splits.get("lhb_hr9", 0))

                    conf = calculate_confidence(b, opp_p, park, i+1, splits, platoon_hr9)

                    odds_data = get_odds(pname)
                    fd_odds = mgm_odds = ev_score = None
                    if odds_data:
                        fd_odds = odds_data["fd"]
                        mgm_odds = odds_data["mgm"]
                        ev_score = calc_ev(conf, fd_odds)

                    # Parlay eligible check
                    # Must have 1.5+ platoon HR/9 AND pitcher must have 20+ IP
                    pitcher_ip = opp_p.get("ip", 0)
                    parlay_eligible = (
                        platoon_hr9 >= PARLAY_MIN_PLATOON_HR9 and
                        pitcher_ip >= PARLAY_MIN_IP
                    )

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
                        "parlay_eligible": parlay_eligible,
                        "pitcher_ip": pitcher_ip,
                        "p_hr9": opp_p.get("hr9", 1.2),
                        "last3_era": opp_p.get("last3_era", 4.0),
                        "era": opp_p.get("era", 4.0),
                        "game_dt": game_dt,
                        "matchup": matchup,
                        "vs": opp_name,
                        "team": team_abbrev,
                        "savant_real": b.get("savant_real", False),
                        "barrel": b.get("barrel", 0),
                        "ev": b.get("ev", 0),
                    })
                ranked.sort(key=lambda x: x["conf"], reverse=True)
                return ranked

            away_ranked = await score_lineup(away_lineup, home_p, home_abbrev, away_abbrev, home_p_name)
            home_ranked = await score_lineup(home_lineup, away_p, home_abbrev, home_abbrev, away_p_name)

            # Add parlay eligible players to pool
            for p in away_ranked + home_ranked:
                if p["parlay_eligible"]:
                    all_top_picks.append(p)

            if not away_ranked and not home_ranked:
                continue

            def make_lines(ranked):
                lines = []
                for i, p in enumerate(ranked[:3]):
                    badge = "🔥" if p["hr7"] >= HOT_MIN else "✅" if p["conf"] >= 70 else ""
                    odds_str = ""
                    if p.get("fd_odds"):
                        fd = f"+{p['fd_odds']}" if p['fd_odds'] > 0 else str(p['fd_odds'])
                        mgm = f"+{p['mgm_odds']}" if p.get('mgm_odds') and p['mgm_odds'] > 0 else ""
                        odds_str = f" | FD:{fd}"
                        if mgm: odds_str += f" MGM:{mgm}"

                    vuln_note = f" 🚨{p['platoon_hr9']}HR9" if p['platoon_hr9'] >= 1.5 else ""
                    line = f"{i+1}. {p['name']} ({p['hand']}) — {p['conf']}% {badge}{vuln_note}{odds_str}".strip()

                    if p.get("savant_real"):
                        line += f"\n   Barrel:{p['barrel']:.1f}% EV:{p['ev']:.1f}mph"

                    if i == 0 and len(ranked) > 1:
                        _, partner, decision = resolve_tiebreaker(p, ranked[1])
                        if decision == "VALUE_SWAP":
                            p2 = ranked[1]
                            fd2 = f"+{p2['fd_odds']}" if p2.get('fd_odds') and p2['fd_odds'] > 0 else "N/A"
                            line += f"\n   💰 VALUE: {p2['name']} {fd2} — better odds"
                        elif decision == "INTERCHANGEABLE":
                            line += f"\n   🔄 INTERCHANGE: {ranked[1]['name']} ({ranked[1]['conf']}%)"
                        elif "PLATOON" in decision:
                            line += f"\n   ⚔️ PLATOON: {p['platoon_hr9']} vs {ranked[1]['platoon_hr9']} HR9"
                    lines.append(line)
                return lines

            away_lines = make_lines(away_ranked)
            home_lines = make_lines(home_ranked)

            all_cands = sorted(away_ranked + home_ranked, key=lambda x: x["conf"], reverse=True)
            game_top = all_cands[0] if all_cands else None

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

            if send_alert:
                msg = f"""
⚾ {away_abbrev} @ {home_abbrev} — {local_time} | {lineup_status}{change}
🏟️ {home_name}
━━━━━━━━━━━━━━━━━━━━━━
🔱 PITCHING MATCHUP
━━━━━━━━━━━━━━━━━━━━━━
{away_abbrev} → {away_p_name} {vuln_flag(away_p['hr9'], away_p['barrel_against'])}
• HR/9:{away_p['hr9']} ERA:{away_p['era']} WHIP:{away_p['whip']} K/9:{away_p['k9']} IP:{away_p['ip']}
• L3 ERA:{away_p['last3_era']} {pitcher_trend(away_p['era'], away_p['last3_era'])}
{splits_line(away_p)}
{home_abbrev} → {home_p_name} {vuln_flag(home_p['hr9'], home_p['barrel_against'])}
• HR/9:{home_p['hr9']} ERA:{home_p['era']} WHIP:{home_p['whip']} K/9:{home_p['k9']} IP:{home_p['ip']}
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
    #  PARLAY — Pitcher vulnerability drives selection
    #  Must have 1.5+ platoon HR9 AND 20+ IP
    #  One per game. Full slate. Higher odds wins ties.
    # ============================================================
    if not parlay_sent and first_game_time:
        mins_to_first = (first_game_time.replace(tzinfo=datetime.timezone.utc) - now_utc).total_seconds() / 60

        if 10 <= mins_to_first <= 35:
            # Deduplicate
            seen = set()
            unique = []
            for p in all_top_picks:
                if p["name"] not in seen:
                    seen.add(p["name"])
                    unique.append(p)

            # Sort: pitcher vulnerability + confidence + EV
            def parlay_sort(p):
                p_vuln = pitcher_vulnerability_score({
                    "hr9": p.get("p_hr9", 1.2),
                    "last3_era": p.get("last3_era", 4.0),
                    "era": p.get("era", 4.0),
                    "barrel_against": 8,
                })
                conf = p.get("conf", 0)
                ev = p.get("ev_score") or 0
                fd = p.get("fd_odds") or 200
                ev_bonus = (ev * 0.3) + (fd / 200)
                return (p_vuln * 0.45) + (conf * 0.35) + (ev_bonus * 0.20)

            unique.sort(key=parlay_sort, reverse=True)

            # Apply tiebreaker — within 3% higher odds wins
            for i in range(len(unique) - 1):
                p1 = unique[i]
                p2 = unique[i+1]
                if abs(p1["conf"] - p2["conf"]) <= 3:
                    p1_odds = p1.get("fd_odds") or 0
                    p2_odds = p2.get("fd_odds") or 0
                    if p2_odds > p1_odds:
                        unique[i], unique[i+1] = unique[i+1], unique[i]

            # One per game
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

            pool_2 = one_per_game(unique, 2)
            pool_3 = one_per_game(unique, 3)
            pool_4 = one_per_game(unique, 4)

            ev_sorted = sorted(unique, key=lambda x: (x.get("ev_score") or 0) + ((x.get("fd_odds") or 200) / 100), reverse=True)
            pool_4_names = {p["name"] for p in pool_4}
            ev_alt = [p for p in ev_sorted if p["name"] not in pool_4_names]
            ev_3 = one_per_game(ev_alt if len(ev_alt) >= 3 else ev_sorted, 3)

            def leg(p, i):
                fd = f"+{p['fd_odds']}" if p.get("fd_odds") and p["fd_odds"] > 0 else "N/A"
                mgm = f"+{p['mgm_odds']}" if p.get("mgm_odds") and p["mgm_odds"] > 0 else "N/A"
                ev_str = f" EV:+{p['ev_score']}%" if p.get("ev_score") and p["ev_score"] > 0 else ""
                hot = " 🔥" if p.get("hr7", 0) >= HOT_MIN else ""
                gt = p.get("game_dt")
                time_str = ""
                if gt:
                    try:
                        et = gt + datetime.timedelta(hours=-4)
                        time_str = f" | {et.strftime('%-I:%M %p ET')}"
                    except:
                        pass
                vuln = f" 🚨{p['platoon_hr9']}HR9" if p.get("platoon_hr9", 0) >= 1.5 else ""
                return (
                    f"{i}. {p['name']} ({p.get('hand','')}) — {p['conf']}%{hot}{vuln}\n"
                    f"   ⚾ vs {p.get('vs','?')} | {p.get('matchup','?')}{time_str}\n"
                    f"   FD:{fd} MGM:{mgm}{ev_str}"
                )

            if len(pool_2) >= 2:
                msg = "🎯 PARLAYS OF THE DAY\n🌅➡️🌙 FULL SLATE | 🚫 No chalk bias\n🔒 One player per game\n━━━━━━━━━━━━━━━━━━━━━━"
                msg += "\n\n2️⃣ 2-LEG\n" + "\n".join(leg(pool_2[i], i+1) for i in range(len(pool_2)))
                if len(pool_3) >= 3:
                    msg += "\n\n3️⃣ 3-LEG\n" + "\n".join(leg(pool_3[i], i+1) for i in range(len(pool_3)))
                if len(pool_4) >= 4:
                    msg += "\n\n4️⃣ 4-LEG\n" + "\n".join(leg(pool_4[i], i+1) for i in range(len(pool_4)))
                if len(ev_3) >= 3:
                    msg += "\n\n💰 EV 3-LEG\n" + "\n".join(leg(ev_3[i], i+1) for i in range(len(ev_3)))
                msg += "\n━━━━━━━━━━━━━━━━━━━━━━"
                await bot.send_message(chat_id=CHAT_ID, text=msg)
                parlay_sent = True
            elif unique:
                msg = "🎯 BEST PLAYS TODAY\n⚠️ Limited high-quality matchups\n━━━━━━━━━━━━━━━━━━━━━━\n"
                for i, p in enumerate(one_per_game(unique, 4), 1):
                    msg += leg(p, i) + "\n"
                msg += "━━━━━━━━━━━━━━━━━━━━━━"
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
             "🎯 PARLAY RULES:\n"
             "• Pitcher must have 1.5+ HR/9 to batter hand\n"
             "• Pitcher must have 20+ IP (no small samples)\n"
             "• Higher odds wins when within 3%\n"
             "• One player per game\n"
             "• Full slate — all games considered\n"
             "• No alerts for games already started\n\n"
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

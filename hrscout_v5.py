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
#  THREE GATE SYSTEM
#  A player must pass gates to qualify for parlay
#  Gates are checked in order — situation over reputation
# ============================================================

def gate1_pitcher_vulnerable(p, bhand):
    """
    Gate 1: Is the pitcher vulnerable to this batter's hand?
    Must have HR/9 >= 1.2 to that handedness.
    Returns (passes, platoon_hr9, gap_label)
    """
    splits = p.get("splits")
    hr9 = p.get("hr9", 1.2)

    if splits:
        if bhand == "R":
            platoon_hr9 = splits.get("rhb_hr9", hr9)
        elif bhand == "L":
            platoon_hr9 = splits.get("lhb_hr9", hr9)
        else:  # Switch
            platoon_hr9 = max(splits.get("rhb_hr9", hr9), splits.get("lhb_hr9", hr9))

        rhb = splits.get("rhb_hr9", hr9)
        lhb = splits.get("lhb_hr9", hr9)
        gap = abs(rhb - lhb)
        if gap >= 0.8: gap_label = "MASSIVE"
        elif gap >= 0.4: gap_label = "SIGNIFICANT"
        elif gap >= 0.2: gap_label = "MODERATE"
        else: gap_label = "MINIMAL"
    else:
        platoon_hr9 = hr9
        gap_label = "UNKNOWN"

    passes = platoon_hr9 >= 1.2
    return passes, platoon_hr9, gap_label


def gate2_pitcher_trending_worse(p):
    """
    Gate 2: Is the pitcher trending worse recently?
    Last 3 starts ERA must be worse than season ERA.
    OR season HR/9 is already so bad (1.5+) it overrides.
    """
    era = p.get("era", 4.0)
    last3 = p.get("last3_era", era)
    hr9 = p.get("hr9", 1.2)

    # Override — pitcher is already elite-bad
    if hr9 >= 1.5:
        return True, f"Season HR/9 {hr9} — already vulnerable"

    # Trending worse
    if last3 > era:
        return True, f"L3 ERA {last3} vs Season {era} — getting worse"

    return False, f"L3 ERA {last3} vs Season {era} — stable/improving"


def gate3_batter_situation(b, platoon_hr9, era, last3_era):
    """
    Gate 3: Is the batter in a good situation TODAY?
    Must have at least one of:
    - Hot streak (2+ HR last 7 days)
    - Strong platoon advantage (HR/9 gap 0.4+)
    - Pitcher falling apart (last3 ERA 1.5+ worse than season)
    """
    hr7 = b.get("hr7", 0)
    reasons = []

    if hr7 >= HOT_MIN:
        reasons.append(f"🔥 {hr7} HR last 7 days")
    elif hr7 >= 2:
        reasons.append(f"🔥 {hr7} HR last 7 days")

    if platoon_hr9 >= 1.5:
        reasons.append(f"⚔️ Platoon HR/9: {platoon_hr9}")

    diff = last3_era - era
    if diff >= 1.5:
        reasons.append(f"📈 Pitcher L3 ERA up {diff:.1f}")

    return len(reasons) >= 1, reasons


def score_player(b, p, park, spot, splits, platoon_hr9):
    """
    Final score for display ranking.
    Based purely on situation — no reputation factors.
    """
    score = 0

    # Platoon HR/9 — most important
    if platoon_hr9 >= 2.5:   score += 35
    elif platoon_hr9 >= 2.0: score += 28
    elif platoon_hr9 >= 1.7: score += 22
    elif platoon_hr9 >= 1.5: score += 17
    elif platoon_hr9 >= 1.2: score += 12
    elif platoon_hr9 >= 1.0: score += 6
    else: score -= 5

    # Pitcher recent trend
    era = p.get("era", 4.0)
    last3 = p.get("last3_era", era)
    diff = last3 - era
    if diff >= 4.0:   score += 20
    elif diff >= 3.0: score += 16
    elif diff >= 2.0: score += 12
    elif diff >= 1.0: score += 8
    elif diff >= 0.0: score += 3
    elif diff <= -2.0: score -= 8

    # Recent hot streak
    hr7 = b.get("hr7", 0)
    if hr7 >= 4:   score += 20
    elif hr7 >= 3: score += 16
    elif hr7 >= 2: score += 12
    elif hr7 >= 1: score += 6

    # Season HR rate
    hr = b.get("hr", 0)
    games = max(b.get("games", 1), 1)
    hr14 = (hr / games) * 14
    if hr14 >= 6:   score += 12
    elif hr14 >= 4: score += 9
    elif hr14 >= 3: score += 6
    elif hr14 >= 2: score += 3

    # Real Savant power metrics (bonus only — not penalty for missing)
    barrel = b.get("barrel", 0)
    if barrel >= 20:   score += 10
    elif barrel >= 15: score += 7
    elif barrel >= 12: score += 5
    elif barrel >= 10: score += 3

    ev = b.get("ev", 0)
    if ev >= 95: score += 5
    elif ev >= 93: score += 4
    elif ev >= 91: score += 3
    elif ev >= 89: score += 2

    # Park
    pf = PARK_FACTORS.get(park, 100)
    if pf >= 115:   score += 6
    elif pf >= 108: score += 4
    elif pf >= 103: score += 2
    elif pf <= 93:  score -= 2

    # Batting order
    if spot in [3, 4]:      score += 4
    elif spot in [1, 2, 5]: score += 2
    elif spot in [6, 7]:    score += 1

    # Scale to 25-95
    scaled = 30 + (score / 130) * 65
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
        barrel_against = min(18, max(4, (era - 3.0) * 3 + 8))
        last3_era = era
        if game_log:
            recent = game_log[-3:] if len(game_log) >= 3 else game_log
            er = sum(int(g.get("stat", {}).get("earnedRuns", 0)) for g in recent)
            ip = sum(float(g.get("stat", {}).get("inningsPitched", 0) or 0) for g in recent)
            if ip > 0:
                last3_era = round((er / ip) * 9, 2)
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
                    ip = float(s.get("inningsPitched", 1) or 1)
                    c_hr9 = round((h / max(ip, 1)) * 9, 2)
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
            "barrel_against": barrel_against,
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
    # Parlay pool — only players who pass all 3 gates
    parlay_pool = []
    # Display pool — all players for game alerts
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
                if mins_since > 30:
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
                if mins_since > 30:
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
                        "hand": "R", "splits": None}

            home_p = await get_pitcher_stats(session, home_pitcher.get("id")) if home_pitcher.get("id") else dp()
            away_p = await get_pitcher_stats(session, away_pitcher.get("id")) if away_pitcher.get("id") else dp()
            if not home_p: home_p = dp()
            if not away_p: away_p = dp()

            home_p_name = home_pitcher.get("fullName", "TBD")
            away_p_name = away_pitcher.get("fullName", "TBD")

            async def process_lineup(lineup, opp_p, park, opp_p_name):
                ranked = []
                gate_passed = []

                for i, player in enumerate(lineup):
                    pid = player.get("id")
                    pname = player.get("fullName", "Unknown")
                    if not pid: continue
                    b = await get_batter_stats(session, pid)
                    if not b or b.get("hr", 0) < 2: continue

                    bhand = b.get("hand", "R")
                    splits = opp_p.get("splits")

                    # Run through 3 gates
                    g1_pass, platoon_hr9, gap_label = gate1_pitcher_vulnerable(opp_p, bhand)
                    g2_pass, g2_reason = gate2_pitcher_trending_worse(opp_p)
                    g3_pass, g3_reasons = gate3_batter_situation(
                        b, platoon_hr9, opp_p.get("era", 4.0), opp_p.get("last3_era", 4.0)
                    )

                    conf = score_player(b, opp_p, park, i+1, splits, platoon_hr9)

                    odds_data = get_odds(pname)
                    fd_odds = mgm_odds = ev_score = None
                    if odds_data:
                        fd_odds = odds_data["fd"]
                        mgm_odds = odds_data["mgm"]
                        ev_score = calc_ev(conf, fd_odds)

                    player_data = {
                        "name": pname,
                        "conf": conf,
                        "hand": bhand,
                        "platoon_hr9": platoon_hr9,
                        "gap_label": gap_label,
                        "hr7": b.get("hr7", 0),
                        "hr": b.get("hr", 0),
                        "fd_odds": fd_odds,
                        "mgm_odds": mgm_odds,
                        "ev_score": ev_score,
                        "g1": g1_pass,
                        "g2": g2_pass,
                        "g3": g3_pass,
                        "g3_reasons": g3_reasons,
                        "gates_passed": sum([g1_pass, g2_pass, g3_pass]),
                        "game_dt": game_dt,
                        "matchup": matchup,
                        "vs": opp_p_name,
                        "team": park,  # Using park as team abbrev placeholder
                        "savant_real": b.get("savant_real", False),
                        "barrel": b.get("barrel", 0),
                        "ev": b.get("ev", 0),
                        "p_hr9": opp_p.get("hr9", 1.2),
                        "last3_era": opp_p.get("last3_era", 4.0),
                        "era": opp_p.get("era", 4.0),
                    }

                    ranked.append(player_data)

                    # Add to parlay pool if passes all 3 gates
                    if g1_pass and g2_pass and g3_pass:
                        gate_passed.append(player_data)

                ranked.sort(key=lambda x: x["conf"], reverse=True)
                return ranked, gate_passed

            away_ranked, away_gate = await process_lineup(away_lineup, home_p, home_abbrev, home_p_name)
            home_ranked, home_gate = await process_lineup(home_lineup, away_p, home_abbrev, away_p_name)

            # Fix team labels
            for p in away_ranked: p["team"] = away_abbrev
            for p in home_ranked: p["team"] = home_abbrev
            for p in away_gate: p["team"] = away_abbrev
            for p in home_gate: p["team"] = home_abbrev

            # Add gate-passed players to parlay pool
            parlay_pool.extend(away_gate + home_gate)

            # If no players passed all 3 gates — add best 2-gate players
            if not away_gate and not home_gate:
                fallback = sorted(
                    [p for p in away_ranked + home_ranked if p["gates_passed"] >= 2],
                    key=lambda x: x["conf"], reverse=True
                )
                if fallback:
                    parlay_pool.extend(fallback[:2])

            if not away_ranked and not home_ranked:
                continue

            # Build display
            def make_lines(ranked):
                lines = []
                for i, p in enumerate(ranked[:3]):
                    badge = "🔥" if p["hr7"] >= HOT_MIN else "✅" if p["conf"] >= 70 else ""
                    gates = f"[{p['gates_passed']}/3 gates]"
                    odds_str = ""
                    if p.get("fd_odds"):
                        fd = f"+{p['fd_odds']}" if p['fd_odds'] > 0 else str(p['fd_odds'])
                        mgm = f"+{p['mgm_odds']}" if p.get('mgm_odds') and p['mgm_odds'] > 0 else ""
                        odds_str = f" | FD:{fd}"
                        if mgm: odds_str += f" MGM:{mgm}"

                    line = f"{i+1}. {p['name']} ({p['hand']}) — {p['conf']}% {badge} {gates}{odds_str}".strip()

                    if p.get("savant_real"):
                        line += f"\n   Barrel:{p['barrel']:.1f}% EV:{p['ev']:.1f}mph"

                    if p["g3_reasons"]:
                        line += f"\n   {' | '.join(p['g3_reasons'][:2])}"

                    if i == 0 and len(ranked) > 1:
                        next_p = ranked[1]
                        gap = abs(p["conf"] - next_p["conf"])
                        if gap <= 3:
                            p1_odds = p.get("fd_odds")
                            p2_odds = next_p.get("fd_odds")
                            if p1_odds and p2_odds and p2_odds > p1_odds:
                                fd2 = f"+{p2_odds}"
                                line += f"\n   💰 VALUE: {next_p['name']} {fd2} — better odds same data"
                            else:
                                line += f"\n   🔄 INTERCHANGE: {next_p['name']} ({next_p['conf']}%)"

                    lines.append(line)
                return lines

            away_lines = make_lines(away_ranked)
            home_lines = make_lines(home_ranked)

            # Game top pick
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
    #  PARLAY — Only 3-gate players. One per game. Full slate.
    #  Tiebreaker: higher odds wins when within 3%
    # ============================================================
    if not parlay_sent and first_game_time:
        mins_to_first = (first_game_time.replace(tzinfo=datetime.timezone.utc) - now_utc).total_seconds() / 60

        if 10 <= mins_to_first <= 35:
            # Deduplicate
            seen = set()
            unique = []
            for p in parlay_pool:
                if p["name"] not in seen:
                    seen.add(p["name"])
                    unique.append(p)

            # Sort: gates passed first, then conf + EV bonus
            def parlay_sort(p):
                gates = p.get("gates_passed", 0)
                conf = p.get("conf", 0)
                ev = p.get("ev_score") or 0
                fd = p.get("fd_odds") or 200
                # EV boost when players are close
                ev_bonus = (ev * 0.3) + (fd / 200)
                return (gates * 100) + conf + ev_bonus

            unique.sort(key=parlay_sort, reverse=True)

            # Apply tiebreaker — within 3% higher odds wins
            for i in range(len(unique) - 1):
                p1 = unique[i]
                p2 = unique[i+1]
                gap = abs(p1["conf"] - p2["conf"])
                if gap <= 3:
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

            # EV 3-leg — different players, pure value
            pool_4_names = {p["name"] for p in pool_4}
            ev_pool = sorted(unique, key=lambda x: (x.get("ev_score") or 0) + ((x.get("fd_odds") or 200) / 100), reverse=True)
            ev_alt = [p for p in ev_pool if p["name"] not in pool_4_names]
            ev_3 = one_per_game(ev_alt if len(ev_alt) >= 3 else ev_pool, 3)

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
                        time_str = f" {et.strftime('%-I:%M %p ET')}"
                    except:
                        pass
                gates = f"✅{p.get('gates_passed',0)}/3"
                return (
                    f"{i}. {p['name']} ({p.get('hand','')}) — {p['conf']}%{hot} {gates}\n"
                    f"   ⚾ vs {p.get('vs','?')} |{time_str}\n"
                    f"   FD:{fd} MGM:{mgm}{ev_str}"
                )

            if len(pool_2) >= 2:
                msg = "🎯 PARLAYS OF THE DAY\n🌅 FULL SLATE | 3-Gate System\n🔒 One player per game\n━━━━━━━━━━━━━━━━━━━━━━"
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
                # Not enough 3-gate players — send what we have with note
                msg = f"🎯 BEST PLAYS TODAY\n⚠️ Limited 3-gate qualifiers\n━━━━━━━━━━━━━━━━━━━━━━\n"
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
        text="✅ HR SCOUT V5 — 3-GATE SYSTEM\n\n"
             "🚦 PARLAY SELECTION GATES:\n"
             "Gate 1: Pitcher HR/9 to batter hand ≥1.2\n"
             "Gate 2: Pitcher trending worse OR HR/9 ≥1.5\n"
             "Gate 3: Batter hot OR strong platoon OR pitcher falling apart\n\n"
             "💰 Within 3% confidence: higher odds wins\n"
             "🔒 One player per game\n"
             "🌅 Full slate — all games considered\n"
             "📋 Top 3 per team shown with gate count\n\n"
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

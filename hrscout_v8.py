import asyncio
import datetime
import aiohttp
from telegram import Bot

TELEGRAM_TOKEN = "8720993049:AAEimQD4PUDFlMA2bpxXsyW3IMcTZ5ak0PY"
CHAT_ID = "919904024"
SCAN_INTERVAL = 300

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
#  SCORING
# ============================================================
def score_barrel(b):
    if b >= 20: return 100
    if b >= 15: return 88
    if b >= 10: return 72
    if b >= 7:  return 55
    if b >= 5:  return 38
    return 20

def score_ev(e):
    if e >= 96: return 100
    if e >= 93: return 88
    if e >= 90: return 72
    if e >= 87: return 55
    if e >= 85: return 38
    return 20

def score_hh(hh):
    if hh >= 55: return 100
    if hh >= 48: return 85
    if hh >= 40: return 68
    if hh >= 32: return 48
    return 22

def score_flyball(fb):
    if fb >= 50: return 100
    if fb >= 42: return 85
    if fb >= 35: return 68
    if fb >= 28: return 48
    return 22

def score_iso(iso):
    if iso >= 300: return 100
    if iso >= 250: return 88
    if iso >= 200: return 72
    if iso >= 150: return 55
    if iso >= 100: return 38
    return 20

def score_pull(pull):
    if pull >= 50: return 100
    if pull >= 40: return 85
    if pull >= 33: return 65
    if pull >= 25: return 45
    return 20

def score_recent_hr(hr, games):
    hr14 = (hr / max(games, 1)) * 14
    if hr14 >= 6: return 100
    if hr14 >= 4: return 85
    if hr14 >= 3: return 70
    if hr14 >= 2: return 55
    if hr14 >= 1: return 38
    return 18

def score_batter_recent_form(avg7, hr7):
    if hr7 >= 4: return 100
    if hr7 >= 3: return 88
    if hr7 >= 2: return 75
    if hr7 >= 1 and avg7 >= 0.300: return 65
    if hr7 >= 1: return 55
    if avg7 >= 0.320: return 45
    if avg7 >= 0.260: return 35
    return 20

def score_pitcher_hr9(hr9):
    if hr9 >= 2.0: return 100
    if hr9 >= 1.5: return 82
    if hr9 >= 1.2: return 65
    if hr9 >= 1.0: return 48
    if hr9 >= 0.7: return 30
    return 15

def score_pitcher_barrel(b):
    if b >= 14: return 100
    if b >= 11: return 82
    if b >= 8:  return 62
    if b >= 6:  return 45
    return 22

def score_pitcher_recent_form(last3_era, season_era):
    diff = last3_era - season_era
    if diff >= 2.5: return 100
    if diff >= 1.5: return 85
    if diff >= 0.5: return 65
    if diff >= -0.5: return 50
    if diff >= -1.5: return 35
    return 20

def score_park(abbrev):
    f = PARK_FACTORS.get(abbrev, 100)
    if f >= 115: return 100
    if f >= 108: return 80
    if f >= 103: return 65
    if f >= 98:  return 50
    if f >= 93:  return 35
    return 20

def score_batting_order(spot):
    if spot <= 0: return 55
    if spot in [3, 4]: return 90
    if spot in [1, 2, 5]: return 78
    if spot in [6, 7]: return 55
    return 38

def score_platoon_splits(batter_hand, p_splits):
    """
    Score platoon based on real pitcher splits vs RHB and LHB.
    p_splits = {"rhb_hr9": x, "lhb_hr9": x, "rhb_slg": x, "lhb_slg": x}
    """
    if not p_splits:
        return 55  # No data — neutral

    if batter_hand == "S":
        # Switch hitter — use better side
        rhb_hr9 = p_splits.get("rhb_hr9", 1.2)
        lhb_hr9 = p_splits.get("lhb_hr9", 1.2)
        hr9 = max(rhb_hr9, lhb_hr9)
    elif batter_hand == "R":
        hr9 = p_splits.get("rhb_hr9", 1.2)
    else:
        hr9 = p_splits.get("lhb_hr9", 1.2)

    if hr9 >= 2.0: return 100
    if hr9 >= 1.5: return 85
    if hr9 >= 1.2: return 70
    if hr9 >= 0.9: return 52
    if hr9 >= 0.6: return 35
    return 18

def calculate_confidence(b, p, park, spot=0, p_splits=None):
    weights = {
        "barrel":          16,
        "ev":              11,
        "hard_hit":         6,
        "flyball":          6,
        "pull":             8,
        "iso":              8,
        "recent_hr":        8,
        "batter_form":      7,
        "p_hr9":            7,
        "p_barrel":         5,
        "p_recent_form":    7,
        "platoon_splits":   8,  # Real splits — significant weight
        "park":             2,
        "batting_order":    1,
    }
    scores = {
        "barrel":          score_barrel(b.get("barrel", 8)),
        "ev":              score_ev(b.get("ev", 88)),
        "hard_hit":        score_hh(b.get("hh", 35)),
        "flyball":         score_flyball(b.get("fb", 35)),
        "pull":            score_pull(b.get("pull", 35)),
        "iso":             score_iso(b.get("iso", 140)),
        "recent_hr":       score_recent_hr(b.get("hr", 0), b.get("games", 1)),
        "batter_form":     score_batter_recent_form(b.get("avg7", 0.250), b.get("hr7", 0)),
        "p_hr9":           score_pitcher_hr9(p.get("hr9", 1.2)),
        "p_barrel":        score_pitcher_barrel(p.get("barrel_against", 8)),
        "p_recent_form":   score_pitcher_recent_form(p.get("last3_era", 4.0), p.get("era", 4.0)),
        "platoon_splits":  score_platoon_splits(b.get("hand", "R"), p_splits),
        "park":            score_park(park),
        "batting_order":   score_batting_order(spot),
    }
    return round(sum(scores[k] * weights[k] / 100 for k in scores))

def pitcher_trend_label(era, last3_era):
    diff = last3_era - era
    if diff >= 1.5: return "📈 TRENDING WORSE"
    if diff >= 0.5: return "⚠️ SLIGHTLY WORSE"
    if diff <= -1.5: return "📉 IMPROVING"
    if diff <= -0.5: return "✅ SLIGHTLY BETTER"
    return "➡️ STABLE"

def vuln_flag(hr9, barrel):
    if hr9 >= 1.5 or barrel >= 11: return "🚨 VULNERABLE"
    if hr9 >= 1.2 or barrel >= 8: return "⚠️ ELEVATED RISK"
    return "✅ SOLID"

def platoon_gap_label(rhb_hr9, lhb_hr9):
    """Assess how significant the platoon split is."""
    gap = abs(rhb_hr9 - lhb_hr9)
    if gap >= 0.8: return "MASSIVE"
    if gap >= 0.4: return "SIGNIFICANT"
    if gap >= 0.2: return "MODERATE"
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
                games.append(game)
        return games
    except:
        return []

async def get_batter_stats(session, player_id):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season,lastXGames&group=hitting&season=2026&gameType=R"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()

        season_stats = {}
        recent_stats = {}

        for stat_block in data.get("stats", []):
            stat_type = stat_block.get("type", {}).get("displayName", "")
            splits = stat_block.get("splits", [])
            if splits:
                s = splits[0].get("stat", {})
                if "season" in stat_type.lower():
                    season_stats = s
                elif "last" in stat_type.lower():
                    recent_stats = s

        if not season_stats:
            return None

        hr = int(season_stats.get("homeRuns", 0))
        games = int(season_stats.get("gamesPlayed", 1))
        ab = int(season_stats.get("atBats", 1))
        slg = float(season_stats.get("sluggingPercentage", 0.350) or 0.350)
        avg = float(season_stats.get("avg", 0.230) or 0.230)
        iso = round((slg - avg) * 1000)
        fb = min(55, max(22, 30 + (hr / max(ab, 1)) * 150 + (slg - 0.350) * 30))
        pull = min(60, max(25, 37 + (hr / max(ab, 1)) * 160))
        barrel = min(25, max(3, (slg - 0.280) * 50))
        ev = min(98, max(83, 87 + (slg - 0.320) * 25))
        hh = min(65, max(22, 33 + (slg - 0.320) * 60))
        hr7 = int(recent_stats.get("homeRuns", 0))
        avg7 = float(recent_stats.get("avg", avg) or avg)

        savant = await get_savant_stats(player_id)
        if savant:
            if savant["barrel"] > 0: barrel = savant["barrel"]
            if savant["ev"] > 0: ev = savant["ev"]
            if savant["hh"] > 0: hh = savant["hh"]

        # Get batter hand
        player_url = f"https://statsapi.mlb.com/api/v1/people/{player_id}"
        hand = "R"
        try:
            async with session.get(player_url, timeout=aiohttp.ClientTimeout(total=8)) as resp2:
                pdata = await resp2.json()
            hand = pdata.get("people", [{}])[0].get("batSide", {}).get("code", "R")
        except:
            pass

        return {
            "barrel": barrel, "ev": ev, "hh": hh, "fb": fb,
            "hr": hr, "games": games, "iso": iso,
            "pull": pull, "hand": hand,
            "hr7": hr7, "avg7": avg7,
            "slg": slg, "avg": avg,
        }
    except:
        pass
    return None

async def get_pitcher_stats(session, player_id):
    """Get pitcher season stats, last 3 starts ERA, and splits vs LHB/RHB."""
    # Season stats
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season,gameLog,statSplits&group=pitching&season=2026&gameType=R&sitCodes=vr,vl"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            data = await resp.json()

        season_stats = {}
        game_log = []
        rhb_stats = {}
        lhb_stats = {}

        for stat_block in data.get("stats", []):
            stat_type = stat_block.get("type", {}).get("displayName", "")
            splits = stat_block.get("splits", [])
            if "season" in stat_type.lower() and not rhb_stats and splits:
                season_stats = splits[0].get("stat", {})
            elif "log" in stat_type.lower():
                game_log = splits
            elif "split" in stat_type.lower():
                for split in splits:
                    sit = split.get("split", {}).get("code", "")
                    if sit == "vr":
                        rhb_stats = split.get("stat", {})
                    elif sit == "vl":
                        lhb_stats = split.get("stat", {})

        if not season_stats:
            return None

        hr9 = float(season_stats.get("homeRunsPer9", 1.2) or 1.2)
        era = float(season_stats.get("era", 4.00) or 4.00)
        whip = float(season_stats.get("whip", 1.30) or 1.30)
        k9 = float(season_stats.get("strikeoutsPer9Inn", 7.0) or 7.0)
        barrel_against = min(18, max(4, (era - 3.0) * 3 + 8))
        hh_against = min(50, max(25, 30 + (era - 3.5) * 4))

        # Real pitcher splits vs RHB and LHB
        def extract_hr9(stat_dict):
            hr = int(stat_dict.get("homeRuns", 0))
            ip = float(stat_dict.get("inningsPitched", 1) or 1)
            return round((hr / max(ip, 1)) * 9, 2)

        def extract_slg(stat_dict):
            return float(stat_dict.get("sluggingPercentage", 0.400) or 0.400)

        def extract_avg(stat_dict):
            return float(stat_dict.get("avg", 0.250) or 0.250)

        rhb_hr9 = extract_hr9(rhb_stats) if rhb_stats else hr9
        lhb_hr9 = extract_hr9(lhb_stats) if lhb_stats else hr9
        rhb_slg = extract_slg(rhb_stats) if rhb_stats else 0.400
        lhb_slg = extract_slg(lhb_stats) if lhb_stats else 0.400
        rhb_avg = extract_avg(rhb_stats) if rhb_stats else 0.250
        lhb_avg = extract_avg(lhb_stats) if lhb_stats else 0.250

        # Last 3 starts real ERA
        last3_era = era
        if game_log:
            recent = game_log[-3:] if len(game_log) >= 3 else game_log
            total_er = sum(int(g.get("stat", {}).get("earnedRuns", 0)) for g in recent)
            total_ip = sum(float(g.get("stat", {}).get("inningsPitched", 0) or 0) for g in recent)
            if total_ip > 0:
                last3_era = round((total_er / total_ip) * 9, 2)

        # Pitcher hand
        player_url = f"https://statsapi.mlb.com/api/v1/people/{player_id}"
        p_hand = "R"
        try:
            async with session.get(player_url, timeout=aiohttp.ClientTimeout(total=8)) as resp2:
                pdata = await resp2.json()
            p_hand = pdata.get("people", [{}])[0].get("pitchHand", {}).get("code", "R")
        except:
            pass

        splits = {
            "rhb_hr9": rhb_hr9, "lhb_hr9": lhb_hr9,
            "rhb_slg": rhb_slg, "lhb_slg": lhb_slg,
            "rhb_avg": rhb_avg, "lhb_avg": lhb_avg,
        }

        return {
            "hr9": hr9, "era": era, "whip": whip, "k9": k9,
            "barrel_against": barrel_against, "hh_against": hh_against,
            "last3_era": last3_era, "hand": p_hand,
            "splits": splits,
        }
    except:
        pass
    return None

# ============================================================
#  PLATOON TIEBREAKER
# ============================================================
def resolve_platoon_tiebreaker(p1, p2, threshold=3):
    """
    Compare two nearly identical players.
    threshold = max % confidence gap to consider interchangeable.
    Returns (winner, loser, decision_type, note)
    decision_type: "CLEAR_WINNER" | "INTERCHANGEABLE" | "PLATOON_SWAP"
    """
    gap = abs(p1["conf"] - p2["conf"])

    if gap > threshold:
        # Not close enough to be interchangeable
        winner = p1 if p1["conf"] >= p2["conf"] else p2
        return winner, None, "CLEAR_WINNER", None

    # They're within threshold — check platoon splits
    p1_platoon = p1.get("platoon_hr9", 1.2)
    p2_platoon = p2.get("platoon_hr9", 1.2)
    platoon_gap = abs(p1_platoon - p2_platoon)

    if platoon_gap >= 0.4:
        # Significant platoon edge — pick better platoon
        if p1_platoon >= p2_platoon:
            return p1, p2, "PLATOON_SWAP" if p2["conf"] > p1["conf"] else "CLEAR_WINNER", f"Platoon HR/9: {p1['name']} {p1_platoon} vs {p2['name']} {p2_platoon}"
        else:
            return p2, p1, "PLATOON_SWAP" if p1["conf"] > p2["conf"] else "CLEAR_WINNER", f"Platoon HR/9: {p2['name']} {p2_platoon} vs {p1['name']} {p1_platoon}"
    else:
        # Still close after platoon — flag as interchangeable
        winner = p1 if p1["conf"] >= p2["conf"] else p2
        loser = p2 if p1["conf"] >= p2["conf"] else p1
        note = f"{loser['name']} ({loser['conf']}%) — similar profile, platoon gap minimal ({platoon_gap:.2f} HR/9)"
        return winner, loser, "INTERCHANGEABLE", note

# ============================================================
#  GAME STATE
# ============================================================
def build_game_state(game, home_lineup, away_lineup):
    home_pid = game.get("teams", {}).get("home", {}).get("probablePitcher", {}).get("id", "")
    away_pid = game.get("teams", {}).get("away", {}).get("probablePitcher", {}).get("id", "")
    home_ids = tuple(p.get("id") for p in home_lineup)
    away_ids = tuple(p.get("id") for p in away_lineup)
    return f"{home_pid}_{away_pid}_{home_ids}_{away_ids}"

# ============================================================
#  MAIN SCAN
# ============================================================
async def run_scan(bot, game_states=None, parlay_sent=False):
    if game_states is None:
        game_states = {}

    new_states = dict(game_states)
    all_top_picks = []
    first_game_time = None

    async with aiohttp.ClientSession() as session:
        await load_savant_data(session)

        games = await get_todays_games(session)
        if not games:
            return game_states, parlay_sent

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
            status = game.get("status", {}).get("abstractGameState", "")
            if status == "Final":
                continue

            home_team_name = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "")
            away_team_name = game.get("teams", {}).get("away", {}).get("team", {}).get("name", "")
            home_abbrev = TEAM_ABBREV.get(home_team_name, "???")
            away_abbrev = TEAM_ABBREV.get(away_team_name, "???")

            home_pitcher = game.get("teams", {}).get("home", {}).get("probablePitcher", {})
            away_pitcher = game.get("teams", {}).get("away", {}).get("probablePitcher", {})

            lineups = game.get("lineups", {})
            home_lineup = lineups.get("homePlayers", [])
            away_lineup = lineups.get("awayPlayers", [])

            if not home_lineup and not away_lineup:
                continue

            current_state = build_game_state(game, home_lineup, away_lineup)
            prev_state = game_states.get(game_id)

            if prev_state == current_state:
                continue

            change_notice = ""
            if prev_state is not None:
                prev_parts = prev_state.split("_")
                curr_parts = current_state.split("_")
                if prev_parts[0] != curr_parts[0]:
                    change_notice = f"\n🚨 PITCHER CHANGE — {home_abbrev} starter changed — RESCORING"
                elif prev_parts[1] != curr_parts[1]:
                    change_notice = f"\n🚨 PITCHER CHANGE — {away_abbrev} starter changed — RESCORING"
                else:
                    change_notice = f"\n🔄 LINEUP CHANGE — RESCORING"

            new_states[game_id] = current_state

            game_time = game.get("gameDate", "")
            try:
                dt = datetime.datetime.fromisoformat(game_time.replace("Z", "+00:00"))
                local_time = dt.strftime("%-I:%M %p ET")
            except:
                local_time = "TBD"

            home_p = await get_pitcher_stats(session, home_pitcher.get("id")) if home_pitcher.get("id") else None
            away_p = await get_pitcher_stats(session, away_pitcher.get("id")) if away_pitcher.get("id") else None

            def default_p():
                return {"hr9": 1.2, "barrel_against": 8.0, "hh_against": 34, "era": 4.00, "whip": 1.30, "k9": 7.0, "last3_era": 4.00, "hand": "R", "splits": None}

            if not home_p: home_p = default_p()
            if not away_p: away_p = default_p()

            home_pitcher_name = home_pitcher.get("fullName", "TBD")
            away_pitcher_name = away_pitcher.get("fullName", "TBD")

            # Score all batters with real platoon splits
            async def score_lineup(lineup, opp_pitcher, park):
                ranked = []
                for i, player in enumerate(lineup):
                    pid = player.get("id")
                    pname = player.get("fullName", "Unknown")
                    if not pid: continue
                    b = await get_batter_stats(session, pid)
                    if not b or b.get("hr", 0) < 3: continue

                    p_splits = opp_pitcher.get("splits")

                    # Get this batter's specific platoon HR/9 against this pitcher
                    bhand = b.get("hand", "R")
                    platoon_hr9 = opp_pitcher["hr9"]  # Default
                    if p_splits:
                        if bhand == "R":
                            platoon_hr9 = p_splits.get("rhb_hr9", opp_pitcher["hr9"])
                        elif bhand == "L":
                            platoon_hr9 = p_splits.get("lhb_hr9", opp_pitcher["hr9"])
                        elif bhand == "S":
                            platoon_hr9 = max(p_splits.get("rhb_hr9", 0), p_splits.get("lhb_hr9", 0))

                    conf = calculate_confidence(b, opp_pitcher, park, i+1, p_splits)
                    ranked.append({
                        "name": pname,
                        "conf": conf,
                        "hand": bhand,
                        "platoon_hr9": platoon_hr9,
                        "hr7": b.get("hr7", 0),
                        "hr": b.get("hr", 0),
                        "avg7": b.get("avg7", 0.250),
                    })
                ranked.sort(key=lambda x: x["conf"], reverse=True)
                return ranked

            away_ranked = await score_lineup(away_lineup, home_p, home_abbrev)
            home_ranked = await score_lineup(home_lineup, away_p, home_abbrev)

            if not away_ranked and not home_ranked:
                continue

            # Build display lines with tiebreaker flags
            def make_lines(ranked, opp_pitcher):
                lines = []
                for i, p in enumerate(ranked):
                    badge = "🔥" if p["conf"] >= 82 else "✅" if p["conf"] >= 70 else "▪️"
                    hot = " 🌶️" if p["hr7"] >= 2 else ""
                    line = f"{i+1}. {p['name']} ({p['hand']}) — {p['conf']}% {badge}{hot}"

                    # ONLY check tiebreaker for the #1 pick
                    if i == 0 and len(ranked) > 1:
                        next_p = ranked[1]
                        winner, loser, decision, note = resolve_platoon_tiebreaker(p, next_p)
                        if decision == "INTERCHANGEABLE" and note:
                            line += f"\n   🔄 INTERCHANGEABLE with {next_p['name']} ({next_p['conf']}%) — platoon gap minimal"
                        elif decision == "PLATOON_SWAP":
                            line += f"\n   ⚔️ LOCKS over {next_p['name']} — {p['hand']}HB splits: {p['platoon_hr9']} HR/9 vs {next_p['platoon_hr9']} HR/9"

                    lines.append(line)
                return lines

            # Pitcher splits display
            def splits_display(p_stats, pitcher_name):
                splits = p_stats.get("splits")
                if not splits:
                    return ""
                rhb_hr9 = splits.get("rhb_hr9", 0)
                lhb_hr9 = splits.get("lhb_hr9", 0)
                rhb_slg = splits.get("rhb_slg", 0)
                lhb_slg = splits.get("lhb_slg", 0)
                rhb_avg = splits.get("rhb_avg", 0)
                lhb_avg = splits.get("lhb_avg", 0)
                gap_label = platoon_gap_label(rhb_hr9, lhb_hr9)
                vuln_side = "RHB" if rhb_hr9 > lhb_hr9 else "LHB"
                return (
                    f"  Splits vs RHB: {rhb_avg:.3f} AVG / {rhb_slg:.3f} SLG / {rhb_hr9} HR/9\n"
                    f"  Splits vs LHB: {lhb_avg:.3f} AVG / {lhb_slg:.3f} SLG / {lhb_hr9} HR/9\n"
                    f"  ⚔️ Platoon gap: {gap_label} — more vulnerable to {vuln_side}"
                )

            away_lines = make_lines(away_ranked, home_p)
            home_lines = make_lines(home_ranked, away_p)

            # Game top pick
            all_candidates = away_ranked + home_ranked
            all_candidates.sort(key=lambda x: x["conf"], reverse=True)

            game_top = None
            if all_candidates:
                t = all_candidates[0]
                team = away_abbrev if t in away_ranked else home_abbrev
                vs = home_pitcher_name if t in away_ranked else away_pitcher_name
                game_top = {**t, "team": team, "vs": vs, "matchup": f"{away_abbrev} @ {home_abbrev}"}
                all_top_picks.append(game_top)

            away_splits = splits_display(home_p, home_pitcher_name)
            home_splits = splits_display(away_p, away_pitcher_name)

            msg = f"""
⚾ {away_abbrev} @ {home_abbrev} — {local_time}{change_notice}
🏟️ {home_team_name}
━━━━━━━━━━━━━━━━━━━━━━
🔱 PITCHING MATCHUP
━━━━━━━━━━━━━━━━━━━━━━
{away_abbrev} → {away_pitcher_name} {vuln_flag(away_p['hr9'], away_p['barrel_against'])}
• HR/9: {away_p['hr9']} | ERA: {away_p['era']} | WHIP: {away_p['whip']} | K/9: {away_p['k9']}
• Barrel Allowed: {away_p['barrel_against']}% | Hard Hit Against: {away_p['hh_against']}%
• Last 3 Starts ERA: {away_p['last3_era']} {pitcher_trend_label(away_p['era'], away_p['last3_era'])}
{away_splits}

{home_abbrev} → {home_pitcher_name} {vuln_flag(home_p['hr9'], home_p['barrel_against'])}
• HR/9: {home_p['hr9']} | ERA: {home_p['era']} | WHIP: {home_p['whip']} | K/9: {home_p['k9']}
• Barrel Allowed: {home_p['barrel_against']}% | Hard Hit Against: {home_p['hh_against']}%
• Last 3 Starts ERA: {home_p['last3_era']} {pitcher_trend_label(home_p['era'], home_p['last3_era'])}
{home_splits}
━━━━━━━━━━━━━━━━━━━━━━
📊 {away_abbrev} HR RANKINGS vs {home_pitcher_name}
{chr(10).join(away_lines) if away_lines else "No qualified batters"}
━━━━━━━━━━━━━━━━━━━━━━
📊 {home_abbrev} HR RANKINGS vs {away_pitcher_name}
{chr(10).join(home_lines) if home_lines else "No qualified batters"}
━━━━━━━━━━━━━━━━━━━━━━
🏆 GAME TOP PICK:
{game_top['name']} ({game_top['team']}) — {game_top['conf']}%
━━━━━━━━━━━━━━━━━━━━━━""".strip()

            await bot.send_message(chat_id=CHAT_ID, text=msg)
            await asyncio.sleep(2)

    # ============================================================
    #  PARLAY OF THE DAY — 30 mins before first pitch
    # ============================================================
    if not parlay_sent and first_game_time and all_top_picks:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        mins_to_first = (first_game_time.replace(tzinfo=datetime.timezone.utc) - now_utc).total_seconds() / 60

        if 0 <= mins_to_first <= 35:
            all_top_picks.sort(key=lambda x: x["conf"], reverse=True)

            seen = set()
            unique = []
            for p in all_top_picks:
                if p["name"] not in seen:
                    seen.add(p["name"])
                    unique.append(p)

            if len(unique) >= 2:
                def leg(p, i):
                    return (
                        f"{i}. {p['name']} ({p['hand']}) — {p['conf']}%\n"
                        f"   ⚾ vs {p['vs']} | {p['matchup']}\n"
                        f"   Platoon HR/9: {p['platoon_hr9']}"
                    )

                msg = f"🎯 PARLAY OF THE DAY\n⏰ First pitch in ~{int(mins_to_first)} mins\n🚫 No chalk bias — data ranked only\n━━━━━━━━━━━━━━━━━━━━━━\n"

                if len(unique) >= 2:
                    msg += "\n2️⃣ 2-LEG PARLAY\n" + "\n".join(leg(unique[i], i+1) for i in range(2))

                if len(unique) >= 3:
                    msg += "\n\n3️⃣ 3-LEG PARLAY\n" + "\n".join(leg(unique[i], i+1) for i in range(3))

                if len(unique) >= 4:
                    msg += "\n\n4️⃣ 4-LEG PARLAY\n" + "\n".join(leg(unique[i], i+1) for i in range(4))

                msg += "\n━━━━━━━━━━━━━━━━━━━━━━"

                # Check for interchangeable players in parlay
                if len(unique) >= 2:
                    swaps = []
                    for i in range(min(4, len(unique))):
                        for j in range(i+1, min(len(unique), i+4)):
                            _, loser, decision, note = resolve_platoon_tiebreaker(unique[i], unique[j])
                            if decision == "INTERCHANGEABLE" and note:
                                swaps.append(f"• Leg {i+1}: {note}")
                    if swaps:
                        msg += "\n\n🔄 INTERCHANGEABLE NOTES:\n" + "\n".join(swaps)

                await bot.send_message(chat_id=CHAT_ID, text=msg)
                parlay_sent = True

    return new_states, parlay_sent

# ============================================================
#  MAIN LOOP
# ============================================================
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID,
        text="✅ HR SCOUT V5 — PLATOON SPLITS EDITION\n\n⚔️ Real pitcher splits vs RHB/LHB\n🔄 Interchangeable player flags\n🚨 Platoon swap when gap is significant\n🎯 3 parlays 30 mins before first pitch\n📈 Real last 3 starts ERA\n🌶️ Hot hitters flagged\n\nWaiting for confirmed lineups...")
    await asyncio.sleep(2)

    game_states = {}
    parlay_sent = False
    last_date = None

    while True:
        now = datetime.datetime.now()
        today = now.date()
        if last_date != today:
            parlay_sent = False
            last_date = today

        try:
            game_states, parlay_sent = await run_scan(bot, game_states, parlay_sent)
        except Exception as e:
            await bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Error: {str(e)[:200]}")

        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())

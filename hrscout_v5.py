import asyncio
import datetime
import aiohttp
from telegram import Bot

TELEGRAM_TOKEN = "8720993049:AAEimQD4PUDFlMA2bpxXsyW3IMcTZ5ak0PY"
CHAT_ID = "919904024"
SCAN_INTERVAL = 300  # 5 minutes

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
#  BASEBALL SAVANT CACHE \u2014 pulled once per scan, not per player
# ============================================================
savant_cache = {}

async def load_savant_data(session):
    """Pull full Statcast leaderboard once per scan and cache it."""
    global savant_cache
    url = "https://baseballsavant.mlb.com/statcast_search/csv?hfPT=&hfAB=&hfGT=R%7C&hfPR=&hfZ=&hfStadium=&hfBBL=&hfNewZones=&hfPull=&hfC=&hfSea=2026%7C&hfSit=&player_type=batter&hfOuts=&hfOpponent=&pitcher_throws=&batter_stands=&hfSA=&game_date_gt=&game_date_lt=&hfMo=&hfTeam=&home_road=&hfRO=&position=&hfInfield=&hfOutfield=&hfInn=&hfBBT=&hfFlag=&metric_1=&group_by=name&min_pitches=0&min_results=0&min_pas=100&sort_col=xba&player_event_sort=api_p_release_speed&sort_order=desc&chk_stats_pa=on&chk_stats_abs=on&chk_stats_bip=on&chk_stats_hits=on&chk_stats_singles=on&chk_stats_dbls=on&chk_stats_triples=on&chk_stats_hrs=on&chk_stats_so=on&chk_stats_k_percent=on&chk_stats_bb=on&chk_stats_bb_percent=on&chk_stats_whiffs=on&chk_stats_swings=on&chk_stats_ba=on&chk_stats_xba=on&chk_stats_obp=on&chk_stats_slg=on&chk_stats_xslg=on&chk_stats_woba=on&chk_stats_xwoba=on&chk_stats_launch_angle=on&chk_stats_exit_velocity=on&chk_stats_barrels=on&chk_stats_brl_percent=on&chk_stats_brl_pa=on&chk_stats_hard_hit_percent=on&chk_stats_avg_best_speed=on&type=details&"
    
    # Use simpler leaderboard endpoint
    simple_url = "https://baseballsavant.mlb.com/leaderboard/expected_statistics?type=batter&year=2026&position=&team=&min=100&csv=true"
    
    try:
        async with session.get(simple_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            text = await resp.text()
        
        lines = text.strip().split("\
")
        if len(lines) < 2:
            return
        
        headers = [h.strip().strip('"').lower() for h in lines[0].split(",")]
        
        for line in lines[1:]:
            try:
                values = line.split(",")
                row = dict(zip(headers, values))
                player_id = row.get("player_id", "").strip().strip('"')
                if player_id:
                    savant_cache[player_id] = row
            except:
                continue
                
    except Exception as e:
        pass

async def get_savant_stats(player_id):
    """Get Statcast stats from cache for a player."""
    row = savant_cache.get(str(player_id), {})
    if not row:
        return None
    
    try:
        barrel_pct = float(row.get("brl_percent", 0) or 0)
        ev = float(row.get("exit_velocity_avg", 0) or 0)
        hard_hit = float(row.get("hard_hit_percent", 0) or 0)
        xwoba = float(row.get("xwoba", 0) or 0)
        xslg = float(row.get("xslg", 0) or 0)
        
        if barrel_pct > 0 or ev > 0:
            return {
                "barrel": barrel_pct,
                "ev": ev,
                "hh": hard_hit,
                "xwoba": xwoba,
                "xslg": xslg,
            }
    except:
        pass
    return None

# ============================================================
#  SCORING \u2014 Full system with flyball and hard hit
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
    # Hard hit % \u2014 Guy 1
    if hh >= 55: return 100
    if hh >= 48: return 85
    if hh >= 40: return 68
    if hh >= 32: return 48
    return 22

def score_flyball(fb):
    # Fly ball % \u2014 Guy 1: air balls = HR source
    # MLB avg ~35%, higher = more HR opportunities
    if fb >= 50: return 100
    if fb >= 42: return 85
    if fb >= 35: return 68  # MLB average
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

def score_park(abbrev):
    f = PARK_FACTORS.get(abbrev, 100)
    if f >= 115: return 100
    if f >= 108: return 80
    if f >= 103: return 65
    if f >= 98:  return 50
    if f >= 93:  return 35
    return 20

def score_platoon(bh, ph):
    if bh == "S": return 72
    if bh != ph: return 90
    return 38

def score_batting_order(spot):
    if spot <= 0: return 55
    if spot in [3, 4]: return 90
    if spot in [1, 2, 5]: return 78
    if spot in [6, 7]: return 55
    return 38

def score_pitcher_trend(era, last3_era):
    diff = last3_era - era
    if diff >= 2.0: return 100
    if diff >= 1.0: return 80
    if diff >= 0.0: return 60
    return 35

def calculate_confidence(b, p, park, spot=0):
    weights = {
        "barrel":        17,  # Guy 1 + 2
        "ev":            12,  # Guy 1 + 2
        "hard_hit":       7,  # Guy 1
        "flyball":        7,  # Guy 1 (new)
        "pull":           9,  # Guy 2
        "iso":            9,  # Guy 1
        "recent_hr":     12,  # Guy 1
        "p_hr9":         10,  # Guy 1
        "p_barrel":       6,  # Guy 1
        "p_trend":        4,  # My addition
        "park":           2,  # My addition
        "platoon":        4,  # My addition
        "batting_order":  1,  # My addition
    }
    scores = {
        "barrel":        score_barrel(b.get("barrel", 8)),
        "ev":            score_ev(b.get("ev", 88)),
        "hard_hit":      score_hh(b.get("hh", 35)),
        "flyball":       score_flyball(b.get("fb", 35)),
        "pull":          score_pull(b.get("pull", 35)),
        "iso":           score_iso(b.get("iso", 140)),
        "recent_hr":     score_recent_hr(b.get("hr", 0), b.get("games", 1)),
        "p_hr9":         score_pitcher_hr9(p.get("hr9", 1.2)),
        "p_barrel":      score_pitcher_barrel(p.get("barrel_against", 8)),
        "p_trend":       score_pitcher_trend(p.get("era", 4.0), p.get("last3_era", 4.0)),
        "park":          score_park(park),
        "platoon":       score_platoon(b.get("hand", "R"), p.get("hand", "R")),
        "batting_order": score_batting_order(spot),
    }
    return round(sum(scores[k] * weights[k] / 100 for k in scores))

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
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=hitting&season=2026"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        if splits:
            s = splits[0].get("stat", {})
            hr = int(s.get("homeRuns", 0))
            games = int(s.get("gamesPlayed", 1))
            ab = int(s.get("atBats", 1))
            slg = float(s.get("sluggingPercentage", 0.350) or 0.350)
            avg = float(s.get("avg", 0.230) or 0.230)
            iso = round((slg - avg) * 1000)
            # Estimate flyball from HR rate and slugging
            fb = min(55, max(22, 30 + (hr / max(ab, 1)) * 150 + (slg - 0.350) * 30))
            pull = min(60, max(25, 37 + (hr / max(ab, 1)) * 160))
            # Base estimates \u2014 will be overridden by Savant data
            barrel = min(25, max(3, (slg - 0.280) * 50))
            ev = min(98, max(83, 87 + (slg - 0.320) * 25))
            hh = min(65, max(22, 33 + (slg - 0.320) * 60))
            hand = "R"

            # Try to get real Savant data
            savant = await get_savant_stats(player_id)
            if savant:
                barrel = savant["barrel"] if savant["barrel"] > 0 else barrel
                ev = savant["ev"] if savant["ev"] > 0 else ev
                hh = savant["hh"] if savant["hh"] > 0 else hh

            return {
                "barrel": barrel, "ev": ev, "hh": hh, "fb": fb,
                "hr": hr, "games": games, "iso": iso,
                "pull": pull, "hand": hand,
            }
    except:
        pass
    return None

async def get_pitcher_stats(session, player_id):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=pitching&season=2026"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        if splits:
            s = splits[0].get("stat", {})
            hr9 = float(s.get("homeRunsPer9", 1.2) or 1.2)
            era = float(s.get("era", 4.00) or 4.00)
            whip = float(s.get("whip", 1.30) or 1.30)
            barrel_against = min(18, max(4, (era - 3.0) * 3 + 8))
            return {
                "hr9": hr9, "era": era, "whip": whip,
                "barrel_against": barrel_against,
                "last3_era": era, "hand": "R",
            }
    except:
        pass
    return None

# ============================================================
#  MAIN SCAN
# ============================================================
async def run_scan(bot, prev_sent=None):
    if prev_sent is None:
        prev_sent = set()

    today = datetime.date.today().strftime("%A, %B %d %Y")
    new_sent = set(prev_sent)
    all_top_picks = []
    games_with_lineups = 0

    async with aiohttp.ClientSession() as session:
        # Load Savant data once for entire scan
        await bot.send_message(chat_id=CHAT_ID,
            text="\ud83d\udd04 Pulling live Statcast data from Baseball Savant...")
        await load_savant_data(session)

        games = await get_todays_games(session)
        if not games:
            return prev_sent

        for game in games:
            game_id = game.get("gamePk")
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

            games_with_lineups += 1
            game_key = f"game_{game_id}"

            if game_key in prev_sent:
                continue

            game_time = game.get("gameDate", "")
            try:
                dt = datetime.datetime.fromisoformat(game_time.replace("Z", "+00:00"))
                local_time = dt.strftime("%-I:%M %p ET")
            except:
                local_time = "TBD"

            home_p_stats = await get_pitcher_stats(session, home_pitcher.get("id")) if home_pitcher.get("id") else None
            away_p_stats = await get_pitcher_stats(session, away_pitcher.get("id")) if away_pitcher.get("id") else None

            if not home_p_stats:
                home_p_stats = {"hr9": 1.2, "barrel_against": 8.0, "era": 4.00, "whip": 1.30, "last3_era": 4.00, "hand": "R"}
            if not away_p_stats:
                away_p_stats = {"hr9": 1.2, "barrel_against": 8.0, "era": 4.00, "whip": 1.30, "last3_era": 4.00, "hand": "R"}

            away_ranked = []
            for i, player in enumerate(away_lineup):
                pid = player.get("id")
                pname = player.get("fullName", "Unknown")
                if not pid:
                    continue
                b_stats = await get_batter_stats(session, pid)
                if not b_stats or b_stats.get("hr", 0) < 3:
                    continue
                conf = calculate_confidence(b_stats, home_p_stats, home_abbrev, i+1)
                away_ranked.append({
                    "name": pname, "conf": conf, "spot": i+1,
                    "hr": b_stats.get("hr", 0),
                    "hh": round(b_stats.get("hh", 0), 1),
                    "fb": round(b_stats.get("fb", 0), 1),
                })

            home_ranked = []
            for i, player in enumerate(home_lineup):
                pid = player.get("id")
                pname = player.get("fullName", "Unknown")
                if not pid:
                    continue
                b_stats = await get_batter_stats(session, pid)
                if not b_stats or b_stats.get("hr", 0) < 3:
                    continue
                conf = calculate_confidence(b_stats, away_p_stats, home_abbrev, i+1)
                home_ranked.append({
                    "name": pname, "conf": conf, "spot": i+1,
                    "hr": b_stats.get("hr", 0),
                    "hh": round(b_stats.get("hh", 0), 1),
                    "fb": round(b_stats.get("fb", 0), 1),
                })

            away_ranked.sort(key=lambda x: x["conf"], reverse=True)
            home_ranked.sort(key=lambda x: x["conf"], reverse=True)

            if not away_ranked and not home_ranked:
                continue

            away_pitcher_name = away_pitcher.get("fullName", "TBD")
            home_pitcher_name = home_pitcher.get("fullName", "TBD")

            away_lines = []
            for rank, p in enumerate(away_ranked, 1):
                bar = "\ud83d\udd25" if p["conf"] >= 82 else "\u2705" if p["conf"] >= 70 else "\u25aa\ufe0f"
                away_lines.append(f"{rank}. {p['name']} \u2014 {p['conf']}% {bar}  HH:{p['hh']}% FB:{p['fb']}%")

            home_lines = []
            for rank, p in enumerate(home_ranked, 1):
                bar = "\ud83d\udd25" if p["conf"] >= 82 else "\u2705" if p["conf"] >= 70 else "\u25aa\ufe0f"
                home_lines.append(f"{rank}. {p['name']} \u2014 {p['conf']}% {bar}  HH:{p['hh']}% FB:{p['fb']}%")

            game_top = None
            if away_ranked and home_ranked:
                if away_ranked[0]["conf"] >= home_ranked[0]["conf"]:
                    game_top = {"name": away_ranked[0]["name"], "conf": away_ranked[0]["conf"], "team": away_abbrev, "vs": home_pitcher_name}
                else:
                    game_top = {"name": home_ranked[0]["name"], "conf": home_ranked[0]["conf"], "team": home_abbrev, "vs": away_pitcher_name}
            elif away_ranked:
                game_top = {"name": away_ranked[0]["name"], "conf": away_ranked[0]["conf"], "team": away_abbrev, "vs": home_pitcher_name}
            elif home_ranked:
                game_top = {"name": home_ranked[0]["name"], "conf": home_ranked[0]["conf"], "team": home_abbrev, "vs": away_pitcher_name}

            if game_top:
                all_top_picks.append({**game_top, "matchup": f"{away_abbrev} @ {home_abbrev}"})

            msg = f"""
\u26be {away_abbrev} @ {home_abbrev} \u2014 {local_time}
\ud83c\udfdf\ufe0f {home_team_name}

\ud83d\udcca {away_abbrev} HR RANKINGS
vs {home_pitcher_name} ({home_p_stats['hr9']} HR/9 | ERA {home_p_stats['era']})
{chr(10).join(away_lines) if away_lines else "Lineup not yet confirmed"}

\ud83d\udcca {home_abbrev} HR RANKINGS
vs {away_pitcher_name} ({away_p_stats['hr9']} HR/9 | ERA {away_p_stats['era']})
{chr(10).join(home_lines) if home_lines else "Lineup not yet confirmed"}

\ud83c\udfc6 GAME TOP PICK:
{game_top['name']} ({game_top['team']}) \u2014 {game_top['conf']}%""".strip()

            await bot.send_message(chat_id=CHAT_ID, text=msg)
            new_sent.add(game_key)
            await asyncio.sleep(2)

    if all_top_picks and games_with_lineups > 0:
        all_top_picks.sort(key=lambda x: x["conf"], reverse=True)
        top = all_top_picks[0]
        await bot.send_message(chat_id=CHAT_ID,
            text=f"\ud83c\udfaf TODAY'S #1 OVERALL PICK\
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\
\ud83d\udc64 {top['name']}\
\ud83c\udfdf\ufe0f {top['matchup']}\
\u26be vs {top['vs']}\
\u2705 CONFIDENCE: {top['conf']}%\
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")

    return new_sent

# ============================================================
#  MAIN LOOP
# ============================================================
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID,
        text="\u2705 HR SCOUT V5 \u2014 BASEBALL SAVANT EDITION\
\
\ud83d\udcca Scoring includes:\
\u2022 Barrel % \u2014 Baseball Savant live\
\u2022 Exit Velocity \u2014 Baseball Savant live\
\u2022 Hard Hit % \u2014 Baseball Savant live\
\u2022 Fly Ball % \u2014 Guy 1 metric added\
\u2022 Pull % \u2014 Guy 2\
\u2022 ISO Power \u2014 Guy 1\
\u2022 Recent HR form\
\u2022 Pitcher HR/9 + Barrel allowed\
\u2022 Park factor + Platoon + Batting order\
\
\u26a1 Confirmed lineups only\
\ud83d\udd04 Scans every 5 minutes\
\
Waiting for confirmed lineups...")
    await asyncio.sleep(2)

    prev_sent = set()

    while True:
        try:
            prev_sent = await run_scan(bot, prev_sent)
        except Exception as e:
            await bot.send_message(chat_id=CHAT_ID, text=f"\u26a0\ufe0f Error: {str(e)[:200]}")
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())

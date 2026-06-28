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
#  PROJECTED LINEUPS — lineups.com scraper
#  Runs in morning before confirmed lineups drop
# ============================================================
projected_lineups_cache = {}

async def load_projected_lineups(session):
    """
    Load projected lineups from Rotowire — posts by 10am ET daily.
    Falls back to MLB Stats API active rosters.
    """
    global projected_lineups_cache
    
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    
    # Try Rotowire first — most reliable projected lineups
    try:
        url = "https://www.rotowire.com/baseball/daily-lineups.php"
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            html = await resp.text()
        
        import re
        # Rotowire uses specific CSS classes for lineup players
        # Extract team abbreviations and player names
        games_raw = re.findall(
            r'class="lineup__team[^"]*"[^>]*>.*?<div class="lineup__list[^"]*">(.*?)</div>',
            html, re.DOTALL
        )
        
        players_by_team = {}
        team_sections = re.findall(
            r'class="lineup__abbr">([A-Z]+)<.*?class="lineup__list[^"]*">(.*?)</ul>',
            html, re.DOTALL
        )
        
        for team, lineup_html in team_sections:
            player_names = re.findall(r"href=\"[^\"]*\">([A-Z]\. [A-Za-z'-]+)", lineup_html)
            if player_names:
                players_by_team[team] = player_names
        
        if players_by_team:
            projected_lineups_cache = players_by_team
            return
    except:
        pass
    
    # Fallback — lineups.com
    try:
        url = "https://www.lineups.com/mlb/lineups/"
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            html = await resp.text()
        import re
        players_by_team = {}
        sections = re.findall(r'data-team="([A-Z]+)".*?class="lineup[^"]*">(.*?)</div>', html, re.DOTALL)
        for team, section in sections:
            names = re.findall(r"([A-Z][a-z]+ [A-Z][a-z]+)", section)
            if names:
                players_by_team[team] = names
        if players_by_team:
            projected_lineups_cache = players_by_team
    except:
        pass


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
            status = game.get("status", {}).get("abstractGameState", "")
            if status in ["Final", "Live"]:
                continue
            gt = game.get("gameDate", "")
            try:
                dt = datetime.datetime.fromisoformat(gt.replace("Z", "+00:00"))
                now_utc = datetime.datetime.now(datetime.timezone.utc)
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
            detailed_status = game.get("status", {}).get("detailedState", "")
            
            # Skip any game that has started, is live, or is finished
            if status in ["Final", "Live"]:
                continue
            if detailed_status in ["In Progress", "Final", "Game Over", "Completed Early", 
                                   "Postponed", "Suspended", "Cancelled"]:
                continue
            
            # Skip if game start time has already passed by more than 30 minutes
            gt_str = game.get("gameDate", "")
            try:
                dt = datetime.datetime.fromisoformat(gt_str.replace("Z", "+00:00"))
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                mins_since_start = (now_utc - dt.replace(tzinfo=datetime.timezone.utc)).total_seconds() / 60
                if mins_since_start > 30:
                    continue
            except:
                pass

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

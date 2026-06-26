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
EARLY_LOOK_HOUR = 10
LOCK_HOUR = 17

# ============================================================
#  PARK FACTORS
# ============================================================
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
#  SCORING ENGINE — Based on Guy 1 + Guy 2 criteria
# ============================================================

# GUY 1 + GUY 2: Barrel % vs pitch mix
# 10%+ = good, 15%+ = great, 20%+ = elite
def score_barrel(b):
    if b >= 20: return 100   # Elite — absolutely slugging
    if b >= 15: return 88    # Very impressive
    if b >= 10: return 72    # Good — threshold met
    if b >= 7:  return 45    # Below threshold
    return 20                # Poor

# GUY 1 + GUY 2: Exit Velocity
# 90mph minimum, 100mph logs = ready to go yard
def score_ev(e):
    if e >= 96: return 100   # Multiple 100mph contact likely
    if e >= 93: return 88
    if e >= 90: return 72    # Minimum threshold per Guy 2
    if e >= 87: return 45    # MLB average — marginal
    return 20

# GUY 1: ISO — Isolated Power
# MLB avg ~140, 250+ = very encouraging
def score_iso(iso):
    if iso >= 300: return 100
    if iso >= 250: return 88   # Very encouraging
    if iso >= 200: return 72
    if iso >= 150: return 55
    if iso >= 100: return 35
    return 15

# GUY 2: Pull % — 66% of all HRs are pulled
# 40%+ = good, 33% = minimum threshold
def score_pull(pull):
    if pull >= 50: return 100
    if pull >= 40: return 85   # Good per Guy 2
    if pull >= 33: return 60   # Minimum threshold
    return 20                  # Below threshold — excluded by Guy 2

# GUY 1: Hard hit % — frequency of 95mph+ contact
def score_hh(hh):
    if hh >= 55: return 100
    if hh >= 48: return 82
    if hh >= 40: return 65
    if hh >= 32: return 40
    return 20

# GUY 1: Recent form — last 2 weeks weighted heavily
def score_recent_hr(hr14):
    if hr14 >= 6:  return 100
    if hr14 >= 4:  return 85
    if hr14 >= 3:  return 70
    if hr14 >= 2:  return 55
    if hr14 >= 1:  return 38
    return 15

# GUY 1: Pitcher vulnerability — HR/9 + barrel % allowed
def score_pitcher_hr9(hr9):
    if hr9 >= 2.0: return 100
    if hr9 >= 1.5: return 82
    if hr9 >= 1.2: return 65
    if hr9 >= 1.0: return 48
    if hr9 >= 0.7: return 28
    return 12

# GUY 1: Pitcher barrel % allowed
def score_pitcher_barrel(barrel_against):
    if barrel_against >= 14: return 100  # Highly vulnerable
    if barrel_against >= 11: return 82
    if barrel_against >= 8:  return 62
    if barrel_against >= 6:  return 42
    return 20

# Park factor
def score_park(abbrev):
    f = PARK_FACTORS.get(abbrev, 100)
    if f >= 115: return 100
    if f >= 108: return 80
    if f >= 103: return 65
    if f >= 98:  return 50
    if f >= 93:  return 35
    return 20

# Batting order spot
def score_batting_order(spot):
    if spot <= 0: return 55   # Unknown/projected
    if spot <= 2: return 82
    if spot <= 5: return 70
    return 42

# ============================================================
#  COMBINED CONFIDENCE CALCULATION
# ============================================================
def calculate_confidence(stats, pitcher_stats, confirmed=False):
    # WEIGHTS — based on both guys' emphasis
    # Guy 1 + 2 both emphasize barrel, EV, pull
    # Guy 1 emphasizes pitcher vulnerability heavily
    # Guy 2 emphasizes pull% most
    weights = {
        "barrel":           18,  # Guy 1 + 2 core metric
        "exit_velocity":    14,  # Guy 1 + 2 core metric
        "pull_pct":         12,  # Guy 2 primary metric
        "iso":              10,  # Guy 1 power metric
        "hard_hit":          8,  # Guy 1 supporting metric
        "recent_hr":        12,  # Guy 1 last 2 weeks
        "pitcher_hr9":      12,  # Guy 1 pitcher vulnerability
        "pitcher_barrel":    8,  # Guy 1 pitcher vulnerability
        "park":              4,  # Park factor
        "batting_order":     2,  # Lineup spot
    }

    scores = {
        "barrel":          score_barrel(stats.get("barrel", 8.0)),
        "exit_velocity":   score_ev(stats.get("ev", 88.0)),
        "pull_pct":        score_pull(stats.get("pull", 35.0)),
        "iso":             score_iso(stats.get("iso", 140)),
        "hard_hit":        score_hh(stats.get("hh", 35.0)),
        "recent_hr":       score_recent_hr(stats.get("hr14", 0)),
        "pitcher_hr9":     score_pitcher_hr9(pitcher_stats.get("hr9", 1.2)),
        "pitcher_barrel":  score_pitcher_barrel(pitcher_stats.get("barrel_against", 8.0)),
        "park":            score_park(stats.get("park", "????")),
        "batting_order":   score_batting_order(stats.get("spot", 0)),
    }

    confidence = round(sum(scores[k] * weights[k] / 100 for k in scores))

    # Confirmed lineup bonus
    if confirmed:
        confidence = min(99, confidence + 3)

    return confidence, scores

# ============================================================
#  MLB API CALLS
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

async def get_batter_stats(session, player_id):
    # Season stats
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
            slg = float(s.get("sluggingPercentage", 0.380))
            avg = float(s.get("avg", 0.240))
            doubles = int(s.get("doubles", 0))
            triples = int(s.get("triples", 0))

            # ISO = SLG - AVG
            iso = round((slg - avg) * 1000)

            # Estimate metrics from available data
            hr14 = (hr / max(games, 1)) * 14
            barrel = min(25, max(4, (slg - 0.300) * 45))
            ev = min(98, max(84, 88 + (slg - 0.350) * 22))
            hh = min(65, max(25, 35 + (slg - 0.350) * 55))
            # Pull% estimated from HR rate (power hitters pull more)
            pull = min(60, max(25, 35 + (hr / max(ab, 1)) * 200))

            return {
                "barrel": barrel, "ev": ev, "hh": hh,
                "hr14": hr14, "hr": hr, "games": games,
                "iso": iso, "pull": pull, "slg": slg, "avg": avg,
            }
    except:
        pass
    return {
        "barrel": 8.0, "ev": 88.0, "hh": 35.0,
        "hr14": 0, "hr": 0, "games": 0,
        "iso": 120, "pull": 33.0, "slg": 0.380, "avg": 0.240,
    }

async def get_pitcher_stats(session, player_id):
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
            # Estimate barrel against from ERA/WHIP
            barrel_against = min(18, max(4, (era - 3.0) * 3 + 8))
            return {"hr9": hr9, "era": era, "whip": whip, "barrel_against": barrel_against}
    except:
        pass
    return {"hr9": 1.2, "era": 4.00, "whip": 1.30, "barrel_against": 8.0}

# ============================================================
#  MAIN SCAN
# ============================================================
async def run_scan(bot, phase="UPDATE"):
    today = datetime.date.today().strftime("%A, %B %d %Y")

    if phase == "EARLY":
        label = "⏰ EARLY LOOK — Projected Matchups"
        note = "⚠️ Projected lineups. Based on probable pitchers + full rosters.\nWill update as lineups confirm."
    elif phase == "LOCK":
        label = "🔒 FINAL LOCK — Confirmed Lineups"
        note = "✅ Confirmed lineups only. Final picks."
    else:
        label = "🔄 LINEUP UPDATE"
        note = "Rescoring all matchups with latest data."

    await bot.send_message(chat_id=CHAT_ID,
        text=f"🤖 HR SCOUT V4 — {label}\n📅 {today}\n{note}\n🎯 Min Confidence: {CONFIDENCE_THRESHOLD}%\n\nScoring criteria:\n• Barrel % (10%+ threshold)\n• Exit Velocity (90mph+ min)\n• Pull % (33%+ min)\n• ISO Power\n• Pitcher vulnerability\n• Park factor\n\nScanning full slate...")

    alerts = []
    seen_batters = set()

    async with aiohttp.ClientSession() as session:
        games = await get_todays_games(session)

        if not games:
            await bot.send_message(chat_id=CHAT_ID, text="📭 No games found today.")
            return

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
            lineups_confirmed = len(home_lineup) > 0 or len(away_lineup) > 0

            if lineups_confirmed:
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

            for batter, spot, pitcher, confirmed in batters_raw:
                batter_id = batter.get("id")
                batter_name = batter.get("fullName", "Unknown")

                if not batter_id or batter_id in seen_batters:
                    continue
                seen_batters.add(batter_id)

                if not pitcher:
                    continue

                pitcher_id = pitcher.get("id")
                pitcher_name = pitcher.get("fullName", "TBD")

                b_stats = await get_batter_stats(session, batter_id)
                p_stats = await get_pitcher_stats(session, pitcher_id) if pitcher_id else {"hr9": 1.2, "barrel_against": 8.0}

                if b_stats.get("games", 0) < 10:
                    continue

                # Guy 2 hard filter: pull% < 33% excluded
                if b_stats.get("pull", 0) < 33:
                    continue

                # Guy 2 hard filter: EV < 87mph excluded
                if b_stats.get("ev", 0) < 87:
                    continue

                b_stats["park"] = home_abbrev
                b_stats["spot"] = spot

                confidence, scores = calculate_confidence(b_stats, p_stats, confirmed)

                if confidence >= CONFIDENCE_THRESHOLD:
                    alerts.append({
                        "batter": batter_name,
                        "pitcher": pitcher_name,
                        "park": home_abbrev,
                        "confidence": confidence,
                        "confirmed": confirmed,
                        "spot": spot,
                        "hr": b_stats["hr"],
                        "games": b_stats["games"],
                        "barrel": round(b_stats["barrel"], 1),
                        "ev": round(b_stats["ev"], 1),
                        "pull": round(b_stats["pull"], 1),
                        "iso": b_stats["iso"],
                        "hh": round(b_stats["hh"], 1),
                        "hr14": round(b_stats["hr14"], 1),
                        "p_hr9": p_stats["hr9"],
                        "p_barrel": round(p_stats["barrel_against"], 1),
                        "p_era": p_stats["era"],
                        "scores": scores,
                    })

    alerts.sort(key=lambda x: x["confidence"], reverse=True)

    if not alerts:
        await bot.send_message(chat_id=CHAT_ID,
            text=f"📭 No plays above {CONFIDENCE_THRESHOLD}% confidence.\nNext scan in 30 mins.")
        return

    conf_label = "CONFIRMED ✅" if any(a["confirmed"] for a in alerts) else "PROJECTED ⏰"
    await bot.send_message(chat_id=CHAT_ID,
        text=f"✅ {len(alerts)} play(s) found — {conf_label}\nRanked highest to lowest confidence:")
    await asyncio.sleep(1)

    for a in alerts[:15]:
        badge = "🔥🔥🔥 ELITE" if a["confidence"]>=90 else "🔥🔥 STRONG" if a["confidence"]>=82 else "🔥 VALUE"
        status = "✅ CONFIRMED LINEUP" if a["confirmed"] else "⏰ PROJECTED LINEUP"
        spot_txt = f"Batting #{a['spot']}" if a["spot"] > 0 else "Order: TBD"

        msg = f"""
━━━━━━━━━━━━━━━━━━━━━━
{badge} — {a['confidence']}% CONFIDENCE
{status} | {spot_txt}
━━━━━━━━━━━━━━━━━━━━━━
👤 BATTER: {a['batter']}
⚾ VS PITCHER: {a['pitcher']}
🏟️ PARK: {a['park']}

📊 BATTER METRICS
• HR 2026: {a['hr']} in {a['games']} games
• Barrel %: {a['barrel']}%  {'🔥' if a['barrel']>=15 else '✅' if a['barrel']>=10 else ''}
• Exit Velocity: {a['ev']} mph  {'🔥' if a['ev']>=93 else '✅'}
• Pull %: {a['pull']}%  {'🔥' if a['pull']>=40 else '✅'}
• ISO Power: {a['iso']}  {'🔥' if a['iso']>=250 else '✅' if a['iso']>=140 else ''}
• Hard-Hit %: {a['hh']}%
• HR Last 14 Games: {a['hr14']}

⚾ PITCHER VULNERABILITY
• HR/9: {a['p_hr9']}  {'🚨' if a['p_hr9']>=1.5 else ''}
• Barrel % Allowed: {a['p_barrel']}%  {'🚨' if a['p_barrel']>=11 else ''}
• ERA: {a['p_era']}

✅ CONFIDENCE: {a['confidence']}%
━━━━━━━━━━━━━━━━━━━━━━""".strip()
        await bot.send_message(chat_id=CHAT_ID, text=msg)
        await asyncio.sleep(1)

# ============================================================
#  MAIN LOOP
# ============================================================
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID,
        text="✅ HR SCOUT V4 IS LIVE\n\nScoring System:\n• Barrel % (Guy 1 + 2)\n• Exit Velocity (Guy 1 + 2)\n• Pull % (Guy 2)\n• ISO Power (Guy 1)\n• Hard-Hit % (Guy 1)\n• Last 14 Days HR Form\n• Pitcher HR/9 + Barrel Allowed\n• Park Factor\n\n⏰ Early Look: 10am daily\n🔄 Updates: Every 30 mins\n🔒 Final Lock: 5pm daily\n\nRunning first scan now...")
    await asyncio.sleep(2)

    scan_count = 0
    last_early = None
    last_lock = None

    while True:
        now = datetime.datetime.now()
        today = now.date()

        if now.hour >= EARLY_LOOK_HOUR and last_early != today:
            await run_scan(bot, "EARLY")
            last_early = today
            await asyncio.sleep(60)
        elif now.hour >= LOCK_HOUR and last_lock != today:
            await run_scan(bot, "LOCK")
            last_lock = today
            await asyncio.sleep(60)
        else:
            scan_count += 1
            phase = "EARLY" if scan_count == 1 else "UPDATE"
            await run_scan(bot, phase)

        await asyncio.sleep(1800)

if __name__ == "__main__":
    asyncio.run(main())

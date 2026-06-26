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
CHECK_INTERVAL = 1800  # 30 minutes

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
#  FETCH TODAY'S GAMES FROM MLB API
# ============================================================
async def get_todays_games(session):
    today = datetime.date.today().strftime("%Y-%m-%d")
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today}&hydrate=lineups,probablePitcher,team"
    async with session.get(url) as resp:
        data = await resp.json()
    games = []
    for date in data.get("dates", []):
        for game in date.get("games", []):
            games.append(game)
    return games

# ============================================================
#  FETCH PLAYER STATS FROM BASEBALL SAVANT
# ============================================================
async def get_batter_stats(session, player_id):
    url = f"https://baseballsavant.mlb.com/expected_statistics?type=batter&year=2026&position=&team=&min=25&csv=true"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            text = await resp.text()
        for line in text.split("\n"):
            if str(player_id) in line:
                parts = line.split(",")
                if len(parts) > 10:
                    return {
                        "barrel": float(parts[7]) if parts[7] else 8.0,
                        "ev": float(parts[4]) if parts[4] else 88.0,
                        "hh": float(parts[6]) if parts[6] else 35.0,
                    }
    except:
        pass
    return {"barrel": 8.0, "ev": 88.0, "hh": 35.0}

# ============================================================
#  FETCH PITCHER STATS
# ============================================================
async def get_pitcher_stats(session, player_id):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=pitching&season=2026"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        if splits:
            s = splits[0].get("stat", {})
            hr = float(s.get("homeRunsPer9", 1.2))
            return {"hr9": hr}
    except:
        pass
    return {"hr9": 1.2}

# ============================================================
#  FETCH RECENT HR RATE FOR BATTER
# ============================================================
async def get_recent_hr(session, player_id):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=hitting&season=2026"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        if splits:
            s = splits[0].get("stat", {})
            hr = int(s.get("homeRuns", 0))
            games = int(s.get("gamesPlayed", 1))
            return (hr / games) * 14 if games > 0 else 0
    except:
        pass
    return 0

# ============================================================
#  SCORING ENGINE
# ============================================================
def score_barrel(b):
    return 100 if b>=18 else 85 if b>=15 else 70 if b>=12 else 50 if b>=9 else 30

def score_ev(e):
    return 100 if e>=95 else 85 if e>=93 else 70 if e>=91 else 50 if e>=89 else 30

def score_hh(h):
    return 100 if h>=55 else 80 if h>=48 else 60 if h>=40 else 40

def score_hr14(h):
    return 100 if h>=6 else 85 if h>=4 else 70 if h>=3 else 55 if h>=2 else 35

def score_hr9(h):
    return 100 if h>=2.0 else 80 if h>=1.5 else 65 if h>=1.2 else 50 if h>=1.0 else 30

def score_park(team_abbrev):
    f = PARK_FACTORS.get(team_abbrev, 100)
    return 100 if f>=115 else 80 if f>=108 else 65 if f>=103 else 50 if f>=98 else 35

def calculate_confidence(batter_stats, pitcher_stats, hr14, home_abbrev):
    weights = {
        "barrel_rate": 20, "exit_velocity": 15, "hard_hit_rate": 10,
        "recent_hr_freq": 20, "pitcher_hr9": 15,
        "park_factor": 10, "bonus": 10,
    }
    scores = {
        "barrel_rate": score_barrel(batter_stats["barrel"]),
        "exit_velocity": score_ev(batter_stats["ev"]),
        "hard_hit_rate": score_hh(batter_stats["hh"]),
        "recent_hr_freq": score_hr14(hr14),
        "pitcher_hr9": score_hr9(pitcher_stats["hr9"]),
        "park_factor": score_park(home_abbrev),
        "bonus": 50,
    }
    return round(sum(scores[k] * weights[k] / 100 for k in scores))

# ============================================================
#  MAIN SCAN
# ============================================================
async def run_scan(bot, label="SCAN"):
    today = datetime.date.today().strftime("%A, %B %d %Y")
    await bot.send_message(chat_id=CHAT_ID,
        text=f"🤖 HR SCOUT — {label}\n📅 {today}\n🎯 Min: {CONFIDENCE_THRESHOLD}%\nPulling live MLB data...")

    alerts = []
    seen = set()

    async with aiohttp.ClientSession() as session:
        games = await get_todays_games(session)

        if not games:
            await bot.send_message(chat_id=CHAT_ID, text="📭 No games found today.")
            return

        for game in games:
            home_team = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "")
            home_abbrev = TEAM_ABBREV.get(home_team, "???")

            lineups = game.get("lineups", {})
            home_lineup = lineups.get("homePlayers", [])
            away_lineup = lineups.get("awayPlayers", [])
            all_batters = home_lineup + away_lineup

            home_pitcher = game.get("teams", {}).get("home", {}).get("probablePitcher", {})
            away_pitcher = game.get("teams", {}).get("away", {}).get("probablePitcher", {})

            for batter in all_batters:
                batter_id = batter.get("id")
                batter_name = batter.get("fullName", "Unknown")

                if batter_id in seen:
                    continue
                seen.add(batter_id)

                batter_team = batter.get("currentTeam", {}).get("name", "")
                batter_abbrev = TEAM_ABBREV.get(batter_team, "")

                if batter_abbrev == home_abbrev:
                    pitcher = away_pitcher
                else:
                    pitcher = home_pitcher

                if not pitcher:
                    continue

                pitcher_id = pitcher.get("id")
                pitcher_name = pitcher.get("fullName", "Unknown")

                batter_stats = await get_batter_stats(session, batter_id)
                pitcher_stats = await get_pitcher_stats(session, pitcher_id)
                hr14 = await get_recent_hr(session, batter_id)

                confidence = calculate_confidence(batter_stats, pitcher_stats, hr14, home_abbrev)

                if confidence >= CONFIDENCE_THRESHOLD:
                    alerts.append({
                        "batter": batter_name,
                        "pitcher": pitcher_name,
                        "park": home_abbrev,
                        "confidence": confidence,
                        "barrel": batter_stats["barrel"],
                        "ev": batter_stats["ev"],
                        "hh": batter_stats["hh"],
                        "hr14": round(hr14, 1),
                        "hr9": pitcher_stats["hr9"],
                    })

    alerts.sort(key=lambda x: x["confidence"], reverse=True)

    if not alerts:
        await bot.send_message(chat_id=CHAT_ID,
            text=f"📭 No plays above {CONFIDENCE_THRESHOLD}% confidence today.")
        return

    await bot.send_message(chat_id=CHAT_ID,
        text=f"✅ {len(alerts)} play(s) found above {CONFIDENCE_THRESHOLD}%")

    for a in alerts:
        badge = "🔥🔥🔥 ELITE" if a["confidence"]>=90 else "🔥🔥 STRONG" if a["confidence"]>=82 else "🔥 VALUE"
        msg = f"""
━━━━━━━━━━━━━━━━━━━━━━
{badge} — {a['confidence']}% CONFIDENCE
━━━━━━━━━━━━━━━━━━━━━━
👤 BATTER: {a['batter']}
⚾ VS: {a['pitcher']}
🏟️ PARK: {a['park']}

📊 BATTER
• Barrel: {a['barrel']}% | EV: {a['ev']} mph
• Hard-Hit: {a['hh']}% | HR Last 14G: {a['hr14']}

📊 PITCHER
• HR/9: {a['hr9']}

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
        text="✅ HR SCOUT V2 IS LIVE\n🔄 Scanning full MLB slate every 30 mins\nPulling live data for ALL players now...")
    await asyncio.sleep(2)
    scan_count = 0
    while True:
        scan_count += 1
        label = "FIRST LOOK" if scan_count == 1 else f"UPDATE #{scan_count}"
        try:
            await run_scan(bot, label)
        except Exception as e:
            await bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Scan error: {str(e)}")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())

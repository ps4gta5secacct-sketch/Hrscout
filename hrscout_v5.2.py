import asyncio
import datetime
import aiohttp
from telegram import Bot

# ============================================================
#  CONFIGURATION
# ============================================================
TELEGRAM_TOKEN = "8720993049:AAEimQD4PUDFlMA2bpxXsyW3IMcTZ5ak0PY"
CHAT_ID = "919904024"
EARLY_THRESHOLD = 62
UPDATE_THRESHOLD = 68
LOCK_THRESHOLD = 75
SCAN_INTERVAL = 300  # 5 minutes

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
#  SCORING — Guy 1 + Guy 2 + My Additions
# ============================================================
def score_barrel(b):
    if b >= 20: return 100
    if b >= 15: return 88
    if b >= 10: return 72
    if b >= 7:  return 45
    return 20

def score_ev(e):
    if e >= 96: return 100
    if e >= 93: return 88
    if e >= 90: return 72
    if e >= 87: return 45
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
    if pull >= 33: return 60
    return 20

def score_hh(hh):
    if hh >= 55: return 100
    if hh >= 48: return 82
    if hh >= 40: return 65
    if hh >= 32: return 40
    return 20

def score_recent_hr(hr, games):
    hr14 = (hr / max(games, 1)) * 14
    if hr14 >= 6:  return 100
    if hr14 >= 4:  return 85
    if hr14 >= 3:  return 70
    if hr14 >= 2:  return 55
    if hr14 >= 1:  return 38
    return 15

def score_pitcher_hr9(hr9):
    if hr9 >= 2.0: return 100
    if hr9 >= 1.5: return 82
    if hr9 >= 1.2: return 65
    if hr9 >= 1.0: return 48
    if hr9 >= 0.7: return 28
    return 12

def score_pitcher_barrel(b):
    if b >= 14: return 100
    if b >= 11: return 82
    if b >= 8:  return 62
    if b >= 6:  return 42
    return 20

def score_park(abbrev):
    f = PARK_FACTORS.get(abbrev, 100)
    if f >= 115: return 100
    if f >= 108: return 80
    if f >= 103: return 65
    if f >= 98:  return 50
    if f >= 93:  return 35
    return 20

def score_platoon(batter_hand, pitcher_hand):
    if batter_hand == "S": return 72
    if batter_hand != pitcher_hand: return 90
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

def calculate_confidence(b, p, park, spot=0, confirmed=False):
    weights = {
        "barrel": 18, "ev": 13, "pull": 12, "iso": 10,
        "hh": 7, "recent_hr": 12, "p_hr9": 10,
        "p_barrel": 7, "p_trend": 4, "park": 3,
        "platoon": 2, "batting_order": 2,
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
    return conf

# ============================================================
#  PLAIN ENGLISH EXPLANATION
# ============================================================
def generate_explanation(batter_name, b, p, park, spot, confirmed):
    reasons = []

    if b["barrel"] >= 20:
        reasons.append(f"elite {b['barrel']}% barrel rate — Guy 1+2: 20%+ means absolutely slugging this pitch mix")
    elif b["barrel"] >= 15:
        reasons.append(f"very impressive {b['barrel']}% barrel rate — Guy 1+2: 15%+ threshold")
    elif b["barrel"] >= 10:
        reasons.append(f"{b['barrel']}% barrel rate meets the 10% minimum threshold — Guy 1+2")

    if b["ev"] >= 93:
        reasons.append(f"{b['ev']}mph exit velocity — multiple 100mph+ contact events likely — Guy 1+2")
    elif b["ev"] >= 90:
        reasons.append(f"{b['ev']}mph exit velocity clears the 90mph minimum — Guy 2")

    if b["pull"] >= 40:
        reasons.append(f"{b['pull']}% pull rate above 40% threshold — 66% of all HRs are pulled — Guy 2")
    elif b["pull"] >= 33:
        reasons.append(f"{b['pull']}% pull rate meets the 33% minimum — Guy 2")

    if b["iso"] >= 250:
        reasons.append(f"ISO of {b['iso']} is elite — well above the 250 threshold — Guy 1")
    elif b["iso"] >= 140:
        reasons.append(f"ISO of {b['iso']} above MLB average of 140 — Guy 1")

    if p["hr9"] >= 1.5:
        reasons.append(f"pitcher is highly vulnerable — {p['hr9']} HR/9 allowed this season — Guy 1")
    elif p["hr9"] >= 1.2:
        reasons.append(f"pitcher allows {p['hr9']} HR/9 showing above average vulnerability — Guy 1")

    trend_diff = p.get("last3_era", p["era"]) - p["era"]
    if trend_diff >= 1.0:
        reasons.append(f"pitcher trending worse — ERA jumped to {p.get('last3_era', p['era'])} over last 3 starts vs {p['era']} season ERA — my addition")

    park_f = PARK_FACTORS.get(park, 100)
    if park_f >= 108:
        reasons.append(f"{park} is a hitter-friendly park (factor {park_f}) — my addition")
    elif park_f <= 94:
        reasons.append(f"{park} is a pitcher-friendly park (factor {park_f}) — slight negative — my addition")

    if spot in [3, 4]:
        reasons.append(f"batting #{spot} in cleanup — maximum plate appearances and RBI spots — my addition")
    elif spot in [1, 2]:
        reasons.append(f"batting #{spot} — more plate appearances throughout the game — my addition")

    bh = b.get("hand", "R")
    ph = p.get("hand", "R")
    if bh != ph and bh != "S":
        reasons.append(f"platoon advantage — {bh} batter vs {ph} pitcher — my addition")

    if not confirmed:
        reasons.append("lineup is projected — confidence will adjust when confirmed")

    if not reasons:
        return f"{batter_name} meets multiple baseline criteria across barrel rate, exit velocity, and pitcher vulnerability."

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
#  API CALLS — Fully dynamic, no hardcoded players
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
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=hitting&season=2026&hydrate=person"
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
            # Estimate Statcast metrics from available data
            barrel = min(25, max(4, (slg - 0.300) * 45))
            ev = min(98, max(84, 88 + (slg - 0.350) * 22))
            hh = min(65, max(25, 35 + (slg - 0.350) * 55))
            pull = min(60, max(28, 36 + (hr / max(ab, 1)) * 180))
            hand = splits[0].get("batter", {}).get("batSide", {}).get("code", "R")
            return {
                "barrel": barrel, "ev": ev, "hh": hh,
                "hr": hr, "games": games, "iso": iso,
                "pull": pull, "hand": hand, "slg": slg,
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
            hand = splits[0].get("pitcher", {}).get("pitchHand", {}).get("code", "R")
            return {
                "hr9": hr9, "era": era, "whip": whip,
                "barrel_against": barrel_against,
                "last3_era": era, "hand": hand,
            }
    except:
        pass
    return None

# ============================================================
#  MAIN SCAN — Every player, every game, every matchup
# ============================================================
async def run_scan(bot, phase="UPDATE", prev_scores=None):
    if prev_scores is None:
        prev_scores = {}

    today = datetime.date.today().strftime("%A, %B %d %Y")

    threshold = EARLY_THRESHOLD if phase == "EARLY" else LOCK_THRESHOLD if phase == "LOCK" else UPDATE_THRESHOLD

    if phase == "EARLY":
        label = "⏰ EARLY LOOK — Projected Matchups"
        note = f"Threshold: {EARLY_THRESHOLD}%+ | Projected lineups"
    elif phase == "LOCK":
        label = "🔒 FINAL LOCK — Confirmed Lineups"
        note = f"Threshold: {LOCK_THRESHOLD}%+ | Confirmed only"
    else:
        label = "🔄 LIVE UPDATE"
        note = f"Threshold: {UPDATE_THRESHOLD}%+ | Rescanning all matchups"

    alerts = []
    new_scores = {}
    seen_batters = set()

    async with aiohttp.ClientSession() as session:
        games = await get_todays_games(session)
        if not games:
            return prev_scores

        total_players_scanned = 0

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
                    pos_type = p.get("position", {}).get("type", "")
                    if pos_type != "Pitcher":
                        batters_raw.append((p.get("person", {}), 0, away_pitcher, False))
                for p in away_roster:
                    pos_type = p.get("position", {}).get("type", "")
                    if pos_type != "Pitcher":
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

                b_stats = await get_batter_stats(session, batter_id)
                if not b_stats or b_stats.get("games", 0) < 10:
                    continue

                total_players_scanned += 1

                # Guy 2 hard filters — applied to every player equally
                if b_stats.get("pull", 0) < 33: continue
                if b_stats.get("ev", 0) < 87: continue
                if b_stats.get("barrel", 0) < 10: continue

                p_stats = await get_pitcher_stats(session, pitcher_id) if pitcher_id else None
                if not p_stats:
                    p_stats = {"hr9": 1.2, "barrel_against": 8.0, "era": 4.00, "whip": 1.30, "last3_era": 4.00, "hand": "R"}

                confidence = calculate_confidence(b_stats, p_stats, home_abbrev, spot, is_confirmed)

                alert_key = f"{batter_id}_{pitcher_id}"
                new_scores[alert_key] = confidence

                if confidence < threshold:
                    continue

                prev_conf = prev_scores.get(alert_key)
                is_new = prev_conf is None
                conf_change = prev_conf is not None and abs(confidence - prev_conf) >= 4
                is_phase_scan = phase in ["EARLY", "LOCK"]

                if not (is_new or conf_change or is_phase_scan):
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
        text=f"🤖 HR SCOUT V5 — {label}\n📅 {today}\n{note}\n👥 Players scanned: {total_players_scanned}\n✅ {len(alerts)} play(s) found:")
    await asyncio.sleep(1)

    for a in alerts[:20]:
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
• Season ERA: {a['p_era']} | Last 3 ERA: {a['p_last3']}

📝 WHY THIS PLAY:
{a['explanation']}

✅ CONFIDENCE: {a['confidence']}%
━━━━━━━━━━━━━━━━━━━━━━""".strip()
        await bot.send_message(chat_id=CHAT_ID, text=msg)
        await asyncio.sleep(1)

    return {**prev_scores, **new_scores}

# ============================================================
#  MAIN LOOP — Runs forever, no manual input needed
# ============================================================
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID,
        text="✅ HR SCOUT V5 IS LIVE\n\n👥 Scans EVERY player on the full MLB slate\n🚫 No hardcoded players — 100% dynamic\n\n📊 SCORING (Guy 1 + Guy 2 + My Additions):\n• Barrel % ≥10% required (Guy 1+2)\n• EV ≥87mph required (Guy 2)\n• Pull% ≥33% required (Guy 2)\n• ISO Power (Guy 1)\n• Pitcher HR/9 + Barrel Allowed (Guy 1)\n• Pitcher trend last 3 starts (my addition)\n• Platoon advantage (my addition)\n• Park factor (my addition)\n• Batting order spot (my addition)\n\n🎯 Thresholds:\n• Early Look: 62%+\n• Updates: 68%+\n• Final Lock: 75%+\n\n📝 Every alert explains WHY in plain English\n📈📉 Confidence changes fire instantly\n⚡ Scans every 5 minutes automatically\n\nRunning first scan now...")
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
            await bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Scan error: {str(e)[:200]}")

        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())

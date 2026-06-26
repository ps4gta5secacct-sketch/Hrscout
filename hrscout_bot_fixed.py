import asyncio
import aiohttp
import json
import datetime
import os
from telegram import Bot

# ============================================================
#  CONFIGURATION
# ============================================================
TELEGRAM_TOKEN = "8720993049:AAEimQD4PUDFlMA2bpxXsyW3IMcTZ5ak0PY"
CHAT_ID = "919904024"
CONFIDENCE_THRESHOLD = 75  # Only alert on plays 75%+

# ============================================================
#  WEIGHTS FOR CONFIDENCE SCORING (must add to 100)
# ============================================================
WEIGHTS = {
    "barrel_rate":        20,  # How often batter barrels the ball
    "exit_velocity":      15,  # Average exit velocity
    "hard_hit_rate":      10,  # Hard hit %
    "recent_hr_freq":     20,  # HR frequency last 14 games
    "pitcher_hr9":        15,  # Pitcher HR/9 allowed
    "pitcher_barrel_against": 10,  # Barrel rate pitcher allows
    "park_factor":         5,  # Ballpark HR factor
    "platoon_advantage":   5,  # Batter vs pitcher handedness
}

# ============================================================
#  PARK HR FACTORS (league average = 100, higher = more HRs)
# ============================================================
PARK_FACTORS = {
    "COL": 120,  # Coors Field
    "CIN": 112,  # Great American Ball Park
    "PHI": 110,  # Citizens Bank Park
    "NYY": 108,  # Yankee Stadium
    "BOS": 106,  # Fenway Park
    "MIL": 104,  # American Family Field
    "HOU": 103,  # Minute Maid Park
    "ATL": 102,  # Truist Park
    "CHC": 102,  # Wrigley Field
    "LAD": 100,  # Dodger Stadium
    "NYM": 100,  # Citi Field
    "STL": 98,   # Busch Stadium
    "MIN": 98,   # Target Field
    "DET": 97,   # Comerica Park
    "PIT": 97,   # PNC Park
    "TOR": 97,   # Rogers Centre
    "BAL": 97,   # Camden Yards
    "CLE": 96,   # Progressive Field
    "CWS": 96,   # Guaranteed Rate Field
    "SEA": 95,   # T-Mobile Park
    "MIA": 95,   # loanDepot Park
    "WSH": 95,   # Nationals Park
    "AZ":  95,   # Chase Field
    "KC":  94,   # Kauffman Stadium
    "LAA": 94,   # Angel Stadium
    "TB":  94,   # Tropicana Field
    "SD":  93,   # Petco Park
    "SF":  92,   # Oracle Park
    "OAK": 92,   # Oakland Coliseum
    "TEX": 91,   # Globe Life Field
}

# ============================================================
#  KNOWN 2026 PLAYER DATA (Statcast-based, updated regularly)
#  Format: barrel_rate, exit_velo, hard_hit_rate, hr_per_14g
# ============================================================
BATTER_DATA = {
    "Jac Caglianone":    {"barrel": 15.9, "ev": 94.4, "hh": 58.9, "hr14": 6.0, "hand": "L", "team": "KC"},
    "Junior Caminero":   {"barrel": 12.7, "ev": 91.5, "hh": 51.0, "hr14": 4.0, "hand": "R", "team": "TB"},
    "Riley Greene":      {"barrel": 12.9, "ev": 90.8, "hh": 48.0, "hr14": 2.0, "hand": "L", "team": "DET"},
    "Jordan Walker":     {"barrel": 13.6, "ev": 93.9, "hh": 51.1, "hr14": 3.5, "hand": "R", "team": "STL"},
    "Yordan Alvarez":    {"barrel": 18.2, "ev": 95.1, "hh": 61.0, "hr14": 3.5, "hand": "L", "team": "HOU"},
    "Kyle Schwarber":    {"barrel": 23.5, "ev": 92.0, "hh": 58.7, "hr14": 4.0, "hand": "L", "team": "PHI"},
    "Oneil Cruz":        {"barrel": 17.9, "ev": 95.8, "hh": 60.0, "hr14": 3.0, "hand": "L", "team": "PIT"},
    "James Wood":        {"barrel": 14.0, "ev": 96.3, "hh": 57.0, "hr14": 3.0, "hand": "L", "team": "WSH"},
    "Aaron Judge":       {"barrel": 22.0, "ev": 95.5, "hh": 62.0, "hr14": 0.0, "hand": "R", "team": "NYY"},  # IL
    "Paul Goldschmidt":  {"barrel": 13.0, "ev": 91.0, "hh": 47.0, "hr14": 2.5, "hand": "R", "team": "NYY"},
    "Gunnar Henderson":  {"barrel": 14.5, "ev": 92.0, "hh": 52.0, "hr14": 3.0, "hand": "L", "team": "BAL"},
    "Bobby Witt Jr.":    {"barrel": 11.0, "ev": 90.5, "hh": 46.0, "hr14": 2.5, "hand": "R", "team": "KC"},
    "Elly De La Cruz":   {"barrel": 12.0, "ev": 91.0, "hh": 49.0, "hr14": 2.5, "hand": "S", "team": "CIN"},
    "Pete Crow-Armstrong":{"barrel": 10.5, "ev": 89.0, "hh": 44.0, "hr14": 3.5, "hand": "L", "team": "CHC"},
    "Manny Machado":     {"barrel": 11.5, "ev": 90.0, "hh": 46.0, "hr14": 2.0, "hand": "R", "team": "SD"},
    "Shohei Ohtani":     {"barrel": 19.0, "ev": 94.0, "hh": 59.0, "hr14": 3.5, "hand": "L", "team": "LAD"},
    "Freddie Freeman":   {"barrel": 13.0, "ev": 91.5, "hh": 50.0, "hr14": 2.5, "hand": "L", "team": "LAD"},
    "Juan Soto":         {"barrel": 15.0, "ev": 92.0, "hh": 53.0, "hr14": 3.0, "hand": "L", "team": "NYM"},
    "Vladimir Guerrero Jr.": {"barrel": 12.5, "ev": 91.0, "hh": 48.0, "hr14": 2.5, "hand": "R", "team": "TOR"},
    "Ben Rice":          {"barrel": 14.0, "ev": 92.5, "hh": 51.0, "hr14": 3.5, "hand": "L", "team": "NYY"},
    "Nick Kurtz":        {"barrel": 15.9, "ev": 94.4, "hh": 58.9, "hr14": 3.0, "hand": "L", "team": "ATH"},
    "Jazz Chisholm Jr.": {"barrel": 13.0, "ev": 91.0, "hh": 48.0, "hr14": 2.5, "hand": "L", "team": "NYY"},
}

# ============================================================
#  KNOWN 2026 PITCHER DATA
#  Format: hr9, barrel_against, hand
# ============================================================
PITCHER_DATA = {
    "David Sandlin":     {"hr9": 2.70, "barrel_against": 13.5, "hand": "R"},
    "Spencer Arrighetti":{"hr9": 1.40, "barrel_against": 6.6,  "hand": "R"},
    "Michael McGreevy":  {"hr9": 1.30, "barrel_against": 10.1, "hand": "R"},
    "Payton Tolle":      {"hr9": 1.10, "barrel_against": 8.0,  "hand": "R"},
    "Trevor Rogers":     {"hr9": 1.20, "barrel_against": 7.5,  "hand": "L"},
    "Patrick Corbin":    {"hr9": 1.50, "barrel_against": 9.0,  "hand": "L"},
    "Keider Montero":    {"hr9": 1.30, "barrel_against": 8.5,  "hand": "R"},
    "Colin Rea":         {"hr9": 1.20, "barrel_against": 7.0,  "hand": "R"},
    "Taj Bradley":       {"hr9": 0.90, "barrel_against": 6.0,  "hand": "R"},
    "Luis Castillo":     {"hr9": 0.80, "barrel_against": 5.5,  "hand": "R"},
    "Paul Skenes":       {"hr9": 0.60, "barrel_against": 4.0,  "hand": "R"},
    "Max Meyer":         {"hr9": 0.85, "barrel_against": 5.0,  "hand": "R"},
    "Tarik Skubal":      {"hr9": 0.75, "barrel_against": 5.0,  "hand": "L"},
    "Walbert Urena":     {"hr9": 1.10, "barrel_against": 7.5,  "hand": "R"},
    "J.T. Ginn":         {"hr9": 1.20, "barrel_against": 8.0,  "hand": "R"},
    "Tomoyuki Sugano":   {"hr9": 1.40, "barrel_against": 9.0,  "hand": "R"},
}

# ============================================================
#  INJURY LIST — players on IL, auto-excluded
# ============================================================
INJURED_LIST = [
    "Aaron Judge",
    "Giancarlo Stanton",
    "Max Fried",
    "Trent Grisham",
]

# ============================================================
#  TODAY'S MATCHUPS — format: (batter, pitcher, home_team)
#  Update this daily or connect to live API
# ============================================================
TODAYS_MATCHUPS = [
    ("Jac Caglianone",    "David Sandlin",      "CWS"),
    ("Riley Greene",      "Spencer Arrighetti", "DET"),
    ("Junior Caminero",   "Taj Bradley",        "TB"),
    ("Jordan Walker",     "Michael McGreevy",   "STL"),
    ("Pete Crow-Armstrong","Colin Rea",         "MIL"),
    ("Gunnar Henderson",  "Trevor Rogers",      "BAL"),
    ("Juan Soto",         "Payton Tolle",       "NYM"),
    ("Jazz Chisholm Jr.", "Payton Tolle",       "NYM"),
    ("Paul Goldschmidt",  "Payton Tolle",       "BOS"),
]


# ============================================================
#  CONFIDENCE SCORING ENGINE
# ============================================================
def score_barrel_rate(barrel):
    # Elite: 18%+ = 100, Good: 12-18% = 60-99, Below: <8% = 0-40
    if barrel >= 18:   return 100
    if barrel >= 15:   return 85
    if barrel >= 12:   return 70
    if barrel >= 9:    return 50
    if barrel >= 6:    return 30
    return 10

def score_exit_velocity(ev):
    if ev >= 95:   return 100
    if ev >= 93:   return 85
    if ev >= 91:   return 70
    if ev >= 89:   return 50
    if ev >= 87:   return 30
    return 10

def score_hard_hit(hh):
    if hh >= 55:   return 100
    if hh >= 48:   return 80
    if hh >= 40:   return 60
    if hh >= 32:   return 40
    return 20

def score_hr_frequency(hr14):
    # HRs in last 14 games
    if hr14 >= 6:   return 100
    if hr14 >= 4:   return 85
    if hr14 >= 3:   return 70
    if hr14 >= 2:   return 55
    if hr14 >= 1:   return 35
    return 10

def score_pitcher_hr9(hr9):
    if hr9 >= 2.0:  return 100
    if hr9 >= 1.5:  return 80
    if hr9 >= 1.2:  return 65
    if hr9 >= 1.0:  return 50
    if hr9 >= 0.7:  return 30
    return 15

def score_pitcher_barrel(barrel_against):
    if barrel_against >= 12:  return 100
    if barrel_against >= 9:   return 80
    if barrel_against >= 7:   return 60
    if barrel_against >= 5:   return 40
    return 20

def score_park(team, home_team):
    park = home_team if home_team else team
    factor = PARK_FACTORS.get(park, 100)
    if factor >= 115:  return 100
    if factor >= 108:  return 80
    if factor >= 103:  return 65
    if factor >= 98:   return 50
    if factor >= 93:   return 35
    return 20

def score_platoon(batter_hand, pitcher_hand):
    # Opposite hands = platoon advantage
    if batter_hand == "S":  return 70  # Switch hitter always has some advantage
    if batter_hand != pitcher_hand:  return 90
    return 40

def calculate_confidence(batter_name, pitcher_name, home_team):
    if batter_name in INJURED_LIST:
        return None, "ON IL"

    batter = BATTER_DATA.get(batter_name)
    pitcher = PITCHER_DATA.get(pitcher_name)

    if not batter or not pitcher:
        return None, "DATA MISSING"

    scores = {
        "barrel_rate":            score_barrel_rate(batter["barrel"]),
        "exit_velocity":          score_exit_velocity(batter["ev"]),
        "hard_hit_rate":          score_hard_hit(batter["hh"]),
        "recent_hr_freq":         score_hr_frequency(batter["hr14"]),
        "pitcher_hr9":            score_pitcher_hr9(pitcher["hr9"]),
        "pitcher_barrel_against": score_pitcher_barrel(pitcher["barrel_against"]),
        "park_factor":            score_park(batter["team"], home_team),
        "platoon_advantage":      score_platoon(batter["hand"], pitcher["hand"]),
    }

    weighted_total = sum(scores[k] * WEIGHTS[k] / 100 for k in scores)
    return round(weighted_total), scores


# ============================================================
#  BUILD TELEGRAM MESSAGE
# ============================================================
def build_alert(batter_name, pitcher_name, home_team, confidence, scores):
    batter = BATTER_DATA[batter_name]
    pitcher = PITCHER_DATA[pitcher_name]

    if confidence >= 90:
        badge = "🔥🔥🔥 ELITE"
    elif confidence >= 82:
        badge = "🔥🔥 STRONG"
    elif confidence >= 75:
        badge = "🔥 VALUE"
    else:
        return None

    msg = f"""
━━━━━━━━━━━━━━━━━━━━━━
{badge} — {confidence}% CONFIDENCE
━━━━━━━━━━━━━━━━━━━━━━
👤 BATTER: {batter_name}
⚾ VS PITCHER: {pitcher_name}
🏟️ PARK: {home_team}

📊 BATTER DATA
• Barrel Rate: {batter['barrel']}%
• Exit Velocity: {batter['ev']} mph
• Hard-Hit Rate: {batter['hh']}%
• HR Last 14 Games: {batter['hr14']}

📊 PITCHER DATA
• HR/9: {pitcher['hr9']}
• Barrel Rate Against: {pitcher['barrel_against']}%

📈 SIGNAL BREAKDOWN
• Barrel Rate Score:     {scores['barrel_rate']}/100
• Exit Velocity Score:   {scores['exit_velocity']}/100
• Hard-Hit Score:        {scores['hard_hit_rate']}/100
• Recent HR Frequency:   {scores['recent_hr_freq']}/100
• Pitcher HR/9 Score:    {scores['pitcher_hr9']}/100
• Pitcher Barrel Score:  {scores['pitcher_barrel_against']}/100
• Park Factor Score:     {scores['park_factor']}/100
• Platoon Advantage:     {scores['platoon_advantage']}/100

✅ CONFIDENCE: {confidence}%
━━━━━━━━━━━━━━━━━━━━━━
"""
    return msg.strip()


# ============================================================
#  SEND ALERTS
# ============================================================
async def send_alerts():
    bot = Bot(token=TELEGRAM_TOKEN)
    today = datetime.date.today().strftime("%A, %B %d %Y")

    header = f"""
🤖 HR SCOUT — DAILY SCAN
📅 {today}
🎯 Minimum Confidence: {CONFIDENCE_THRESHOLD}%
━━━━━━━━━━━━━━━━━━━━━━
Scanning {len(TODAYS_MATCHUPS)} matchups...
"""
    await bot.send_message(chat_id=CHAT_ID, text=header.strip())
    await asyncio.sleep(1)

    alerts_sent = 0

    for batter_name, pitcher_name, home_team in TODAYS_MATCHUPS:
        confidence, scores = calculate_confidence(batter_name, pitcher_name, home_team)

        if confidence is None:
            continue

        if confidence >= CONFIDENCE_THRESHOLD:
            msg = build_alert(batter_name, pitcher_name, home_team, confidence, scores)
            if msg:
                await bot.send_message(chat_id=CHAT_ID, text=msg)
                await asyncio.sleep(1)
                alerts_sent += 1

    if alerts_sent == 0:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=f"📭 No plays found above {CONFIDENCE_THRESHOLD}% confidence today."
        )
    else:
        summary = f"✅ Scan complete. {alerts_sent} play(s) found above {CONFIDENCE_THRESHOLD}% confidence."
        await bot.send_message(chat_id=CHAT_ID, text=summary)


if __name__ == "__main__":
    asyncio.run(send_alerts())

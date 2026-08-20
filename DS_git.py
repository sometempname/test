import requests
import re
import urllib3
import time
import os
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ----------------------------------------------------------------------
# Hardcoded configuration (non-secret values)
# ----------------------------------------------------------------------
BASE_URL = "https://ol.lstyxl.com"

# Source coordinates
SRC_GALAXY = 3
SRC_SYSTEM = 341
SRC_PLANET = 15

# Destination coordinates
DST_GALAXY = 3
DST_SYSTEM = 341
DST_PLANET = 16

# Ships to send: ship ID -> count
SHIPS = {
    210: 1
    # Add more as needed, e.g. 204: 2
}

# ----------------------------------------------------------------------
# Extract available exploration lanes from fleetTable page
# ----------------------------------------------------------------------
def get_available_lanes(soup):
    # Strategy 1: Find a string containing '探险队' and look in its parent
    for elem in soup.find_all(string=re.compile("探险队")):
        parent = elem.find_parent()
        if parent:
            text = parent.get_text(strip=True)
            match = re.search(r"(\d+)\s*/\s*(\d+)\s*探险队", text)
            if match:
                filled = int(match.group(1))
                total = int(match.group(2))
                return total - filled
    # Strategy 2: Search any span, div, td that contains '探险队'
    for tag in soup.find_all(['span', 'div', 'td']):
        text = tag.get_text(strip=True)
        if '探险队' in text:
            match = re.search(r"(\d+)\s*/\s*(\d+)", text)
            if match:
                filled = int(match.group(1))
                total = int(match.group(2))
                return total - filled
    # Fallback: try to find any fraction just before '探险队' anywhere in HTML
    html_text = soup.get_text()
    match = re.search(r"(\d+)\s*/\s*(\d+)\s*探险队", html_text)
    if match:
        filled = int(match.group(1))
        total = int(match.group(2))
        return total - filled
    return 0

# ----------------------------------------------------------------------
# Send one fleet using the current session
# ----------------------------------------------------------------------
def send_fleet(session):
    fleet_table = session.get(f"{BASE_URL}/game.php?page=fleetTable")
    soup = BeautifulSoup(fleet_table.text, 'html.parser')

    form = soup.find('form', action=re.compile(r'fleetStep1'))
    if not form:
        print("Could not find the fleet selection form on fleetTable.")
        return False

    payload = {}
    for inp in form.find_all('input', {'type': 'hidden'}):
        name = inp.get('name')
        if name:
            payload[name] = inp.get('value', '')

    ship_inputs = form.find_all('input', {'name': re.compile(r'^ship\d+$')})
    if not ship_inputs:
        print("No ship input fields found in the form.")
        return False

    for inp in ship_inputs:
        name = inp.get('name')
        m = re.search(r'(\d+)', name)
        if m:
            sid = int(m.group(1))
            payload[name] = SHIPS.get(sid, 0)

    save_groop_input = form.find('input', {'name': 'save_groop'})
    if save_groop_input is not None:
        payload['save_groop'] = ''

    payload.setdefault('galaxy', SRC_GALAXY)
    payload.setdefault('system', SRC_SYSTEM)
    payload.setdefault('planet', SRC_PLANET)
    payload.setdefault('type', 1)
    payload.setdefault('target_mission', 0)

    action = form.get('action')
    if action.startswith('?'):
        step1_url = f"{BASE_URL}/game.php{action}"
    elif action.startswith('/'):
        step1_url = f"{BASE_URL}{action}"
    elif action.startswith('http'):
        step1_url = action
    else:
        step1_url = f"{BASE_URL}/{action}"

    r1 = session.post(step1_url, data=payload)

    soup2 = BeautifulSoup(r1.text, 'html.parser')
    token = None
    for inp in soup2.find_all('input', {'type': 'hidden'}):
        if 'token' in inp.get('name', '').lower():
            token = inp.get('value')
            break

    if not token:
        print("Token not found after step1. Aborting fleet send.")
        return False

    payload2 = {
        'token': token,
        'fleet_group': '0',
        'target_mission': '0',
        'galaxy': DST_GALAXY,
        'system': DST_SYSTEM,
        'planet': DST_PLANET,
        'type': 1,
        'speed': 10,
        'shortcut[][name]': '',
        'shortcut[][galaxy]': '',
        'shortcut[][system]': '',
        'shortcut[][planet]': '',
        'shortcut[][type]': '1',
    }
    session.post(f"{BASE_URL}/game.php?page=fleetStep2", data=payload2)

    payload3 = {
        'token': token,
        'mission': 15,
        'metal': 0,
        'crystal': 0,
        'deuterium': 0,
        'staytime': 1,
    }
    r3 = session.post(f"{BASE_URL}/game.php?page=fleetStep3", data=payload3)

    if "fleetTable" in r3.url or "Fleet sent" in r3.text or "舰队发送" in r3.text:
        print("Fleet sent successfully.")
        return True
    else:
        print("Fleet may not have been sent (check manually).")
        return False

# ----------------------------------------------------------------------
# Main monitoring loop
# ----------------------------------------------------------------------
def main():
    # Read credentials from environment variables
    username = os.environ.get("GAME_USERNAME")
    password = os.environ.get("GAME_PASSWORD")
    if not username or not password:
        print("Error: GAME_USERNAME and GAME_PASSWORD environment variables must be set.")
        return

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent, "Referer": BASE_URL})
    session.verify = False

    print("Logging in...")
    r = session.post(f"{BASE_URL}/index.php?page=login", data={
        'uni': '1',
        'username': username,
        'password': password
    }, timeout=15)

    if "game.php" not in r.url:
        print("Login failed.")
        return
    print("Login successful.\n")

    try:
        while True:
            table = session.get(f"{BASE_URL}/game.php?page=fleetTable")
            soup = BeautifulSoup(table.text, 'html.parser')
            lanes = get_available_lanes(soup)

            if lanes != 0:
                print(f"Available exploration lanes: {lanes}")

                for _ in range(lanes):
                    print("Sending fleet...")
                    success = send_fleet(session)
                    if not success:
                        print("Fleet send failed, waiting before retry.")
                        break
                    time.sleep(2)

                print("Waiting 10 seconds...\n")

            # Always wait 10 seconds before checking again
            time.sleep(10)

    except KeyboardInterrupt:
        print("\nStopped by user.")

    print("Logging out...")
    session.get(f"{BASE_URL}/game.php?page=logout")
    session.cookies.clear()
    print("Done.")

if __name__ == "__main__":
    main()

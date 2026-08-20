import requests
import re
import urllib3
import time
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def read_config(filename="spec.txt"):
    with open(filename, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if len(lines) < 6:
        raise ValueError("Config file must have at least 6 non-empty lines.")

    base_url = lines[0]
    username = lines[1]
    password = lines[2]

    src_match = re.match(r"\[(\d+):(\d+):(\d+)\]", lines[3])
    if not src_match:
        raise ValueError("Invalid source coordinates format. Use [g:s:p]")
    src_galaxy, src_system, src_planet = map(int, src_match.groups())

    dst_match = re.match(r"\[(\d+):(\d+):(\d+)\]", lines[4])
    if not dst_match:
        raise ValueError("Invalid destination coordinates format. Use [g:s:p]")
    dst_galaxy, dst_system, dst_planet = map(int, dst_match.groups())

    ship_match = re.match(r"\(([^)]*)\)", lines[5])
    if not ship_match:
        raise ValueError("Invalid ships format. Use (id:count, id:count, ...)")
    ships_str = ship_match.group(1).strip()
    ships = {}
    if ships_str:
        for part in ships_str.split(","):
            part = part.strip()
            if ":" not in part:
                continue
            ship_id_str, count_str = part.split(":", 1)
            ship_id = int(ship_id_str.strip())
            count = int(count_str.strip())
            ships[ship_id] = count
    else:
        raise ValueError("Ship list cannot be empty. Provide at least one ship (id:count).")

    return {
        "base_url": base_url,
        "username": username,
        "password": password,
        "src_galaxy": src_galaxy,
        "src_system": src_system,
        "src_planet": src_planet,
        "dst_galaxy": dst_galaxy,
        "dst_system": dst_system,
        "dst_planet": dst_planet,
        "ships": ships,
    }

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

def send_fleet(session, base_url, config):
    src_galaxy = config["src_galaxy"]
    src_system = config["src_system"]
    src_planet = config["src_planet"]
    dst_galaxy = config["dst_galaxy"]
    dst_system = config["dst_system"]
    dst_planet = config["dst_planet"]
    ships = config["ships"]

    fleet_table = session.get(f"{base_url}/game.php?page=fleetTable")
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
            payload[name] = ships.get(sid, 0)

    save_groop_input = form.find('input', {'name': 'save_groop'})
    if save_groop_input is not None:
        payload['save_groop'] = ''

    payload.setdefault('galaxy', src_galaxy)
    payload.setdefault('system', src_system)
    payload.setdefault('planet', src_planet)
    payload.setdefault('type', 1)
    payload.setdefault('target_mission', 0)

    action = form.get('action')
    if action.startswith('?'):
        step1_url = f"{base_url}/game.php{action}"
    elif action.startswith('/'):
        step1_url = f"{base_url}{action}"
    elif action.startswith('http'):
        step1_url = action
    else:
        step1_url = f"{base_url}/{action}"

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
        'galaxy': dst_galaxy,
        'system': dst_system,
        'planet': dst_planet,
        'type': 1,
        'speed': 10,
        'shortcut[][name]': '',
        'shortcut[][galaxy]': '',
        'shortcut[][system]': '',
        'shortcut[][planet]': '',
        'shortcut[][type]': '1',
    }
    session.post(f"{base_url}/game.php?page=fleetStep2", data=payload2)

    payload3 = {
        'token': token,
        'mission': 15,
        'metal': 0,
        'crystal': 0,
        'deuterium': 0,
        'staytime': 1,
    }
    r3 = session.post(f"{base_url}/game.php?page=fleetStep3", data=payload3)

    if "fleetTable" in r3.url or "Fleet sent" in r3.text or "舰队发送" in r3.text:
        print("Fleet sent successfully.")
        return True
    else:
        print("Fleet may not have been sent (check manually).")
        return False

def main():
    config = read_config()
    base_url = config["base_url"]
    username = config["username"]
    password = config["password"]

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent, "Referer": base_url})
    session.verify = False

    print("Logging in...")
    r = session.post(f"{base_url}/index.php?page=login", data={
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
            table = session.get(f"{base_url}/game.php?page=fleetTable")
            soup = BeautifulSoup(table.text, 'html.parser')
            lanes = get_available_lanes(soup)

            if lanes != 0:
                print(f"Available exploration lanes: {lanes}")

                for _ in range(lanes):
                    print("Sending fleet...")
                    success = send_fleet(session, base_url, config)
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
    session.get(f"{base_url}/game.php?page=logout")
    session.cookies.clear()
    print("Done.")

if __name__ == "__main__":
    main()
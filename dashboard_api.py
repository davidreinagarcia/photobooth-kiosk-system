#!/usr/bin/env python3
"""
Photobooth Dashboard API — runs on port 9000
Serves hardware status, system info, and control actions.
Accessed from Chromebook via http://100.79.197.15:9000
"""
import os
import sys
import json
import subprocess
import glob
import time
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

SCRIPTS_DIR = "/home/david/photobooth-scripts"
KIOSK_API   = "http://localhost:8888"
PRICES_FILE = f"{SCRIPTS_DIR}/prices.json"

# ─── USB DEVICE IDs ───────────────────────────────────────
# Nikon D5000 USB vendor:product
NIKON_D5000_ID  = "04b0:0424"
# Mitsubishi CP-D70DW (old placeholder — replaced by Canon SELPHY below)
MITSUBISHI_ID   = "06d6:0061"
# Canon SELPHY CP1500 USB vendor:product
# TODO: fill in correct vendor:product when printer arrives
# Run `lsusb` with printer connected to find it (format: xxxx:xxxx)
CANON_SELPHY_ID = "PLACEHOLDER:PLACEHOLDER"
# CUPS printer name — run `lpstat -p` with printer connected to find exact name
CUPS_PRINTER_NAME = "Canon_SELPHY_CP1500"  # TODO: confirm when printer arrives
# Generic: any keyboard (HID class 03)
KEYBOARD_CLASS  = "03"

# ─── PRINTER INK/PAPER STATUS ─────────────────────────────
def get_printer_supplies():
    """
    Query Canon SELPHY CP1500 ink/paper status via CUPS.
    TODO: test with actual printer connected — SELPHY may or may not expose
    supply levels depending on connection type (USB vs WiFi) and driver.
    Run `lpstat -p` and `lpinfo -l -p <printer>` to check what's available.
    Returns dict with paper and ink counts, or None values if not readable.
    """
    # --- UNCOMMENT WHEN PRINTER IS CONNECTED AND CUPS IS SET UP ---
    # try:
    #     out = run(f"lpstat -p {CUPS_PRINTER_NAME} -l 2>/dev/null")
    #     # Parse supply levels from CUPS output
    #     # Note: exact parsing depends on driver — test and adjust
    #     paper_match = re.search(r"paper.*?(\d+)", out, re.IGNORECASE)
    #     ink_match   = re.search(r"ink.*?(\d+)%", out, re.IGNORECASE)
    #     paper = int(paper_match.group(1)) if paper_match else None
    #     ink   = int(ink_match.group(1))   if ink_match   else None
    #     return {"paper": paper, "ink": ink}
    # except Exception as e:
    #     print(f"⚠ Could not read printer supplies: {e}")
    #     return {"paper": None, "ink": None}
    return {"paper": None, "ink": None}  # placeholder until printer arrives

# ─── HELPERS ──────────────────────────────────────────────
def run(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
    except:
        return ""

def usb_connected(vendor_product):
    out = run(f"lsusb | grep -i '{vendor_product}'")
    return bool(out)

def any_usb_class(cls):
    """Check if any USB device with given class is connected."""
    out = run("lsusb -v 2>/dev/null | grep -i 'bDeviceClass'")
    return cls.lower() in out.lower()

def keyboard_connected():
    # Check /dev/input for keyboards
    out = run("ls /dev/input/by-id/ 2>/dev/null | grep -i kbd")
    return bool(out)

def get_hardware_status():
    camera   = usb_connected(NIKON_D5000_ID) or bool(run("lsusb | grep -i 'Nikon'"))
    printer  = usb_connected(CANON_SELPHY_ID) or bool(run("lsusb | grep -i 'Canon'"))
    flash    = bool(run("lsusb | grep -i 'flash\|speedlite\|godox\|yongnuo'"))
    keyboard = keyboard_connected()
    screen   = bool(run("xrandr 2>/dev/null | grep ' connected'"))
    supplies = get_printer_supplies()
    return {
        "camera":        camera,
        "printer":       printer,
        "flash":         flash,
        "keyboard":      keyboard,
        "screen":        screen,
        "printer_paper": supplies["paper"],
        "printer_ink":   supplies["ink"],
    }

def get_system_status():
    # CPU usage
    cpu = run("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'").replace("%us,","").strip()
    if not cpu:
        cpu = run("grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$3+$4+$5)} END {printf \"%.1f\", usage}'")

    # RAM
    mem = run("free -m | awk 'NR==2{printf \"%s/%s MB\", $3,$2}'")

    # Disk
    disk = run("df -h / | awk 'NR==2{printf \"%s used / %s total\", $3,$2}'")

    # Uptime
    uptime = run("uptime -p")

    # Temperature (if available)
    temp = run("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
    if temp:
        temp = f"{int(temp)//1000}°C"
    else:
        temp = "N/A"

    # Kiosk API status
    try:
        r = requests.get(f"{KIOSK_API}/kiosk-api/payment-status", timeout=1)
        api_ok = r.status_code == 200
    except:
        api_ok = False

    # Current mode (read from state file if exists)
    mode = "unknown"
    try:
        with open(f"{SCRIPTS_DIR}/current_mode.txt") as f:
            mode = f.read().strip()
    except:
        pass

    return {
        "cpu": cpu + "%" if cpu and "%" not in cpu else cpu,
        "memory": mem,
        "disk": disk,
        "uptime": uptime,
        "temperature": temp,
        "kiosk_api": api_ok,
        "mode": mode,
        "time": datetime.now().strftime("%b %d, %Y — %I:%M:%S %p")
    }

def get_prices():
    try:
        with open(PRICES_FILE) as f:
            return json.load(f)
    except:
        return {"digital": 5, "print": 10}

def save_prices(digital, print_price):
    with open(PRICES_FILE, "w") as f:
        json.dump({"digital": digital, "print": print_price}, f)
    # Patch kiosk_api.py prices live
    for script in ["kiosk_api.py"]:
        path = f"{SCRIPTS_DIR}/{script}"
        try:
            with open(path) as f:
                content = f.read()
            import re
            content = re.sub(r"PRICE_DIGITAL\s*=\s*\d+", f"PRICE_DIGITAL = {digital}", content)
            content = re.sub(r"PRICE_PRINT\s*=\s*\d+",   f"PRICE_PRINT = {print_price}", content)
            with open(path, "w") as f:
                f.write(content)
        except Exception as e:
            print(f"⚠ Could not patch {script}: {e}")

# ─── HTTP HANDLER ─────────────────────────────────────────
class DashboardHandler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/status":
            data = {
                "hardware": get_hardware_status(),
                "system":   get_system_status(),
                "prices":   get_prices(),
            }
            self.respond(data)
        elif self.path == "/" or self.path == "/dashboard":
            # Serve the dashboard HTML directly from this server
            try:
                with open("/var/www/html/dashboard.html", "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        if self.path == "/api/set-mode":
            mode = body.get("mode", "free")
            try:
                requests.post(f"{KIOSK_API}/kiosk-api/set-mode",
                              json={"mode": mode}, timeout=2)
                # Save current mode
                with open(f"{SCRIPTS_DIR}/current_mode.txt", "w") as f:
                    f.write(mode)
                self.respond({"ok": True})
            except Exception as e:
                self.respond({"ok": False, "error": str(e)})

        elif self.path == "/api/set-prices":
            digital     = int(body.get("digital", 5))
            print_price = int(body.get("print", 10))
            save_prices(digital, print_price)
            # Signal kiosk.html to reload prices
            try:
                with open("/var/www/html/kiosk_price_update.txt", "w") as f:
                    f.write("1")
            except Exception as e:
                print(f"⚠ Could not write price update flag: {e}")
            self.respond({"ok": True})

        elif self.path == "/api/enable-kiosk":
            # Block if a session is currently active
            try:
                r = requests.get(f"{KIOSK_API}/kiosk-api/payment-status", timeout=1)
                data = r.json()
                if data.get("paid"):
                    self.respond({"ok": False, "error": "Session in progress — wait until it finishes"})
                    return
            except:
                pass
            self.respond({"ok": True})
            def enable_kiosk():
                # Determine correct page based on current mode
                mode = "free"
                try:
                    with open(f"{SCRIPTS_DIR}/current_mode.txt") as f:
                        mode = f.read().strip()
                except:
                    pass
                url = "http://localhost/kiosk.html" if mode == "paid" else \
                      "http://localhost/kiosk-free.html" if mode == "free" else \
                      "http://localhost/mode_select.html"
                os.system("pkill -f firefox 2>/dev/null")
                time.sleep(2)
                os.system("pkill -f unclutter 2>/dev/null")
                os.system("unclutter -idle 0 -root &")
                os.system(f"DISPLAY=:0 firefox --kiosk {url} &")
                print(f"✓ Kiosk lockdown enabled → {url}")
            threading.Thread(target=enable_kiosk, daemon=True).start()

        elif self.path == "/api/disable-kiosk":
            self.respond({"ok": True})
            def disable_kiosk():
                mode = "free"
                try:
                    with open(f"{SCRIPTS_DIR}/current_mode.txt") as f:
                        mode = f.read().strip()
                except:
                    pass
                url = "http://localhost/kiosk.html" if mode == "paid" else \
                      "http://localhost/kiosk-free.html" if mode == "free" else \
                      "http://localhost/mode_select.html"
                os.system("pkill -f unclutter 2>/dev/null")
                os.system("pkill -f firefox 2>/dev/null")
                time.sleep(2)
                os.system(f"DISPLAY=:0 firefox {url} &")
                print("✓ Kiosk lockdown disabled")
            threading.Thread(target=disable_kiosk, daemon=True).start()

        elif self.path == "/api/reboot":
            self.respond({"ok": True})
            time.sleep(1)
            os.system("sudo reboot")

        elif self.path == "/api/trigger-collage":
            self.respond({"ok": True})
            def owner_session():
                import requests as req
                import time as t
                try:
                    # Set option to print, no phone
                    req.post(f"{KIOSK_API}/kiosk-api/set-phone",
                             json={"phone": None, "option": "print"}, timeout=2)
                    t.sleep(0.3)
                    # Use paid session flow — redirects Firefox to "Get Ready, press ENTER" page
                    req.post(f"{KIOSK_API}/kiosk-api/payment-confirmed",
                             json={}, timeout=2)
                except Exception as e:
                    print(f"⚠ Owner trigger: could not start session: {e}")
            threading.Thread(target=owner_session, daemon=True).start()

        elif self.path == "/api/shutdown":
            self.respond({"ok": True})
            time.sleep(1)
            os.system("pkill -f firefox 2>/dev/null")
            os.system("systemctl --user stop photobooth 2>/dev/null")
            time.sleep(2)
            os.system("sudo /sbin/shutdown -h now")

        elif self.path == "/api/restart-booth":
            self.respond({"ok": True})
            os.system("systemctl --user restart photobooth")

        else:
            self.send_response(404)
            self.end_headers()

    def respond(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass

# ─── MAIN ─────────────────────────────────────────────────
if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 9000), DashboardHandler)
    print("✓ Dashboard API running on port 9000")
    server.serve_forever()

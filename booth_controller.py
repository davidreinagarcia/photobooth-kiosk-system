import subprocess
import os
import time

# ─── CONFIGURATION ────────────────────────────────────────
STRIPE_WEBHOOK_SECRET  = os.environ["STRIPE_WEBHOOK_SECRET"]
STRIPE_API_KEY         = os.environ["STRIPE_API_KEY"]
STRIPE_PUBLISHABLE_KEY = os.environ["STRIPE_PUBLISHABLE_KEY"]

SCRIPTS_DIR = "/home/david/photobooth-scripts"
WEB_DIR     = "/var/www/html"

# ─── STARTUP SERVICES ─────────────────────────────────────
def start_services():
    procs = []

    # Kill Firefox (clean slate)
    print("Closing any existing Firefox windows...")
    os.system("pkill -f firefox 2>/dev/null")
    time.sleep(2)

    # Kill anything already on these ports
    print("Clearing ports...")
    os.system("sudo fuser -k 14711/tcp 2>/dev/null")
    os.system("sudo fuser -k 8888/tcp 2>/dev/null")
    time.sleep(1)

    # Start remotebuzzer
    print("Starting remotebuzzer...")
    procs.append(subprocess.Popen(
        ["sudo", "node", f"{WEB_DIR}/assets/js/remotebuzzer-server.js"],
        cwd=WEB_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    ))
    time.sleep(3)
    print("  ✓ Remotebuzzer running on port 14711")

    # Start kiosk API (no mode yet — mode_select.html will set it)
    print("Starting kiosk API...")
    log = open(f"{SCRIPTS_DIR}/kiosk_api.log", "a")
    procs.append(subprocess.Popen(
        ["python3", f"{SCRIPTS_DIR}/kiosk_api.py"],
        stdout=log,
        stderr=log
    ))
    time.sleep(1)
    print("  ✓ Kiosk API running on port 8888")

    # Start dashboard API
    print("Starting dashboard API...")
    log2 = open(f"{SCRIPTS_DIR}/dashboard_api.log", "a")
    procs.append(subprocess.Popen(
        ["python3", f"{SCRIPTS_DIR}/dashboard_api.py"],
        stdout=log2, stderr=log2
    ))
    print("  ✓ Dashboard API running on port 9000")

    # Run Drive cleanup in background
    print("Running Drive cleanup...")
    procs.append(subprocess.Popen(
        ["python3", "-c",
         "from drive_upload import cleanup_old_drive_folders; cleanup_old_drive_folders()"],
        cwd=SCRIPTS_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    ))

    return procs

# ─── MAIN ─────────────────────────────────────────────────
def main():
    print("\n========================================")
    print("       PHOTOBOOTH STARTUP")
    print("========================================")

    procs = start_services()

    # Wait for desktop to be fully ready before launching Firefox
    print("Waiting for desktop...")
    time.sleep(10)  # give GNOME extra time to fully load on boot

    # Wait until DISPLAY :0 is actually available (up to 30 extra seconds)
    for _ in range(15):
        result = os.system("DISPLAY=:0 xdpyinfo >/dev/null 2>&1")
        if result == 0:
            break
        print("  Display not ready yet, waiting...")
        time.sleep(2)

    print("Opening mode selection page...")
    os.system("DISPLAY=:0 firefox http://localhost/mode_select.html &")

    print("\n========================================")
    print("  Photobooth is running")
    print("  Select mode in Firefox (1=Paid, 2=Free)")
    print("  Press CTRL+C to shut everything down")
    print("========================================\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down all services...")
        os.system("pkill -f firefox 2>/dev/null")
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        print("✓ Done. Goodbye!")

if __name__ == "__main__":
    main()

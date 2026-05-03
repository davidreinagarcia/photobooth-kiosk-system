import os
import sys
import re
import json
import glob
import threading
import time
import stripe
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# ─── STRIPE CONFIGURATION ─────────────────────────────────
stripe.api_key = os.environ["STRIPE_API_KEY"]
STRIPE_WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]

PHOTOS_DIR   = "/var/www/html/data/images/"
PRICES_FILE  = "/home/david/photobooth-scripts/prices.json"
SCRIPTS_DIR  = "/home/david/photobooth-scripts"

def load_prices():
    try:
        with open(PRICES_FILE) as f:
            p = json.load(f)
            return p.get("digital", 5), p.get("print", 10)
    except:
        return 5, 10

PRICE_DIGITAL, PRICE_PRINT = load_prices()

# ─── SHARED STATE ─────────────────────────────────────────
state = {
    "payment_received": False,
    "session_done": False,
    "phone": None,
    "option": None,
    "mode": "free"
}

# ─── API HANDLER ──────────────────────────────────────────
class KioskAPIHandler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Stripe-Signature")
        self.end_headers()

    def do_GET(self):
        print(f"[API] GET: {self.path}")
        if self.path == "/kiosk-api/payment-status":
            self.respond({"paid": state["payment_received"]})
        elif self.path == "/kiosk-api/session-done":
            self.respond({"done": state["session_done"]})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length)

        # ── Stripe webhook (raw body needed for signature verification) ──
        if self.path == "/webhook":
            sig_header = self.headers.get("Stripe-Signature")
            try:
                event = stripe.Webhook.construct_event(
                    raw_body, sig_header, STRIPE_WEBHOOK_SECRET
                )
                if event["type"] == "checkout.session.completed":
                    print("\n💰 Payment received via webhook!")
                    state["payment_received"] = True
                    self.respond({"ok": True})
                    threading.Thread(target=run_paid_session, daemon=True).start()
                else:
                    self.respond({"ok": True})
            except Exception as e:
                print(f"Webhook error: {e}")
                self.send_response(400)
                self.end_headers()
            return

        # ── All other POST endpoints use JSON body ──
        try:
            body = json.loads(raw_body)
        except Exception:
            body = {}

        print(f"[API] POST: {self.path} | body: {body}")

        if self.path == "/kiosk-api/set-mode":
            mode = body.get("mode", "free")
            state["mode"] = mode
            print(f"✓ Mode set to: {mode}")
            # Persist mode so dashboard can read it
            try:
                with open(f"{SCRIPTS_DIR}/current_mode.txt", "w") as f:
                    f.write(mode)
            except Exception as e:
                print(f"⚠ Could not write mode file: {e}")
            self.respond({"ok": True})
            # Start Stripe listener if switching to paid and not already running
            if mode == "paid" and not state.get("stripe_running"):
                threading.Thread(target=start_stripe_listener, daemon=True).start()
            # Redirect Firefox to the correct kiosk page immediately
            threading.Thread(target=switch_kiosk_mode, args=(mode,), daemon=True).start()

        elif self.path == "/kiosk-api/start-free":
            state["phone"] = body.get("phone")
            state["session_done"] = False
            self.respond({"ok": True})
            threading.Thread(target=run_free_session, daemon=True).start()

        elif self.path == "/kiosk-api/create-payment":
            option = body.get("option", "digital")
            phone = body.get("phone")
            state["phone"] = phone
            state["option"] = option
            state["payment_received"] = False
            PRICE_DIGITAL, PRICE_PRINT = load_prices()
            price = PRICE_PRINT if option == "print" else PRICE_DIGITAL
            try:
                checkout = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[{
                        "price_data": {
                            "currency": "usd",
                            "product_data": {
                                "name": f"Photobooth {'Print + Digital' if option == 'print' else 'Digital'}",
                            },
                            "unit_amount": price * 100,
                        },
                        "quantity": 1,
                    }],
                    mode="payment",
                    success_url="https://buy.stripe.com/success",
                    cancel_url="http://100.79.197.15/kiosk.html",
                )
                self.respond({"ok": True, "url": checkout.url, "session_id": checkout.id})
            except Exception as e:
                print(f"Stripe error: {e}")
                self.respond({"ok": False, "error": str(e)})

        elif self.path == "/kiosk-api/payment-confirmed":
            # Fallback in case webhook was slow or missed
            if not state["payment_received"]:
                print("\n💰 Payment confirmed via success page (webhook fallback)!")
                state["payment_received"] = True
                self.respond({"ok": True})
                threading.Thread(target=run_paid_session, daemon=True).start()
            else:
                self.respond({"ok": True, "already_running": True})

        elif self.path == "/kiosk-api/start-collage":
            # Called when user presses ENTER on payment success page
            self.respond({"ok": True})
            def fire_collage():
                time.sleep(3)  # give Firefox time to load PhotoboothProject
                print("Firing collage trigger...")
                os.system("curl -s -X GET http://localhost:14711/commands/start-collage")
                threading.Thread(target=session_watchdog, daemon=True).start()
            threading.Thread(target=fire_collage, daemon=True).start()

        elif self.path == "/kiosk-api/reload-kiosk":
            # Reload the current kiosk page (e.g. after price change)
            mode = state.get("mode", "free")
            url = "http://localhost/kiosk.html" if mode == "paid" else "http://localhost/kiosk-free.html"
            try:
                with open("/var/www/html/kiosk_redirect.txt", "w") as f:
                    f.write(url)
            except Exception as e:
                print(f"⚠ Could not write reload flag: {e}")
            self.respond({"ok": True})

        elif self.path == "/kiosk-api/set-phone":
            state["phone"] = body.get("phone")
            state["option"] = body.get("option")
            self.respond({"ok": True})

        elif self.path == "/kiosk-api/session-complete":
            # PhotoboothProject calls this when collage is fully saved
            state["session_done"] = True
            self.respond({"ok": True})
            threading.Thread(target=process_and_deliver, daemon=True).start()

        else:
            self.send_response(404)
            self.end_headers()

    def respond(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass

# ─── SESSION LOGIC ────────────────────────────────────────
def run_paid_session():
    print(f"\n✓ Paid session ready for {state['phone']}")
    state["session_done"] = False
    # Navigate Firefox on the VM to the "Get Ready" page
    # Customer presses ENTER there to start the collage
    try:
        with open("/var/www/html/kiosk_redirect.txt", "w") as f:
            f.write("http://localhost/kiosk_payment_success.html")
        print("✓ Redirecting Firefox to Get Ready page")
    except Exception as e:
        print(f"⚠ Could not write redirect: {e}")

def session_watchdog():
    """
    If PhotoboothProject never calls /session-complete within 60 seconds
    of the collage trigger (e.g. camera not detected, crash), redirect
    back to the kiosk so the booth isn't stuck on a black screen.
    """
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(2)
        if state["session_done"]:
            return  # session completed normally, nothing to do
    print("⚠ Watchdog: session-complete never received — redirecting back to kiosk")
    state["payment_received"] = False
    state["phone"] = None
    state["session_done"] = True
    reopen_kiosk()

def run_free_session():
    print(f"\n✓ Free session starting for {state['phone']}")
    print("Waiting for Firefox to switch to PhotoboothProject...")
    time.sleep(5)
    state["session_done"] = False
    print("Firing collage trigger...")
    os.system("curl -s -X GET http://localhost:14711/commands/start-collage")
    threading.Thread(target=session_watchdog, daemon=True).start()
    # process_and_deliver() called by /session-complete when PhotoboothProject is done

def reopen_kiosk():
    """Redirect Firefox back to kiosk after a session ends."""
    time.sleep(2)
    mode = state.get("mode", "free")
    url = "http://localhost/kiosk.html" if mode == "paid" else "http://localhost/kiosk-free.html"
    try:
        with open("/var/www/html/kiosk_redirect.txt", "w") as f:
            f.write(url)
        print(f"✓ Kiosk redirect flag set to {url}")
    except Exception as e:
        print(f"⚠ Could not write redirect flag: {e}")

def switch_kiosk_mode(mode):
    """Write redirect flag — kiosk pages poll kiosk_check.php every 2s and will navigate."""
    url = "http://localhost/kiosk.html" if mode == "paid" else "http://localhost/kiosk-free.html"
    print(f"✓ Switching kiosk to {url}")
    try:
        with open("/var/www/html/kiosk_redirect.txt", "w") as f:
            f.write(url)
    except Exception as e:
        print(f"⚠ Could not write redirect flag: {e}")

def find_session_files():
    """
    Returns (collage_path, [individual_paths]) for the most recent session.

    PhotoboothProject saves files as:
      YYYYMMDD_HHMMSS.jpg    ← collage (no dash-number suffix)
      YYYYMMDD_HHMMSS-0.jpg  ← individual shot 1
      YYYYMMDD_HHMMSS-1.jpg  ← individual shot 2
      YYYYMMDD_HHMMSS-2.jpg  ← individual shot 3
      YYYYMMDD_HHMMSS-3.jpg  ← individual shot 4
    """
    all_files = glob.glob(PHOTOS_DIR + "*.jpg")
    all_files = [f for f in all_files if "_digital" not in f]  # kept in case of old files
    if not all_files:
        return None, []

    collages    = {}  # prefix -> path
    individuals = {}  # prefix -> [paths]

    for f in all_files:
        base = os.path.basename(f)
        # Individual: YYYYMMDD_HHMMSS-N.jpg
        m = re.match(r"^(\d{8}_\d{6})-\d+\.jpg$", base)
        if m:
            prefix = m.group(1)
            individuals.setdefault(prefix, []).append(f)
            continue
        # Collage: YYYYMMDD_HHMMSS.jpg
        m = re.match(r"^(\d{8}_\d{6})\.jpg$", base)
        if m:
            prefix = m.group(1)
            collages[prefix] = f

    if not collages:
        latest = max(all_files, key=os.path.getmtime)
        return latest, []

    # Pick the most recently modified collage
    latest_prefix = max(collages.keys(), key=lambda p: os.path.getmtime(collages[p]))
    collage = collages[latest_prefix]
    session_individuals = sorted(individuals.get(latest_prefix, []))
    return collage, session_individuals

def cleanup_local_files(file_paths):
    """Delete specific local files after successful Drive upload."""
    deleted = 0
    for f in file_paths:
        try:
            os.remove(f)
            deleted += 1
        except Exception as e:
            print(f"  ⚠ Could not delete {f}: {e}")
    if deleted > 0:
        print(f"✓ Deleted {deleted} local files after upload")

def process_and_deliver():
    collage, individuals = find_session_files()

    if not collage:
        print("✗ No collage found!")
        state["session_done"] = True
        state["payment_received"] = False
        reopen_kiosk()
        return

    print(f"✓ Collage: {collage}")
    print(f"✓ Individuals: {individuals}")

    upload_ok = False
    try:
        from drive_upload import upload_session_folder
        mtime = os.path.getmtime(collage)
        session_dt = datetime.fromtimestamp(mtime)
        # Structure: Root / Apr10_2026 / 10-25PM / files
        day_folder_name     = session_dt.strftime("%b%d_%Y")        # e.g. Apr10_2026
        session_folder_name = session_dt.strftime("%I-%M%p")        # e.g. 10-25PM

        print(f"Uploading to Drive: {day_folder_name} / {session_folder_name} ...")
        # Upload collage + all individual shots (no cropping needed with 3+1 layout)
        all_files = [collage] + individuals
        folder_link = upload_session_folder(day_folder_name, session_folder_name, all_files)
        print(f"✓ Folder link: {folder_link}")
        upload_ok = True

        # Clean up Drive folders older than 7 days
        try:
            from drive_upload import cleanup_old_drive_folders
            cleanup_old_drive_folders()
        except Exception as e:
            print(f"⚠ Drive cleanup skipped: {e}")

        if state["phone"]:
            try:
                from sms_sender import send_photo_link
                print(f"Sending SMS to {state['phone']}...")
                send_photo_link(state["phone"], folder_link)
            except Exception as e:
                print(f"⚠ SMS skipped: {e}")
        else:
            print(f"✓ No phone provided — link: {folder_link}")

        # ─── PRINT JOB ────────────────────────────────────────
        # TODO: uncomment and configure when Canon SELPHY CP1500 is connected
        # Prints the collage (full 4x6, 3+1 layout) via CUPS
        # Prerequisites:
        #   1. Install CUPS Canon SELPHY driver: sudo apt install printer-driver-gutenprint
        #   2. Add printer via CUPS web UI at http://localhost:631
        #   3. Confirm printer name with: lpstat -p
        #   4. Update CUPS_PRINTER_NAME in dashboard_api.py to match
        # if state.get("option") == "print" and collage:
        #     try:
        #         cups_printer = "Canon_SELPHY_CP1500"  # TODO: confirm name with lpstat -p
        #         print(f"Sending print job to {cups_printer}...")
        #         os.system(f'lp -d {cups_printer} -o media=w288h432 -o fit-to-page "{collage}"')
        #         print("✓ Print job sent")
        #     except Exception as e:
        #         print(f"⚠ Print job failed: {e}")
        # ──────────────────────────────────────────────────────

    except Exception as e:
        print(f"⚠ Drive upload skipped: {e}")

    # Delete local files only after confirmed upload
    if upload_ok:
        all_local = [collage] + individuals
        cleanup_local_files(all_local)
    else:
        print("⚠ Keeping local files since upload failed")

    # Reset state for next session
    state["session_done"] = True
    state["payment_received"] = False
    state["phone"] = None
    print("✓ Session complete — reopening kiosk...")
    reopen_kiosk()

# ─── STRIPE LISTENER ─────────────────────────────────────
def start_stripe_listener():
    import subprocess
    print("✓ Starting Stripe webhook listener...")
    state["stripe_running"] = True
    proc = subprocess.Popen(
        ["stripe", "listen", "--forward-to", "localhost:8888/webhook"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    proc.wait()
    state["stripe_running"] = False
    print("⚠ Stripe listener stopped")

# ─── START SERVER ─────────────────────────────────────────
def start_kiosk_api(mode="free"):
    state["mode"] = mode
    server = HTTPServer(("0.0.0.0", 8888), KioskAPIHandler)
    print(f"✓ Kiosk API running on port 8888 (mode: {mode})")
    server.serve_forever()

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "free"
    start_kiosk_api(mode)

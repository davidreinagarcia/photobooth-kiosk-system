# 📸 Photobooth Kiosk System

A self-hosted photobooth built as a college fun project, running on an Ubuntu machine connected to a Nikon D5000 camera and a Canon SELPHY CP1500 photo printer. Guests interact with a browser-based kiosk, pay (or not), take a 4-shot collage, and receive their photos via SMS link — all automatically.

This repo contains the **custom Python backend** built on top of the open-source [PhotoboothProject](https://photoboothproject.github.io/), which handles the camera capture, collage assembly, and the core web UI. Everything here is the layer we added: payment processing, session management, Google Drive delivery, SMS notifications, and a remote operator dashboard.

---

## How It Works

```
Guest approaches booth
        │
        ▼
┌─────────────────────────────────────────┐
│           mode_select.html              │  ← operator picks mode on boot
│         (Paid Mode / Free Mode)         │
└────────────────┬────────────────────────┘
                 │
      ┌──────────┴──────────┐
      │                     │
      ▼                     ▼
 kiosk.html           kiosk-free.html
 (Stripe payment)     (enter phone → go)
      │                     │
      └──────────┬──────────┘
                 │
                 ▼
     PhotoboothProject fires camera
     → 4 shots → collage assembled
                 │
                 ▼
     kiosk_api.py receives /session-complete
                 │
          ┌──────┴───────┐
          ▼              ▼
   Google Drive     Twilio SMS
   upload folder    → guest's phone
   (auto-deleted    with Drive link
    after 7 days)
```

---

## Modes

### 💳 Paid Mode
Guests enter their phone number and select **Digital** or **Print + Digital**. A Stripe Checkout page opens on the kiosk screen. Once payment is confirmed (via Stripe webhook), the booth fires automatically — no staff needed. Prices are configurable live from the dashboard without restarting anything.

### 🆓 Free Mode
Guests enter their phone number and the session starts immediately. Same delivery flow — Drive upload + SMS link.

### 👤 Owner Trigger
The dashboard has a one-click button to fire a session without any payment or phone, useful for testing or owner use.

---

## The Dashboard

Accessed remotely from a Chromebook (or any browser on the same network) at `http://<booth-ip>:9000`. Gives full operator control without touching the booth machine.

**Hardware status panel**
- Live detection of camera (Nikon D5000), printer (Canon SELPHY CP1500), flash, keyboard, and screen — shown as green/red indicators
- Printer ink and paper level (once printer is connected via CUPS)
- CPU, RAM, disk usage, temperature, and uptime

**Controls**
- Switch between Paid / Free mode instantly
- Enable / disable kiosk lockdown (Firefox goes fullscreen kiosk mode, cursor hidden)
- Adjust Digital and Print prices — takes effect immediately without restart
- Trigger an owner collage session
- Reboot or shut down the booth machine remotely
- Restart the booth service

---

## File Overview

| File | What it does |
|---|---|
| `booth_controller.py` | Entry point. Starts all services on boot and opens Firefox to the mode selection page |
| `kiosk_api.py` | Core session API on port 8888. Handles Stripe webhooks, session state, photo delivery orchestration |
| `dashboard_api.py` | Operator dashboard API on port 9000. Hardware detection, system stats, all control actions |
| `drive_upload.py` | Uploads session photos to a structured Google Drive folder (`MonthDay_Year / HH-MMam`). Auto-deletes folders older than 7 days |
| `sms_sender.py` | Sends the Drive folder link to the guest's phone via Twilio |
| `prices.json` | Persists current Digital / Print prices across restarts |

The HTML files (`kiosk.html`, `kiosk-free.html`, `kiosk_payment_success.html`, `mode_select.html`, `dashboard.html`) live in the web root alongside PhotoboothProject's files and are not included in this repo.

---

## Hardware

| Component | Model |
|---|---|
| Camera | Nikon D5000 (USB tethered via gphoto2) |
| Printer | Canon SELPHY CP1500 *(arriving soon — CUPS setup pending)* |
| Flash | External speedlite |
| Kiosk screen | Connected via HDMI |
| Machine | Ubuntu desktop |

---

## Stack

- **[PhotoboothProject](https://photoboothproject.github.io/)** — open-source base handling camera capture, collage layout, and the core web UI (PHP + JS). This repo adds the custom backend layer on top.
- **Stripe** — payment processing and webhooks
- **Twilio** — SMS delivery
- **Google Drive API** — photo storage and sharing
- **Python** `http.server` — lightweight API servers (no framework needed for this scale)
- **Firefox in kiosk mode** — fullscreen guest-facing display

---

## Setup

**1. Clone and install dependencies**
```bash
git clone https://github.com/davidreinagarcia/photobooth-kiosk-system
cd photobooth-kiosk-system
pip install -r requirements.txt
```

**2. Configure environment variables**
```bash
cp .env.example .env
# Fill in your Stripe, Twilio, and Google Drive credentials
```

**3. Google Drive auth**

Place your OAuth client credentials at `photobooth-scripts/credentials_oauth.json` (download from Google Cloud Console → APIs & Services → Credentials). On first run, `drive_upload.py` will open a browser to authorize and save a `token.pickle` for future runs.

**4. Install PhotoboothProject**

Follow the [PhotoboothProject installation guide](https://photoboothproject.github.io/). The Python scripts expect it to be served from `/var/www/html` with the remotebuzzer server enabled.

**5. Run**
```bash
python booth_controller.py
```

This starts the kiosk API (port 8888), dashboard API (port 9000), and opens Firefox to the mode selection page.

---

## Project Context

Built as a fun college side project with a friend. The goal was a fully self-contained photobooth that can be set up at parties or events — guests pay on the spot, take their photos, and get a link on their phone within seconds. No app, no account, no friction.

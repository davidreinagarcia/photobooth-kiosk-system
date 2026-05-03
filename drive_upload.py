import os
import pickle
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ─── CONFIGURATION ────────────────────────────────────────
CREDENTIALS_FILE = "/home/david/photobooth-scripts/credentials_oauth.json"
TOKEN_FILE       = "/home/david/photobooth-scripts/token.pickle"
DRIVE_FOLDER_ID  = os.environ["DRIVE_FOLDER_ID"]   # root photobooth folder
SCOPES           = ["https://www.googleapis.com/auth/drive"]

# ─── AUTHENTICATION ───────────────────────────────────────
def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)
    return build("drive", "v3", credentials=creds)

# ─── HELPERS ──────────────────────────────────────────────
def make_public(service, file_id):
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"}
    ).execute()

def get_or_create_folder(service, name, parent_id):
    """Find existing folder by name under parent, or create it."""
    query = (
        f"name='{name}' and "
        f"'{parent_id}' in parents and "
        f"mimeType='application/vnd.google-apps.folder' and "
        f"trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, webViewLink)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"], files[0]["webViewLink"]

    # Create it
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id]
    }
    folder = service.files().create(body=meta, fields="id, webViewLink").execute()
    make_public(service, folder["id"])
    return folder["id"], folder["webViewLink"]

def upload_file(service, file_path, parent_id):
    file_name = os.path.basename(file_path)
    media = MediaFileUpload(file_path, mimetype="image/jpeg")
    meta = {"name": file_name, "parents": [parent_id]}
    uploaded = service.files().create(
        body=meta, media_body=media, fields="id, webViewLink"
    ).execute()
    make_public(service, uploaded["id"])
    print(f"  ✓ Uploaded: {file_name}")
    return uploaded.get("webViewLink")

# ─── MAIN UPLOAD FUNCTION ─────────────────────────────────
def upload_session_folder(day_folder_name, session_folder_name, file_paths):
    """
    Drive structure:
      Root (DRIVE_FOLDER_ID)
        └── Apr10_2026          ← day_folder_name
              └── 10-25PM       ← session_folder_name
                    └── files

    Returns the shareable link to the session folder.
    """
    service = get_drive_service()

    # Get or create the day folder
    day_id, _ = get_or_create_folder(service, day_folder_name, DRIVE_FOLDER_ID)
    print(f"✓ Day folder ready: {day_folder_name}")

    # Create the session folder inside the day folder
    session_id, session_link = get_or_create_folder(service, session_folder_name, day_id)
    print(f"✓ Session folder ready: {session_folder_name}")

    # Upload all files
    for file_path in file_paths:
        if not os.path.exists(file_path):
            print(f"  ⚠ File not found, skipping: {file_path}")
            continue
        upload_file(service, file_path, session_id)

    print(f"✓ All files uploaded → {session_link}")
    return session_link

# ─── DRIVE CLEANUP (folders older than 7 days) ────────────
def cleanup_old_drive_folders():
    """
    Deletes day folders in the root photobooth Drive folder
    whose names parse to a date older than 7 days.
    Folder name format: Apr10_2026
    """
    service = get_drive_service()
    query = (
        f"'{DRIVE_FOLDER_ID}' in parents and "
        f"mimeType='application/vnd.google-apps.folder' and "
        f"trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get("files", [])
    cutoff = datetime.now() - timedelta(days=7)
    deleted = 0

    for folder in folders:
        name = folder["name"]
        try:
            folder_date = datetime.strptime(name, "%b%d_%Y")
            if folder_date < cutoff:
                service.files().delete(fileId=folder["id"]).execute()
                print(f"  ✓ Deleted old Drive folder: {name}")
                deleted += 1
        except ValueError:
            pass  # folder name doesn't match date format, skip

    if deleted == 0:
        print("✓ No old Drive folders to clean up")
    else:
        print(f"✓ Removed {deleted} Drive folder(s) older than 7 days")

# ─── TEST ─────────────────────────────────────────────────
if __name__ == "__main__":
    import glob
    images = glob.glob("/var/www/html/data/images/*.jpg")
    if not images:
        print("No images found to test with.")
    else:
        test_files = images[:2]
        print(f"Testing with: {test_files}")
        link = upload_session_folder("TestDay_Apr10_2026", "12-00PM_test", test_files)
        print(f"✓ Done! Link: {link}")
        print("\nTesting Drive cleanup (dry run — nothing old enough to delete yet)...")
        cleanup_old_drive_folders()

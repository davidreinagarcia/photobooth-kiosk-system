def send_photo_link(customer_phone, drive_link):
    """
    Send the Google Drive folder link to the customer via Twilio SMS.
    Uses Messaging Service SID for sending (better deliverability than raw number).
    Twilio number: +18446260910
    Trial mode: can only send to verified numbers. Upgrade account to send to anyone.
    """
    TWILIO_ACCOUNT_SID    = os.environ["TWILIO_ACCOUNT_SID"]
    TWILIO_AUTH_TOKEN     = os.environ["TWILIO_AUTH_TOKEN"]
    TWILIO_MESSAGING_SID  = os.environ["TWILIO_MESSAGING_SID"]

    from twilio.rest import Client
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    message = client.messages.create(
        body=f"Thanks for using our photobooth! 📸 Your photos are here: {drive_link}",
        messaging_service_sid=TWILIO_MESSAGING_SID,
        to=customer_phone
    )
    print(f"✓ SMS sent to {customer_phone} | SID: {message.sid}")
    return message.sid

# ─── TEST ─────────────────────────────────────────────────
if __name__ == "__main__":
    # To test: add your number as a verified caller ID in Twilio console first
    # https://console.twilio.com/us1/develop/phone-numbers/manage/verified
    test_phone = "+1XXXXXXXXXXX"  # replace with a verified Twilio number  # replace with your verified number
    test_link  = "https://drive.google.com/drive/folders/test"
    print(f"Sending test SMS to {test_phone}...")
    send_photo_link(test_phone, test_link)

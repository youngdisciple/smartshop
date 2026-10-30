import os
import imaplib
from dotenv import load_dotenv

load_dotenv()

email_address = os.getenv("GMAIL_ADDRESS")
app_password = os.getenv("GMAIL_APP_PASSWORD")

try:
    with imaplib.IMAP4_SSL("imap.gmail.com") as mail:
        mail.login(email_address, app_password)
        status, data = mail.select("INBOX")

        if status == "OK":
            print("Gmail connection successful!")
            print("Inbox opened successfully.")
        else:
            print("Could not open Gmail inbox.")

except Exception as error:
    print("Gmail connection failed:", type(error).__name__)

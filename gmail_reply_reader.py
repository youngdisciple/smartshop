
import imaplib
import email
import os
import time
from email.header import decode_header
from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

IMAP_HOST = "imap.gmail.com"
CHECK_INTERVAL = 15
last_checked_uid = None


def get_email_text(message):
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                if part.get_filename() is None:
                    content = part.get_payload(decode=True)
                    if content:
                        return content.decode(
                            part.get_content_charset() or "utf-8",
                            errors="replace"
                        )
    else:
        content = message.get_payload(decode=True)
        if content:
            return content.decode(
                message.get_content_charset() or "utf-8",
                errors="replace"
            )

    return ""


def check_replies():
    global last_checked_uid

    with imaplib.IMAP4_SSL(IMAP_HOST) as mail:
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("INBOX")

        status, data = mail.uid(
            "search", None, '(SUBJECT "SmartShop alert")'
        )

        if status != "OK":
            return

        uids = data[0].split()

        # Ignore old emails when the reader first starts.
        if last_checked_uid is None:
            if uids:
                last_checked_uid = max(int(uid) for uid in uids)

            print("Reply reader ready. Waiting for new SmartShop emails.")
            return

        for uid in uids:
            uid_number = int(uid)

            if uid_number <= last_checked_uid:
                continue

            status, result = mail.uid("fetch", uid, "(RFC822)")

            if status != "OK" or not result or not isinstance(result[0], tuple):
                continue

            message = email.message_from_bytes(result[0][1])

            subject_parts = decode_header(message.get("Subject", ""))
            subject = "".join(
                part.decode(encoding or "utf-8", errors="replace")
                if isinstance(part, bytes) else part
                for part, encoding in subject_parts
            )

            sender = email.utils.parseaddr(
                message.get("From", "")
            )[1]

            body = get_email_text(message)

            first_line = next(
                (line.strip() for line in body.splitlines() if line.strip()),
                ""
            )

            if (
                "SmartShop alert" in subject
                and sender.lower() == GMAIL_ADDRESS.lower()
                and first_line.upper() == "YES"
            ):
                print("Valid YES reply detected.")

                try:
                    from fan_controller import fan_on
                    from website import app
                    fan_on()
                    with app.app_context():
                        print("Fan ON command sent.")
                except Exception as error:
                    print("Fan control failed:", type(error).__name__)

            else:
                print("New email ignored.")

            last_checked_uid = max(last_checked_uid, uid_number)


def start_reply_reader():
    while True:
        try:
            check_replies()
        except Exception as error:
            print("Email reply check failed:", type(error).__name__)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    start_reply_reader()

import email
import imaplib
from email.header import decode_header


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


class ReplyReader:
    def __init__(self, address, password, fan_on):
        self.address = address
        self.password = password
        self.fan_on = fan_on
        self.host = "imap.gmail.com"
        self.last_checked_uid = None

    def check_replies(self):
        with imaplib.IMAP4_SSL(self.host, timeout=10) as mail:
            mail.login(self.address, self.password)
            mail.select("INBOX")

            status, data = mail.uid(
                "search", None, '(SUBJECT "SmartShop alert")'
            )

            if status != "OK":
                return

            uids = data[0].split()

            # Ignore old emails when the reader first starts.
            if self.last_checked_uid is None:
                if uids:
                    self.last_checked_uid = max(int(uid) for uid in uids)

                print("Reply reader ready. Waiting for new SmartShop emails.")
                return

            for uid in uids:
                uid_number = int(uid)

                if uid_number <= self.last_checked_uid:
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
                    and sender.lower() == self.address.lower()
                    and first_line.upper() == "YES"
                ):
                    print("Valid YES reply detected.")

                    try:
                        self.fan_on()
                        print("Fan ON command sent.")
                    except Exception as error:
                        print("Fan control failed:", type(error).__name__)

                else:
                    print("New email ignored.")

                self.last_checked_uid = max(self.last_checked_uid, uid_number)

    def run(self, stop_event):
        while not stop_event.is_set():
            try:
                self.check_replies()
            except Exception as error:
                print("Email reply check failed:", type(error).__name__)
            stop_event.wait(15)

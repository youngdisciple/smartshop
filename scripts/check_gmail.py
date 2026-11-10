"""Check Gmail credentials: python -m scripts.check_gmail."""
import imaplib
from smartshop.config import load_config


def main():
    config = load_config()
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com", timeout=10) as mail:
            mail.login(config["GMAIL_ADDRESS"], config["GMAIL_APP_PASSWORD"])
            status, data = mail.select("INBOX")
            if status == "OK":
                print("Gmail connection successful!")
                print("Inbox opened successfully.")
            else:
                print("Could not open Gmail inbox.")
    except Exception as error:
        print("Gmail connection failed:", type(error).__name__)


if __name__ == "__main__":
    main()

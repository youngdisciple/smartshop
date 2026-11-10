"""Explicitly arm the dedicated membership reader; prints UID, never links it."""
import time
from smartshop.config import load_config
from smartshop.services.membership import MembershipReader


def main():
    service = MembershipReader(load_config())
    try:
        service.start()
        deadline = time.monotonic() + 20
        while not service.reader_epoch and time.monotonic() < deadline:
            time.sleep(0.1)
        operation = service.arm('diagnostic', 'checkout')
        print('Present a fresh card within 60 seconds. No account will be linked.')
        while True:
            uid = service.result('diagnostic', operation, 'checkout')
            if uid:
                print('UID:', uid)
                return
            time.sleep(0.1)
    finally:
        service.stop()


if __name__ == '__main__':
    main()

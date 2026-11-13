"""Print EPCs from a bounded CF600 serial/HID scan or an explicit fake scan."""
import argparse
from math import isfinite
from time import monotonic, sleep
from smartshop.hardware.cf600 import CF600Reader, DEFAULT_DEVICE
from smartshop.hardware.product_reader import FakeReader, ProductReader
from smartshop.hardware.cf600_serial import CF600SerialReader, DEFAULT_SERIAL_DEVICE


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--fake', action='store_true')
    mode.add_argument('--hardware', action='store_true')
    parser.add_argument('--backend', choices=('cf600_serial', 'cf600_hid'), default='cf600_serial')
    parser.add_argument('--device')
    parser.add_argument('--baudrate', type=int, default=57600)
    parser.add_argument('--seconds', type=float, default=15)
    parser.add_argument('epcs', nargs='*')
    args = parser.parse_args(argv)
    if not isfinite(args.seconds) or not 0 < args.seconds <= 60:
        parser.error('--seconds must be greater than 0 and at most 60')
    if args.fake and not args.epcs:
        parser.error('--fake requires at least one EPC')
    if args.hardware and args.epcs:
        parser.error('EPC arguments are only allowed with --fake')
    if args.fake:
        adapter = FakeReader()
    elif args.backend == 'cf600_serial':
        adapter = CF600SerialReader(args.device or DEFAULT_SERIAL_DEVICE, args.baudrate)
    else:
        adapter = CF600Reader(args.device or DEFAULT_DEVICE)
    reader = ProductReader(adapter)
    try:
        operation = reader.arm('diagnostic', 'inventory')
        if args.fake:
            adapter.reads.extend(args.epcs)
            print('\n'.join(reader.poll('diagnostic', operation['id'])))
        else:
            print(f'CF600 armed ({args.backend}); present tags. Ctrl-C stops.', flush=True)
            deadline = monotonic() + args.seconds
            seen = set()
            while monotonic() < deadline:
                for value in reader.poll('diagnostic', operation['id']):
                    if value not in seen:
                        print(value, flush=True)
                        seen.add(value)
                sleep(min(0.1, max(0, deadline - monotonic())))
            print(f'{len(seen)} distinct EPC(s)', flush=True)
    except KeyboardInterrupt:
        pass
    except ValueError as error:
        parser.exit(1, f'{error}\n')
    finally:
        reader.stop()


if __name__ == '__main__':
    main()

"""Guarded fake-reader diagnostic. No invented CF600 SDK bindings."""
import argparse
from smartshop.hardware.product_reader import FakeReader, ProductReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fake', action='store_true', required=True)
    parser.add_argument('epcs', nargs='+')
    args = parser.parse_args()
    adapter = FakeReader()
    reader = ProductReader(adapter)
    try:
        operation = reader.arm('diagnostic', 'inventory')
        adapter.reads.extend(args.epcs)
        print('\n'.join(reader.poll('diagnostic', operation['id'])))
    finally:
        reader.stop()


if __name__ == '__main__':
    main()

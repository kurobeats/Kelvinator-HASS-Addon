"""
CLI: Command-line interface for the Kelvinator DNA library.

Usage:
    kelvinator-cli discover                  # Find devices on LAN
    kelvinator-cli status -d devices.json    # Get device status
    kelvinator-cli control -d devices.json --power-on --mode cool --temp 22

For development:
    python -m kelvinator_dna.cli discover
"""

import argparse
import json
import logging
import sys

from .device import KelvinatorDevice, discover_devices
from .cloud import load_cached_devices
from .commands import ACState


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S',
    )


def cmd_discover(args: argparse.Namespace) -> None:
    """Discover Kelvinator AC devices on the local network."""
    print("Discovering devices on the local network...")
    raw_devices = discover_devices(timeout=args.timeout)
    if not raw_devices:
        print("No devices found.")
        return

    print(f"\nFound {len(raw_devices)} device(s):")
    for d in raw_devices:
        print(f"  IP:   {d['ip']}")
        print(f"  MAC:  {d['mac']}")
        print(f"  DID:  {d['did']}")
        if d.get('name'):
            print(f"  Name: {d['name']}")
        print()

    if args.output:
        output = {
            "devices": [
                {
                    "did": d["did"],
                    "mac": d["mac"],
                    "name": d.get("name", ""),
                    "devtype": 20379,
                    "pid": "9b4f0000",
                    "password": 0,
                    "aes_key": "",
                    "terminal_id": 1,
                    "sub_device_num": 0,
                    "room_id": "",
                    "room_name": "",
                }
                for d in raw_devices
            ]
        }
        with open(args.output, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"Saved to {args.output}")
        print("Note: Fill in 'aes_key' and 'password' from cloud API before using.")


def cmd_status(args: argparse.Namespace) -> None:
    """Query device status."""
    devices = load_cached_devices(args.device_file)
    if not devices:
        print("No devices found in config file.")
        return
    dev_info = devices[0]

    if not args.ip:
        print("Please specify device IP with --ip")
        return

    dev = KelvinatorDevice(
        ip=args.ip,
        did=dev_info.did,
        mac=dev_info.mac,
        aes_key=dev_info.aes_key,
        password=dev_info.password,
    )

    with dev:
        status = dev.get_status()
        print(f"Device: {dev_info.name or dev_info.did}")
        print(f"Status: {status}")
        if status.raw:
            print(f"Raw:    {status.raw}")


def cmd_control(args: argparse.Namespace) -> None:
    """Send control commands to the AC unit."""
    devices = load_cached_devices(args.device_file)
    if not devices:
        print("No devices found in config file.")
        return
    dev_info = devices[0]

    if not args.ip:
        print("Please specify device IP with --ip")
        return

    dev = KelvinatorDevice(
        ip=args.ip,
        did=dev_info.did,
        mac=dev_info.mac,
        aes_key=dev_info.aes_key,
        password=dev_info.password,
    )

    params = {}
    if args.power_on:
        params['power'] = True
    elif args.power_off:
        params['power'] = False
    if args.mode:
        mode_map = {'cool': 0, 'heat': 1, 'auto': 2, 'fan': 3, 'dry': 4}
        params['mode'] = mode_map[args.mode]
    if args.temp is not None:
        params['temp'] = args.temp
    if args.fan:
        fan_map = {'auto': 0, 'low': 1, 'med': 2, 'high': 3}
        params['fan'] = fan_map[args.fan]
    if args.swing:
        swing_map = {'off': 0, 'vert': 1, 'horiz': 2, 'both': 3}
        params['swing'] = swing_map[args.swing]
    if args.sleep:
        params['sleep'] = True
    if args.turbo:
        params['turbo'] = True

    if not params:
        print("No control parameters specified. Use --help for options.")
        return

    state = ACState(**{**ACState().to_dict(), **params})

    print(f"Sending: {state}")
    with dev:
        dev.set_state(state)
        print("Control command sent successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kelvinator/Electrolux AC Controller"
    )
    parser.add_argument('-v', '--verbose', action='store_true')
    subparsers = parser.add_subparsers(dest='command')

    p = subparsers.add_parser('discover', help='Discover devices on LAN')
    p.add_argument('-t', '--timeout', type=float, default=3.0)
    p.add_argument('-o', '--output', default='discovered_devices.json')

    p = subparsers.add_parser('status', help='Query AC status')
    p.add_argument('-d', '--device-file', required=True)
    p.add_argument('-i', '--ip')

    p = subparsers.add_parser('control', help='Control the AC')
    p.add_argument('-d', '--device-file', required=True)
    p.add_argument('-i', '--ip')
    p.add_argument('--power-on', action='store_true')
    p.add_argument('--power-off', action='store_true')
    p.add_argument('--mode', choices=['cool', 'heat', 'auto', 'fan', 'dry'])
    p.add_argument('--temp', type=int)
    p.add_argument('--fan', choices=['auto', 'low', 'med', 'high'])
    p.add_argument('--swing', choices=['off', 'vert', 'horiz', 'both'])
    p.add_argument('--sleep', action='store_true')
    p.add_argument('--turbo', action='store_true')

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == 'discover':
        cmd_discover(args)
    elif args.command == 'status':
        cmd_status(args)
    elif args.command == 'control':
        cmd_control(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()

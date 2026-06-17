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


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S',
    )


def cmd_discover(args):
    print("Discovering devices on the local network...")
    devices = discover_devices(timeout=args.timeout)
    if not devices:
        print("No devices found.")
        return

    print(f"\nFound {len(devices)} device(s):")
    for d in devices:
        print(f"  IP: {d['ip']}")
        print(f"  MAC: {d['mac']}")
        print(f"  DID: {d['did']}")
        if d.get('name'):
            print(f"  Name: {d['name']}")
        print()

    if args.output:
        from .cloud import save_cached_devices
        save_cached_devices(devices, args.output)
        print(f"Saved to {args.output}")


def cmd_status(args):
    devices = load_cached_devices(args.device_file)
    if not devices:
        print("No devices found in config file.")
        return
    dev_info = devices[0]

    if not args.ip:
        print("Please specify device IP with --ip")
        return

    dev = KelvinatorDevice(
        ip=args.ip, did=dev_info.did, mac=dev_info.mac,
        aes_key=dev_info.aes_key, password=dev_info.password,
    )

    with dev:
        dev.authenticate()
        status = dev.get_status()
        print(f"Device: {dev_info.name}")
        print(f"Status: {status}")


def cmd_control(args):
    devices = load_cached_devices(args.device_file)
    if not devices:
        print("No devices found in config file.")
        return
    dev_info = devices[0]

    if not args.ip:
        print("Please specify device IP with --ip")
        return

    dev = KelvinatorDevice(
        ip=args.ip, did=dev_info.did, mac=dev_info.mac,
        aes_key=dev_info.aes_key, password=dev_info.password,
    )

    state = ACState()
    if args.power_on:
        state.power = True
    elif args.power_off:
        state.power = False
    if args.mode:
        mode_map = {'cool': 0, 'heat': 1, 'auto': 2, 'fan': 3, 'dry': 4}
        state.mode = mode_map.get(args.mode, 0)
    if args.temp:
        state.temp = args.temp
    if args.fan:
        fan_map = {'auto': 0, 'low': 1, 'med': 2, 'high': 3}
        state.fan = fan_map.get(args.fan, 0)
    if args.swing:
        swing_map = {'off': 0, 'vert': 1, 'horiz': 2, 'both': 3}
        state.swing = swing_map.get(args.swing, 0)
    if args.sleep:
        state.sleep = True
    if args.turbo:
        state.turbo = True

    print(f"Sending: {state}")
    with dev:
        dev.authenticate()
        dev.set_state(state)
        print("Control command sent.")


def main():
    parser = argparse.ArgumentParser(description="Kelvinator/Electrolux AC Controller")
    parser.add_argument('-v', '--verbose', action='store_true')
    subparsers = parser.add_subparsers(dest='command')

    p = subparsers.add_parser('discover', help='Discover devices')
    p.add_argument('-t', '--timeout', type=float, default=3.0)
    p.add_argument('-o', '--output', default='discovered_devices.json')

    p = subparsers.add_parser('status', help='Query status')
    p.add_argument('-d', '--device-file', required=True)
    p.add_argument('-i', '--ip')

    p = subparsers.add_parser('control', help='Control AC')
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

    commands = {
        'discover': cmd_discover,
        'status': cmd_status,
        'control': cmd_control,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()

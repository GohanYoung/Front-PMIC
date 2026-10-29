import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from drivers.aardvark_contorller import AardvarkI2C

WRITE_RETRY = 3
WRITE_RETRY_DELAY_MS = 10
SCAN_PROBE_BYTE = 0x00

def parse_hex_int(text):
    return int(text, 0)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Write ChargerIC register through Aardvark (without MUX)",
    )
    parser.add_argument("--port", type=int, default=0, help="Aardvark port index")
    parser.add_argument("--bitrate", type=int, default=100, help="I2C bitrate in kHz")
    parser.add_argument("--addr", type=parse_hex_int, default=0x33, help="ChargerIC 7-bit I2C address")
    parser.add_argument("--reg", type=parse_hex_int, default=0x15, help="register address")
    parser.add_argument("--data", type=parse_hex_int, default=0x55, help="register value to write")
    parser.add_argument("--readback", action="store_true", help="read back register after write")
    parser.add_argument("--scan-only", action="store_true", help="scan target address only")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.addr < 0x00 or args.addr > 0x7F:
        print("[TEST] --addr must be in 0x00~0x7F")
        return 2

    i2c = AardvarkI2C(
        port=args.port,
        bitrate=args.bitrate,
        debug=False,
        enable_pullup=True,
        enable_target_power=False,
    )

    reg = args.reg & 0xFF
    data = args.data & 0xFF

    print("=" * 60)
    print("[TEST] Aardvark -> ChargerIC register write (No MUX)")
    print(f"  Port    : {args.port}")
    print(f"  Bitrate : {args.bitrate} kHz")
    print(f"  Addr    : 0x{args.addr:02X}")
    print(f"  Reg     : 0x{reg:02X}")
    print(f"  Data    : 0x{data:02X}")
    print(f"  Retry   : {WRITE_RETRY} (delay={WRITE_RETRY_DELAY_MS}ms)")
    print(f"  Readback: {'ON' if args.readback else 'OFF'}")
    if args.scan_only:
        print(f"  Scan    : addr=0x{args.addr:02X} (probe=0x{SCAN_PROBE_BYTE:02X})")
    print("=" * 60)

    try:
        i2c.open()

        if args.scan_only:
            print("[TEST] Scanning I2C bus ...")
            found = i2c.scan_addresses(
                start_addr=args.addr,
                end_addr=args.addr,
                probe_byte=SCAN_PROBE_BYTE,
                retry=WRITE_RETRY,
                retry_delay_ms=WRITE_RETRY_DELAY_MS,
                on_found=lambda addr: print(f"  [FOUND] 0x{addr:02X}"),
            )
            if found:
                print("[TEST] Found addresses:", " ".join(f"0x{a:02X}" for a in found))
                return 0
            print("[TEST] No responsive address found in scan range")
            return 1

        i2c.write_with_retry(
            args.addr,
            [reg, data],
            retry=WRITE_RETRY,
            retry_delay_ms=WRITE_RETRY_DELAY_MS,
        )
        print(f"[TEST] PASS: wrote 0x{data:02X} to reg 0x{reg:02X} on 0x{args.addr:02X}")

        if args.readback:
            actual = i2c.read_byte(args.addr, reg)
            print(f"[TEST] READ: reg 0x{reg:02X} = 0x{actual:02X}")
        return 0
    except Exception as exc:
        print(f"[TEST] FAIL: {exc}")
        return 1
    finally:
        i2c.close()


if __name__ == "__main__":
    sys.exit(main())

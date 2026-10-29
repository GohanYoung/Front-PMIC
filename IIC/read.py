import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.charger_register_table import CHARGER_I2C_ADDR
from drivers.aardvark_contorller import AardvarkI2C
from drivers.tca9548a import TCA9548A

DEFAULT_PORT = 0
DEFAULT_BITRATE = 100
DEFAULT_MUX_ADDR = 0x70
DEFAULT_CHARGER_ADDR = CHARGER_I2C_ADDR
MUX_RETRY = 3
MUX_RETRY_DELAY_MS = 10
READ_RETRY = 2
RECOVER_REOPEN_DELAY_MS = 20
SCAN_PROBE_BYTE = 0x00


def parse_hex_int(text):
    return int(text, 0)


def parse_channel_list(text):
    raw = [x.strip() for x in str(text).split(",") if x.strip()]
    if not raw:
        return []

    channels = []
    seen = set()
    for item in raw:
        ch = int(item, 0)
        if not (0 <= ch <= 7):
            raise ValueError(f"channel out of range: {item}")
        if ch not in seen:
            channels.append(ch)
            seen.add(ch)
    return channels


def build_parser():
    parser = argparse.ArgumentParser(
        description="Read ChargerIC register via Aardvark -> MUX -> ChargerIC",
    )
    parser.add_argument("--reg", type=parse_hex_int, default=0x15, help="register address to read")
    parser.add_argument("--scan-only", action="store_true", help="scan target slave address on selected channel(s) only")
    parser.add_argument("--scan-addr", type=parse_hex_int, default=None, help=f"target 7-bit address to scan, default 0x{DEFAULT_CHARGER_ADDR:02X}")
    parser.add_argument("--channel", type=int, default=None, help="single MUX channel (0~7)")
    parser.add_argument("--channels", type=str, default="", help="comma-separated channels, e.g. 0,2,3")
    parser.add_argument("--csv-out", type=str, default="", help="output CSV path")
    return parser


def resolve_channels(args):
    if args.channel is not None and args.channels:
        raise ValueError("use either --channel or --channels, not both")

    if args.channel is not None:
        if not (0 <= args.channel <= 7):
            raise ValueError("--channel must be in 0~7")
        return [args.channel]

    if args.channels:
        parsed = parse_channel_list(args.channels)
        if not parsed:
            raise ValueError("--channels cannot be empty")
        return parsed

    return list(range(8))


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.scan_addr is not None and (args.scan_addr < 0x00 or args.scan_addr > 0x7F):
        print("[TEST] --scan-addr must be in 0x00~0x7F")
        return 2

    try:
        selected_channels = resolve_channels(args)
    except Exception as exc:
        print(f"[TEST] channel selection invalid: {exc}")
        return 2

    reg = args.reg & 0xFF
    scan_addr = (args.scan_addr if args.scan_addr is not None else DEFAULT_CHARGER_ADDR) & 0x7F
    i2c = AardvarkI2C(
        port=DEFAULT_PORT,
        bitrate=DEFAULT_BITRATE,
        debug=False,
        enable_pullup=True,
        enable_target_power=True,
    )

    print("=" * 60)
    print("[TEST] Aardvark -> MUX -> ChargerIC register read")
    print(f"  Port     : {DEFAULT_PORT}")
    print(f"  Bitrate  : {DEFAULT_BITRATE} kHz")
    print(f"  MUX Addr : 0x{DEFAULT_MUX_ADDR:02X}")
    print(f"  IC Addr  : 0x{DEFAULT_CHARGER_ADDR:02X}")
    if args.scan_only:
        print(f"  Scan Addr: 0x{scan_addr:02X}")
    else:
        print(f"  Reg      : 0x{reg:02X}")
    print(f"  Channels : {', '.join('CH' + str(ch) for ch in selected_channels)}")
    print("=" * 60)

    ok = 0
    fail = 0
    rows = []
    try:
        i2c.open()
        mux = TCA9548A(i2c, addr=DEFAULT_MUX_ADDR)
        for ch in selected_channels:
            try:
                if args.scan_only:
                    mux.select_channel_with_retry(ch, MUX_RETRY, MUX_RETRY_DELAY_MS)
                    found = i2c.scan_addresses(
                        start_addr=scan_addr,
                        end_addr=scan_addr,
                        probe_byte=SCAN_PROBE_BYTE,
                        retry=READ_RETRY,
                        retry_delay_ms=MUX_RETRY_DELAY_MS,
                    )
                    if scan_addr in found:
                        print(f"[TEST][CH{ch}] FOUND slave 0x{scan_addr:02X}")
                        rows.append(
                            {
                                "channel": ch,
                                "status": "PASS",
                                "reg": "",
                                "value": f"0x{scan_addr:02X}",
                                "error": "",
                            }
                        )
                        ok += 1
                    else:
                        print(f"[TEST][CH{ch}] NOT FOUND slave 0x{scan_addr:02X}")
                        rows.append(
                            {
                                "channel": ch,
                                "status": "FAIL",
                                "reg": "",
                                "value": f"0x{scan_addr:02X}",
                                "error": "not found",
                            }
                        )
                        fail += 1
                else:
                    value = mux.read_byte_with_channel_recovery(
                        channel=ch,
                        dev_addr=DEFAULT_CHARGER_ADDR,
                        reg=reg,
                        read_retry=READ_RETRY,
                        retry_delay_ms=MUX_RETRY_DELAY_MS,
                        recover_reopen_delay_ms=RECOVER_REOPEN_DELAY_MS,
                    )
                    print(f"[TEST][CH{ch}] READ reg 0x{reg:02X} = 0x{value:02X}")
                    rows.append(
                        {
                            "channel": ch,
                            "status": "PASS",
                            "reg": f"0x{reg:02X}",
                            "value": f"0x{value:02X}",
                            "error": "",
                        }
                    )
                    ok += 1
            except Exception as exc:
                print(f"[TEST][CH{ch}] FAIL: {exc}")
                rows.append(
                    {
                        "channel": ch,
                        "status": "FAIL",
                        "reg": f"0x{reg:02X}",
                        "value": "",
                        "error": str(exc),
                    }
                )
                fail += 1
            finally:
                try:
                    mux.disable_all()
                except Exception:
                    pass

        if args.csv_out:
            out_path = Path(args.csv_out)
            if not out_path.is_absolute():
                out_path = PROJECT_ROOT / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["channel", "status", "reg", "value", "error"],
                )
                writer.writeheader()
                writer.writerows(rows)
            print(f"[TEST] CSV saved: {out_path}")

        print("-" * 60)
        print(f"[TEST] Summary: {ok} pass, {fail} fail")
        if fail == 0:
            return 0
        return 1
    except Exception as exc:
        print(f"[TEST] FAIL: {exc}")
        return 1
    finally:
        i2c.close()


if __name__ == "__main__":
    sys.exit(main())

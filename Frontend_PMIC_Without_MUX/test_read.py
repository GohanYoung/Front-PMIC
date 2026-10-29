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

MUX_RETRY = 3
MUX_RETRY_DELAY_MS = 10
READ_RETRY = 2
RECOVER_REOPEN_DELAY_MS = 20


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
    parser.add_argument("--port", type=int, default=0, help="Aardvark port index")
    parser.add_argument("--bitrate", type=int, default=100, help="I2C bitrate in kHz")
    parser.add_argument("--mux-addr", type=parse_hex_int, default=0x70, help="TCA9548A 7-bit I2C address")
    parser.add_argument("--charger-addr", type=parse_hex_int, default=CHARGER_I2C_ADDR, help="ChargerIC 7-bit I2C address")
    parser.add_argument("--reg", type=parse_hex_int, default=0x15, help="register address to read")
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

    if args.charger_addr < 0x00 or args.charger_addr > 0x7F:
        print("[TEST] --charger-addr must be in 0x00~0x7F")
        return 2
    if args.mux_addr < 0x00 or args.mux_addr > 0x7F:
        print("[TEST] --mux-addr must be in 0x00~0x7F")
        return 2

    try:
        selected_channels = resolve_channels(args)
    except Exception as exc:
        print(f"[TEST] channel selection invalid: {exc}")
        return 2

    reg = args.reg & 0xFF
    i2c = AardvarkI2C(
        port=args.port,
        bitrate=args.bitrate,
        debug=False,
        enable_pullup=True,
        enable_target_power=False,
    )

    print("=" * 60)
    print("[TEST] Aardvark -> MUX -> ChargerIC register read")
    print(f"  Port     : {args.port}")
    print(f"  Bitrate  : {args.bitrate} kHz")
    print(f"  MUX Addr : 0x{args.mux_addr:02X}")
    print(f"  IC Addr  : 0x{args.charger_addr:02X}")
    print(f"  Reg      : 0x{reg:02X}")
    print(f"  Channels : {', '.join('CH' + str(ch) for ch in selected_channels)}")
    print("=" * 60)

    ok = 0
    fail = 0
    rows = []
    try:
        i2c.open()
        mux = TCA9548A(i2c, addr=args.mux_addr)
        for ch in selected_channels:
            try:
                value = mux.read_byte_with_channel_recovery(
                    channel=ch,
                    dev_addr=args.charger_addr,
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

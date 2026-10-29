import argparse
import csv
import re
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

WRITE_RETRY = 3
WRITE_RETRY_DELAY_MS = 10
SCAN_PROBE_BYTE = 0x00

MUX_RETRY = 3
MUX_RETRY_DELAY_MS = 10
READ_RETRY = 2
RECOVER_REOPEN_DELAY_MS = 20


def _safe_print(text):
    try:
        print(text)
    except UnicodeEncodeError:
        print(str(text).encode("ascii", "replace").decode("ascii"))


def parse_hex_int(text):
    return int(text, 0)


def parse_channel_list(text):
    parts = re.split(r"[\s,]+", str(text).strip())
    raw = [x.strip() for x in parts if x.strip()]
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


def parse_reg_list(text):
    parts = re.split(r"[\s,]+", str(text).strip())
    raw = [x.strip() for x in parts if x.strip()]
    if not raw:
        raise ValueError("--reg cannot be empty")

    regs = []
    seen = set()
    for item in raw:
        reg = int(item, 0)
        if not (0x00 <= reg <= 0xFF):
            raise ValueError(f"register out of range: {item}")
        if reg not in seen:
            regs.append(reg)
            seen.add(reg)
    return regs


def create_i2c():
    return AardvarkI2C(
        port=DEFAULT_PORT,
        bitrate=DEFAULT_BITRATE,
        debug=False,
        enable_pullup=True,
        enable_target_power=True,
    )


def resolve_read_channels(args):
    if args.channels:
        parsed = parse_channel_list(args.channels)
        if not parsed:
            raise ValueError("--channels cannot be empty")
        for ch in parsed:
            if ch > 5:
                raise ValueError("--channels only supports CH0~CH5 for this script")
        return parsed

    return list(range(6))


def run_write(args):
    if args.addr < 0x00 or args.addr > 0x7F:
        _safe_print("[TEST] --addr must be in 0x00~0x7F")
        return 2

    i2c = create_i2c()
    reg = args.reg & 0xFF
    data = args.data & 0xFF

    print("=" * 60)
    print("[TEST] Aardvark -> ChargerIC register write (No MUX)")
    print(f"  Port    : {DEFAULT_PORT}")
    print(f"  Bitrate : {DEFAULT_BITRATE} kHz")
    print(f"  Addr    : 0x{args.addr:02X}")
    print(f"  Reg     : 0x{reg:02X}")
    print(f"  Data    : 0x{data:02X}")
    print(f"  Retry   : {WRITE_RETRY} (delay={WRITE_RETRY_DELAY_MS}ms)")
    print(f"  Readback: {'ON' if args.readback else 'OFF'}")
    print("=" * 60)

    try:
        i2c.open()

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


def run_read(args):
    try:
        selected_channels = resolve_read_channels(args)
    except Exception as exc:
        _safe_print(f"[TEST] channel selection invalid: {exc}")
        return 2

    try:
        regs = parse_reg_list(args.reg)
    except Exception as exc:
        _safe_print(f"[TEST] register selection invalid: {exc}")
        return 2

    i2c = create_i2c()

    print("=" * 60)
    print("[TEST] Aardvark -> MUX -> ChargerIC register read")
    print(f"  Port     : {DEFAULT_PORT}")
    print(f"  Bitrate  : {DEFAULT_BITRATE} kHz")
    print(f"  MUX Addr : 0x{DEFAULT_MUX_ADDR:02X}")
    print(f"  IC Addr  : 0x{DEFAULT_CHARGER_ADDR:02X}")
    print(f"  Regs     : {', '.join(f'0x{r:02X}' for r in regs)}")
    print(f"  Channels : {', '.join('CH' + str(ch) for ch in selected_channels)}")
    print("=" * 60)

    ok = 0
    fail = 0
    try:
        i2c.open()
        mux = TCA9548A(i2c, addr=DEFAULT_MUX_ADDR)
        for ch in selected_channels:
            try:
                reg_values = []
                for reg in regs:
                    value = mux.read_byte_with_channel_recovery(
                        channel=ch,
                        dev_addr=DEFAULT_CHARGER_ADDR,
                        reg=reg,
                        read_retry=READ_RETRY,
                        retry_delay_ms=MUX_RETRY_DELAY_MS,
                        recover_reopen_delay_ms=RECOVER_REOPEN_DELAY_MS,
                    )
                    reg_values.append((reg, value))
                detail = ", ".join(f"0x{reg:02X}=0x{value:02X}" for reg, value in reg_values)
                _safe_print(f"[TEST][CH{ch}] PASS: {detail}")
                ok += 1
            except Exception:
                _safe_print(f"[TEST][CH{ch}] FAIL")
                fail += 1
            finally:
                try:
                    mux.disable_all()
                except Exception:
                    pass

        print("-" * 60)
        print(f"[TEST] Summary: {ok} pass, {fail} fail")
        if fail > 0:
            _safe_print("read failed, please power-cycle MUX")
            return 1
        return 0
    except Exception:
        _safe_print("[TEST] FAIL: read failed, please power-cycle MUX")
        return 1
    finally:
        i2c.close()


def run_scan(args):
    if args.addr < 0x00 or args.addr > 0x7F:
        _safe_print("[TEST] --addr must be in 0x00~0x7F")
        return 2

    i2c = create_i2c()
    target_addr = args.addr & 0x7F
    rows = []

    if args.no_mux:
        print("=" * 60)
        print("[TEST] Aardvark direct scan (No MUX)")
        print(f"  Port     : {DEFAULT_PORT}")
        print(f"  Bitrate  : {DEFAULT_BITRATE} kHz")
        print(f"  Scan Addr: 0x{target_addr:02X}")
        print("=" * 60)
        try:
            i2c.open()
            found = i2c.scan_addresses(
                start_addr=target_addr,
                end_addr=target_addr,
                probe_byte=SCAN_PROBE_BYTE,
                retry=WRITE_RETRY,
                retry_delay_ms=WRITE_RETRY_DELAY_MS,
            )
            if target_addr in found:
                _safe_print(f"[TEST] PASS: FOUND 0x{target_addr:02X}")
                return 0
            _safe_print(f"[TEST] FAIL: NOT FOUND 0x{target_addr:02X}")
            return 1
        except Exception:
            _safe_print("[TEST] FAIL: scan failed")
            return 1
        finally:
            i2c.close()

    try:
        selected_channels = resolve_read_channels(args)
    except Exception as exc:
        _safe_print(f"[TEST] channel selection invalid: {exc}")
        return 2

    print("=" * 60)
    print("[TEST] Aardvark -> MUX channel scan")
    print(f"  Port     : {DEFAULT_PORT}")
    print(f"  Bitrate  : {DEFAULT_BITRATE} kHz")
    print(f"  MUX Addr : 0x{DEFAULT_MUX_ADDR:02X}")
    print(f"  Scan Addr: 0x{target_addr:02X}")
    print(f"  Channels : {', '.join('CH' + str(ch) for ch in selected_channels)}")
    print("=" * 60)

    ok = 0
    fail = 0
    try:
        i2c.open()
        mux = TCA9548A(i2c, addr=DEFAULT_MUX_ADDR)
        for ch in selected_channels:
            try:
                mux.select_channel_with_retry(ch, MUX_RETRY, MUX_RETRY_DELAY_MS)
                found = i2c.scan_addresses(
                    start_addr=target_addr,
                    end_addr=target_addr,
                    probe_byte=SCAN_PROBE_BYTE,
                    retry=READ_RETRY,
                    retry_delay_ms=MUX_RETRY_DELAY_MS,
                )
                if target_addr in found:
                    _safe_print(f"[TEST][CH{ch}] PASS")
                    rows.append({"channel": ch, "status": "PASS", "address": f"0x{target_addr:02X}", "error": ""})
                    ok += 1
                else:
                    _safe_print(f"[TEST][CH{ch}] FAIL")
                    rows.append({"channel": ch, "status": "FAIL", "address": f"0x{target_addr:02X}", "error": "not found"})
                    fail += 1
            except Exception:
                _safe_print(f"[TEST][CH{ch}] FAIL")
                rows.append({"channel": ch, "status": "FAIL", "address": f"0x{target_addr:02X}", "error": "scan exception"})
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
                writer = csv.DictWriter(f, fieldnames=["channel", "status", "address", "error"])
                writer.writeheader()
                writer.writerows(rows)
            print(f"[TEST] CSV saved: {out_path}")

        print("-" * 60)
        print(f"[TEST] Summary: {ok} pass, {fail} fail")
        if fail > 0:
            _safe_print("scan failed, please power-cycle MUX")
            return 1
        return 0
    except Exception:
        _safe_print("[TEST] FAIL: scan failed")
        _safe_print("scan failed, please power-cycle MUX")
        return 1
    finally:
        i2c.close()


def build_parser():
    parser = argparse.ArgumentParser(
        description="Combined write(no MUX) and read(via MUX) tool",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    write_parser = subparsers.add_parser("write", help="write/register-readback without MUX")
    write_parser.add_argument("--addr", type=parse_hex_int, default=DEFAULT_CHARGER_ADDR, help="ChargerIC 7-bit I2C address")
    write_parser.add_argument("--reg", type=parse_hex_int, default=0x15, help="register address")
    write_parser.add_argument("--data", type=parse_hex_int, default=0x55, help="register value to write")
    write_parser.add_argument("--readback", action="store_true", help="read back register after write")
    write_parser.set_defaults(func=run_write)

    read_parser = subparsers.add_parser("read", help="read register via MUX CH0~CH5")
    read_parser.add_argument("--reg", type=str, default="0x15", help="register(s) to read, e.g. 0x15 or 0x15,0x16")
    read_parser.add_argument("--channels", type=str, default="", help="channels: single or comma-separated, e.g. 2 or 0,2,3")
    read_parser.set_defaults(func=run_read)

    scan_parser = subparsers.add_parser("scan", help="scan slave address (direct or via MUX CH0~CH5)")
    scan_parser.add_argument("--addr", type=parse_hex_int, default=DEFAULT_CHARGER_ADDR, help="target 7-bit address to scan")
    scan_parser.add_argument("--no-mux", action="store_true", help="scan directly without MUX")
    scan_parser.add_argument("--channel", type=int, default=None, help="single MUX channel (0~5)")
    scan_parser.add_argument("--channels", type=str, default="", help="comma-separated channels, e.g. 0,2,3")
    scan_parser.add_argument("--csv-out", type=str, default="", help="output CSV path (MUX scan)")
    scan_parser.set_defaults(func=run_scan)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

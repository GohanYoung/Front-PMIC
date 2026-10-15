import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.charger_register_table import REG_RW_SAFE_TABLE, REG_TEST_TABLE
from drivers.aardvark_contorller import AardvarkI2C
from drivers.tca9548a import TCA9548A


def parse_hex_int(text):
    return int(text, 0)


def run_mux_stability_test(mux, mux_channel, count, retry, retry_delay_ms):
    ok = 0
    fail = 0
    for idx in range(1, count + 1):
        try:
            mux.select_channel_with_retry(mux_channel, retry, retry_delay_ms)
            ok += 1
            print(f"  [PASS] MUX select {idx}/{count}")
        except Exception as exc:
            fail += 1
            print(f"  [FAIL] MUX select {idx}/{count}: {exc}")
    return ok, fail


def build_parser():
    parser = argparse.ArgumentParser(
        description="Aardvark Charger register read/write verify",
    )
    parser.add_argument("--port", type=int, default=0, help="Aardvark port index")
    parser.add_argument("--bitrate", type=int, default=400, help="I2C bitrate in kHz")
    parser.add_argument(
        "--addr",
        type=parse_hex_int,
        default=0x70,
        help="7-bit I2C device address, e.g. 0x70",
    )
    parser.add_argument(
        "--table-repeat",
        type=int,
        default=1,
        help="repeat count of whole REG_TEST_TABLE verification",
    )
    parser.add_argument(
        "--mode",
        choices=["ro", "rw", "raw"],
        default="ro",
        help="ro: reg read verify; rw: write then reg read; raw: direct read without reg pointer",
    )
    parser.add_argument("--raw-read-len", type=int, default=1, help="bytes to read in raw mode")
    parser.add_argument("--scan-only", action="store_true", help="scan I2C addresses only")
    parser.add_argument("--scan-start", type=parse_hex_int, default=0x08, help="scan start address")
    parser.add_argument("--scan-end", type=parse_hex_int, default=0x77, help="scan end address")
    parser.add_argument("--probe-byte", type=parse_hex_int, default=0x00, help="probe byte for address scan")
    parser.add_argument("--mux-addr", type=parse_hex_int, default=0x70, help="TCA9548A address")
    parser.add_argument("--mux-channel", type=int, default=None, help="optional TCA9548A channel 0~7")
    parser.add_argument("--mux-stress-count", type=int, default=0, help="run MUX select stability test N times")
    parser.add_argument("--retry", type=int, default=3, help="retry count for each write op")
    parser.add_argument("--retry-delay-ms", type=int, default=10, help="delay between retries in ms")
    parser.add_argument("--disable-pullup", action="store_true", help="disable Aardvark internal I2C pull-up")
    parser.add_argument("--enable-target-power", action="store_true", help="enable Aardvark target power output")
    parser.add_argument("--debug", action="store_true", help="enable I2C TX debug print")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.table_repeat <= 0:
        print("[TEST] --table-repeat must be > 0")
        return 2
    if args.scan_start < 0x00 or args.scan_end > 0x7F or args.scan_start > args.scan_end:
        print("[TEST] invalid scan range")
        return 2
    if args.retry <= 0:
        print("[TEST] --retry must be > 0")
        return 2
    if args.retry_delay_ms < 0:
        print("[TEST] --retry-delay-ms must be >= 0")
        return 2
    if args.mux_stress_count < 0:
        print("[TEST] --mux-stress-count must be >= 0")
        return 2
    if args.mux_stress_count > 0 and args.mux_channel is None:
        print("[TEST] --mux-stress-count requires --mux-channel")
        return 2
    if args.raw_read_len <= 0:
        print("[TEST] --raw-read-len must be > 0")
        return 2

    i2c = AardvarkI2C(
        port=args.port,
        bitrate=args.bitrate,
        debug=args.debug,
        enable_pullup=(not args.disable_pullup),
        enable_target_power=args.enable_target_power,
    )

    print("=" * 60)
    print("[TEST] Aardvark Charger Register R/W Verify")
    print(f"  Port    : {args.port}")
    print(f"  Bitrate : {args.bitrate} kHz")
    print(f"  Addr    : 0x{args.addr:02X}")
    print(f"  Mode    : {args.mode}")
    if args.mode == "raw":
        print(f"  RawLen  : {args.raw_read_len}")
    print(f"  Scan    : 0x{args.scan_start:02X}~0x{args.scan_end:02X}")
    print(f"  Pull-up : {'ON' if not args.disable_pullup else 'OFF'}")
    print(f"  TargetP : {'ON' if args.enable_target_power else 'OFF'}")
    print(f"  Retry   : {args.retry} (delay={args.retry_delay_ms}ms)")
    if args.mux_channel is not None:
        print(f"  MUX     : addr=0x{args.mux_addr:02X} ch={args.mux_channel}")
    if args.mux_stress_count > 0:
        print(f"  MUXTest : count={args.mux_stress_count}")
    active_entries = REG_RW_SAFE_TABLE if args.mode == "rw" else REG_TEST_TABLE
    print(f"  Entries : {len(active_entries)}")
    print(f"  Repeat  : {args.table_repeat}")
    print("=" * 60)

    try:
        i2c.open()
        mux = TCA9548A(i2c, addr=args.mux_addr)

        if args.mux_channel is not None and args.mux_stress_count == 0:
            print(f"[TEST] Selecting MUX ch{args.mux_channel} @ 0x{args.mux_addr:02X} ...")
            mux.select_channel_with_retry(args.mux_channel, args.retry, args.retry_delay_ms)
            print("[TEST] MUX channel selected")

        if args.mux_stress_count > 0:
            print(f"[TEST] Running MUX stability test ({args.mux_stress_count} times) ...")
            ok, fail = run_mux_stability_test(
                mux,
                args.mux_channel,
                args.mux_stress_count,
                args.retry,
                args.retry_delay_ms,
            )
            print(f"[TEST] MUX stability: {ok}/{args.mux_stress_count} pass, {fail} fail")
            return 0 if fail == 0 else 1

        print("[TEST] Scanning I2C bus ...")
        skip_addrs = set()
        if args.mux_channel is not None:
            # Avoid changing MUX state during scan by accidentally writing 0x00 to mux control reg.
            skip_addrs.add(args.mux_addr & 0x7F)
        found = i2c.scan_addresses(
            start_addr=args.scan_start,
            end_addr=args.scan_end,
            probe_byte=args.probe_byte,
            retry=args.retry,
            retry_delay_ms=args.retry_delay_ms,
            skip_addrs=skip_addrs,
            on_found=lambda addr: print(f"  [FOUND] 0x{addr:02X}"),
        )
        if found:
            print("[TEST] Found addresses:", " ".join(f"0x{a:02X}" for a in found))
        else:
            print("[TEST] No responsive address found in scan range")

        if args.scan_only:
            return 0 if found else 1

        if args.addr not in found:
            print(f"[TEST] WARN: target address 0x{args.addr:02X} was not found in scan")

        if args.mux_channel is not None:
            # Re-assert MUX route before register transactions.
            mux.select_channel_with_retry(args.mux_channel, args.retry, args.retry_delay_ms)

        total = 0
        passed = 0
        for loop_idx in range(1, args.table_repeat + 1):
            print(f"\n[TEST] Verify pass {loop_idx}/{args.table_repeat}")

            if args.mode == "raw":
                total += 1
                data = i2c.read_raw(args.addr, args.raw_read_len)
                passed += 1
                print("  [PASS] RAW READ:", " ".join(f"0x{b:02X}" for b in data))
                continue

            for reg, expected in active_entries:
                total += 1
                if args.mode == "rw":
                    i2c.write_with_retry(
                        args.addr,
                        [reg & 0xFF, expected & 0xFF],
                        args.retry,
                        args.retry_delay_ms,
                    )
                actual = i2c.read_byte(args.addr, reg & 0xFF)
                if actual == (expected & 0xFF):
                    passed += 1
                    if args.mode == "rw":
                        print(f"  [PASS] Reg=0x{reg:02X} W=0x{expected:02X} R=0x{actual:02X}")
                    else:
                        print(f"  [PASS] Reg=0x{reg:02X} E=0x{expected:02X} R=0x{actual:02X}")
                else:
                    if args.mode == "rw":
                        print(f"  [FAIL] Reg=0x{reg:02X} W=0x{expected:02X} R=0x{actual:02X}")
                    else:
                        print(f"  [FAIL] Reg=0x{reg:02X} E=0x{expected:02X} R=0x{actual:02X}")

        print("\n" + "=" * 60)
        print(f"[TEST] Summary: {passed}/{total} passed")
        if passed == total:
            print("[TEST] PASS: all registers verified")
            return 0

        print("[TEST] FAIL: register verify mismatch")
        return 1

    except NotImplementedError as exc:
        print(f"[TEST] FAIL: {exc}")
        print("[TEST] Hint: install Total Phase Aardvark SDK Python binding first.")
        return 3

    except Exception as exc:
        print(f"[TEST] FAIL: {exc}")
        return 1

    finally:
        i2c.close()


if __name__ == "__main__":
    sys.exit(main())

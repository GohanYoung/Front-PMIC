import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.charger_register_table import (
    CHARGER_I2C_ADDR,
    CHARGER_REGISTER_TABLE,
    WRITE_TEST_REG,
    WRITE_TEST_VALUE,
)
from drivers.aardvark_contorller import AardvarkI2C
from drivers.tca9548a import TCA9548A


def parse_hex_int(text):
    return int(text, 0)


def read_byte_with_retry(i2c, dev_addr, reg, retry, retry_delay_ms):
    last_exc = None
    for attempt in range(1, retry + 1):
        try:
            val = i2c.read_byte(dev_addr, reg)
            return val, attempt
        except Exception as exc:
            last_exc = exc
            if attempt < retry:
                time.sleep(retry_delay_ms / 1000.0)
    raise last_exc


def write_verify_with_retry(i2c, mux, args, reg, value):
    last_exc = None
    for attempt in range(1, args.write_verify_retry + 1):
        try:
            mux.select_channel_with_retry(args.mux_channel, args.retry, args.retry_delay_ms)
            before, before_attempt = read_byte_with_retry(
                i2c,
                args.charger_addr,
                reg,
                args.retry,
                args.retry_delay_ms,
            )

            i2c.write_with_retry(
                args.charger_addr,
                [reg & 0xFF, value & 0xFF],
                args.retry,
                args.retry_delay_ms,
            )

            if args.post_write_delay_ms > 0:
                time.sleep(args.post_write_delay_ms / 1000.0)

            mux.select_channel_with_retry(args.mux_channel, args.retry, args.retry_delay_ms)
            after, after_attempt = read_byte_with_retry(
                i2c,
                args.charger_addr,
                reg,
                args.retry,
                args.retry_delay_ms,
            )

            if after == (value & 0xFF):
                return {
                    "status": "PASS",
                    "before": before,
                    "after": after,
                    "verify_attempt": attempt,
                    "before_attempt": before_attempt,
                    "after_attempt": after_attempt,
                    "detail": "write success",
                }

            last_exc = RuntimeError(
                f"readback mismatch expected=0x{value:02X} actual=0x{after:02X}"
            )
        except Exception as exc:
            last_exc = exc

        if attempt < args.write_verify_retry:
            time.sleep(args.retry_delay_ms / 1000.0)

    raise last_exc


def print_table(title, headers, rows):
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(str(cell)))

    def fmt_row(row_vals):
        return "| " + " | ".join(str(v).ljust(widths[i]) for i, v in enumerate(row_vals)) + " |"

    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    print("\n" + title)
    print(sep)
    print(fmt_row(headers))
    print(sep)
    for row in rows:
        print(fmt_row(row))
    print(sep)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Aardvark -> MUX -> ChargerIC verification",
    )
    parser.add_argument("--port", type=int, default=0, help="Aardvark port index")
    parser.add_argument("--bitrate", type=int, default=100, help="I2C bitrate in kHz")
    parser.add_argument("--mux-addr", type=parse_hex_int, default=0x70, help="TCA9548A address")
    parser.add_argument("--mux-channel", type=int, default=0, help="TCA9548A channel 0~7")
    parser.add_argument("--charger-addr", type=parse_hex_int, default=CHARGER_I2C_ADDR, help="ChargerIC 7-bit I2C address")
    parser.add_argument("--detect-reg", type=parse_hex_int, default=0x15, help="read-only detect register for link probe")
    parser.add_argument("--retry", type=int, default=5, help="retry count for write operations")
    parser.add_argument("--retry-delay-ms", type=int, default=30, help="retry delay in ms")
    parser.add_argument("--write-verify-retry", type=int, default=3, help="retry count for step3 write-verify transaction")
    parser.add_argument("--post-write-delay-ms", type=int, default=20, help="delay after register write before readback")
    parser.add_argument("--disable-pullup", action="store_true", help="disable Aardvark internal pull-up")
    parser.add_argument("--enable-target-power", action="store_true", help="enable Aardvark target power")
    parser.add_argument("--debug", action="store_true", help="enable low-level I2C debug")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not (0 <= args.mux_channel <= 7):
        print("[TEST] --mux-channel must be in 0~7")
        return 2
    if args.retry <= 0:
        print("[TEST] --retry must be > 0")
        return 2
    if args.retry_delay_ms < 0:
        print("[TEST] --retry-delay-ms must be >= 0")
        return 2
    if args.write_verify_retry <= 0:
        print("[TEST] --write-verify-retry must be > 0")
        return 2
    if args.post_write_delay_ms < 0:
        print("[TEST] --post-write-delay-ms must be >= 0")
        return 2
    if not (0 <= args.detect_reg <= 0xFF):
        print("[TEST] --detect-reg must be in 0~255")
        return 2

    i2c = AardvarkI2C(
        port=args.port,
        bitrate=args.bitrate,
        debug=args.debug,
        enable_pullup=(not args.disable_pullup),
        enable_target_power=args.enable_target_power,
    )

    print("=" * 72)
    print("[TEST] Aardvark -> MUX -> ChargerIC Comprehensive Verification")
    print(f"  Port      : {args.port}")
    print(f"  Bitrate   : {args.bitrate} kHz")
    print(f"  MUX       : 0x{args.mux_addr:02X}, ch={args.mux_channel}")
    print(f"  ChargerIC : 0x{args.charger_addr:02X}")
    print(f"  DetectReg : 0x{args.detect_reg:02X}")
    print(f"  WriteTest : Reg=0x{WRITE_TEST_REG:02X}, Value=0x{WRITE_TEST_VALUE:02X}")
    print(f"  Retry     : {args.retry} (delay={args.retry_delay_ms}ms)")
    print(f"  WriteVRfy : {args.write_verify_retry} (post_delay={args.post_write_delay_ms}ms)")
    print(f"  Pull-up   : {'ON' if not args.disable_pullup else 'OFF'}")
    print(f"  TargetP   : {'ON' if args.enable_target_power else 'OFF'}")
    print("=" * 72)

    try:
        i2c.open()
        mux = TCA9548A(i2c, addr=args.mux_addr)

        # Step1: verify full link connectivity.
        print("\n[STEP1] Verify full link connectivity")
        link_rows = []

        try:
            mux.select_channel_with_retry(args.mux_channel, args.retry, args.retry_delay_ms)
            link_rows.append(["MUX Select", "PASS", f"MUX=0x{args.mux_addr:02X}, CH={args.mux_channel}"])
        except Exception as exc:
            link_rows.append(["MUX Select", "FAIL", str(exc)])
            print_table("[LINK RESULT]", ["Check", "Status", "Detail"], link_rows)
            return 1

        try:
            detect_val, detect_attempt = read_byte_with_retry(
                i2c,
                args.charger_addr,
                args.detect_reg & 0xFF,
                args.retry,
                args.retry_delay_ms,
            )
            link_rows.append(
                [
                    "Charger Detect",
                    "PASS",
                    (
                        f"Read 0x{args.detect_reg:02X}=0x{detect_val:02X} "
                        f"(attempt {detect_attempt}/{args.retry})"
                    ),
                ]
            )
        except Exception as exc:
            link_rows.append(["Charger Detect", "FAIL", str(exc)])
            print_table("[LINK RESULT]", ["Check", "Status", "Detail"], link_rows)
            return 1

        print_table("[LINK RESULT]", ["Check", "Status", "Detail"], link_rows)

        # Step2: read all registers in the provided table.
        print("\n[STEP2] Read all listed registers")
        read_rows = []
        read_fail = 0
        for reg in CHARGER_REGISTER_TABLE:
            addr = reg["addr"] & 0xFF
            try:
                mux.select_channel_with_retry(args.mux_channel, args.retry, args.retry_delay_ms)
                value, attempt = read_byte_with_retry(
                    i2c,
                    args.charger_addr,
                    addr,
                    args.retry,
                    args.retry_delay_ms,
                )
                read_rows.append([
                    f"0x{addr:02X}",
                    reg["name"],
                    reg["reg_type"],
                    reg["default"],
                    reg["recommend"],
                    f"0x{value:02X}",
                    "PASS",
                    f"attempt {attempt}/{args.retry}",
                ])
            except Exception as exc:
                read_fail += 1
                read_rows.append([
                    f"0x{addr:02X}",
                    reg["name"],
                    reg["reg_type"],
                    reg["default"],
                    reg["recommend"],
                    "--",
                    "FAIL",
                    str(exc),
                ])

        print_table(
            "[REGISTER READ RESULT]",
            ["Addr", "Register", "Type", "Default", "Recommend", "Read", "Status", "Detail"],
            read_rows,
        )

        if read_fail > 0:
            print(f"[TEST] WARN: register read has {read_fail} failure(s), continue to Step3 write test")

        # Step3: write 0x09 = 0x48 and read back.
        print("\n[STEP3] Write test register and verify readback")
        write_rows = []
        try:
            wr = write_verify_with_retry(
                i2c,
                mux,
                args,
                WRITE_TEST_REG,
                WRITE_TEST_VALUE,
            )
            write_rows.append([
                f"0x{WRITE_TEST_REG:02X}",
                f"0x{wr['before']:02X}",
                f"0x{WRITE_TEST_VALUE:02X}",
                f"0x{wr['after']:02X}",
                wr["status"],
                (
                    f"verify_attempt={wr['verify_attempt']}/{args.write_verify_retry}, "
                    f"before_attempt={wr['before_attempt']}, after_attempt={wr['after_attempt']}, "
                    f"{wr['detail']}"
                ),
            ])
        except Exception as exc:
            write_rows.append([
                f"0x{WRITE_TEST_REG:02X}",
                "--",
                f"0x{WRITE_TEST_VALUE:02X}",
                "--",
                "FAIL",
                str(exc),
            ])

        print_table(
            "[WRITE VERIFY RESULT]",
            ["Reg", "Before", "Write", "Readback", "Status", "Detail"],
            write_rows,
        )

        if read_fail > 0 and write_rows[0][4] == "PASS":
            print("[TEST] PARTIAL: link and write passed, but some register reads failed")
            return 1

        if write_rows[0][4] != "PASS":
            print("[TEST] FAIL: write verification failed")
            return 1

        print("[TEST] PASS: link/read/write checks all passed")
        return 0

    except Exception as exc:
        print(f"[TEST] FAIL: {exc}")
        return 1

    finally:
        i2c.close()


if __name__ == "__main__":
    sys.exit(main())

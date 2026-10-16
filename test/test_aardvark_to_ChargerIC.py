import argparse
import sys
import time
from datetime import datetime
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


def parse_channel_list(text):
    if text is None:
        return []
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


def trace(enabled, message, level="INFO"):
    if enabled:
        print(f"[TRACE][{level}] {message}")


def export_excel_result(excel_path, args, link_rows, read_rows, write_rows, final_status):
    try:
        from openpyxl import Workbook
    except ImportError:
        print("[TEST] WARN: openpyxl is not installed, skip Excel export")
        return

    out_path = Path(excel_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "register_values"

    ws.append(["Field", "Value"])
    ws.append(["GeneratedAt", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    ws.append(["FinalStatus", final_status])

    aardvark_connected = any(r[0] == "Aardvark Open" and r[1] == "PASS" for r in link_rows)
    mux_connected = any(r[0] == "Aardvark->MUX" and r[1] == "PASS" for r in link_rows)
    selected_rows = [r for r in link_rows if r[0] == "Channel Selected" and str(r[3]).startswith("CH")]
    ch_pass = [r for r in selected_rows if r[1] == "PASS"]
    ch_skip = [r for r in selected_rows if r[1] == "SKIP"]
    ch_fail = [r for r in selected_rows if r[1] == "FAIL"]
    selected_channels = ", ".join(r[3] for r in selected_rows) if selected_rows else "NONE"
    connected_channels = ", ".join(r[3] for r in ch_pass) if ch_pass else "NONE"

    ws.append(["AardvarkConnected", "PASS" if aardvark_connected else "FAIL"])
    ws.append(["MuxConnected", "PASS" if mux_connected else "FAIL"])
    ws.append(["SelectedChannels", selected_channels])
    ws.append(["ConnectedChannels", connected_channels])
    ws.append(["ChannelDetectPassCount", str(len(ch_pass))])
    ws.append(["ChannelDetectSkipCount", str(len(ch_skip))])
    ws.append(["ChannelDetectFailCount", str(len(ch_fail))])

    ws.append(["Port", args.port])
    ws.append(["BitrateKHz", args.bitrate])
    ws.append(["MuxAddr", f"0x{args.mux_addr:02X}"])
    ws.append(["ScanMode", "AUTO(CH0~CH7)"])
    ws.append(["ChargerAddr", f"0x{args.charger_addr:02X}"])
    ws.append([])

    ws.append([
        "Section",
        "Item",
        "Channel",
        "Addr",
        "Register",
        "Type",
        "Default",
        "Recommend",
        "ReadValue",
        "WriteValue",
        "ReadbackValue",
        "Status",
        "Detail",
    ])

    for row in link_rows:
        ws.append([
            "LINK",
            row[0],
            row[3],
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            row[1],
            row[2],
        ])

    for row in read_rows:
        ws.append([
            "READ",
            "",
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            "",
            "",
            row[7],
            row[8],
        ])

    for row in write_rows:
        ws.append([
            "WRITE_VERIFY",
            "",
            row[0],
            row[1],
            "WRITE_TEST_REG",
            "",
            "",
            "",
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
        ])

    wb.save(out_path)
    print(f"[TEST] Excel saved: {out_path}")


def read_byte_with_retry(i2c, dev_addr, reg, retry, retry_delay_ms, debug=False, scope=""):
    last_exc = None
    for attempt in range(1, retry + 1):
        try:
            trace(
                debug,
                f"{scope}read attempt {attempt}/{retry} addr=0x{dev_addr:02X} reg=0x{reg:02X}",
            )
            val = i2c.read_byte(dev_addr, reg)
            trace(
                debug,
                f"{scope}read success attempt {attempt}/{retry} addr=0x{dev_addr:02X} reg=0x{reg:02X} val=0x{val:02X}",
            )
            return val, attempt
        except Exception as exc:
            last_exc = exc
            trace(
                debug,
                f"{scope}read failed attempt {attempt}/{retry} addr=0x{dev_addr:02X} reg=0x{reg:02X} err={exc}",
                level="WARN",
            )
            if attempt < retry:
                trace(debug, f"{scope}read retry sleep {retry_delay_ms}ms")
                time.sleep(retry_delay_ms / 1000.0)
    raise last_exc


def safe_disable_all(mux, retry, retry_delay_ms, debug=False, scope=""):
    last_exc = None
    for attempt in range(1, retry + 1):
        try:
            mux.disable_all()
            trace(debug, f"{scope}mux disable_all success attempt {attempt}/{retry}")
            return
        except Exception as exc:
            last_exc = exc
            trace(
                debug,
                f"{scope}mux disable_all failed attempt {attempt}/{retry} err={exc}",
                level="WARN",
            )
            if attempt < retry:
                time.sleep(retry_delay_ms / 1000.0)
    raise last_exc


def recover_bus(i2c, mux, args, reason):
    trace(args.debug, f"recover start reason={reason}", level="WARN")
    try:
        safe_disable_all(mux, args.retry, args.retry_delay_ms, args.debug, scope="recover ")
    except Exception as exc:
        trace(args.debug, f"recover disable_all failed err={exc}", level="WARN")

    time.sleep(max(args.retry_delay_ms, 20) / 1000.0)

    try:
        i2c.close()
    except Exception as exc:
        trace(args.debug, f"recover close failed err={exc}", level="WARN")

    time.sleep(max(args.retry_delay_ms, 20) / 1000.0)
    i2c.open()
    trace(args.debug, "recover reopen done", level="WARN")


def is_bus_fault(exc):
    msg = str(exc)
    # Bus-level faults on MUX side usually indicate SDA/SCL stuck.
    return (
        "Addr=0x70" in msg
        or "Aardvark not opened" in msg
        or "arbitration" in msg.lower()
        or "bus" in msg.lower()
    )


def write_verify_with_retry(i2c, mux, args, mux_channel, reg, value):
    last_exc = None
    for attempt in range(1, args.write_verify_retry + 1):
        try:
            trace(
                args.debug,
                (
                    f"write-verify attempt {attempt}/{args.write_verify_retry} "
                    f"target ch={mux_channel} addr=0x{args.charger_addr:02X} "
                    f"reg=0x{reg:02X} value=0x{value:02X}"
                ),
            )
            mux.select_channel_with_retry(mux_channel, args.retry, args.retry_delay_ms)
            before, before_attempt = read_byte_with_retry(
                i2c,
                args.charger_addr,
                reg,
                args.retry,
                args.retry_delay_ms,
                debug=args.debug,
                scope=f"ch{mux_channel} before-write ",
            )

            trace(
                args.debug,
                (
                    f"write tx ch={mux_channel} addr=0x{args.charger_addr:02X} "
                    f"payload=[0x{reg & 0xFF:02X}, 0x{value & 0xFF:02X}]"
                ),
            )
            i2c.write_with_retry(
                args.charger_addr,
                [reg & 0xFF, value & 0xFF],
                args.retry,
                args.retry_delay_ms,
            )

            if args.post_write_delay_ms > 0:
                time.sleep(args.post_write_delay_ms / 1000.0)

            mux.select_channel_with_retry(mux_channel, args.retry, args.retry_delay_ms)
            after, after_attempt = read_byte_with_retry(
                i2c,
                args.charger_addr,
                reg,
                args.retry,
                args.retry_delay_ms,
                debug=args.debug,
                scope=f"ch{mux_channel} after-write ",
            )

            if after == (value & 0xFF):
                trace(
                    args.debug,
                    (
                        f"write-verify pass attempt {attempt}/{args.write_verify_retry} "
                        f"expected=0x{value:02X} actual=0x{after:02X}"
                    ),
                )
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
            trace(
                args.debug,
                (
                    f"write-verify mismatch attempt {attempt}/{args.write_verify_retry} "
                    f"expected=0x{value:02X} actual=0x{after:02X}"
                ),
                level="WARN",
            )
        except Exception as exc:
            last_exc = exc
            trace(
                args.debug,
                f"write-verify failed attempt {attempt}/{args.write_verify_retry} err={exc}",
                level="ERROR",
            )
            if is_bus_fault(exc):
                try:
                    recover_bus(i2c, mux, args, f"write-verify ch{mux_channel}")
                except Exception as recover_exc:
                    trace(args.debug, f"recover failed err={recover_exc}", level="ERROR")

        if attempt < args.write_verify_retry:
            trace(args.debug, f"write-verify retry sleep {args.retry_delay_ms}ms")
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
    parser.add_argument(
        "--channels",
        type=str,
        required=True,
        help="comma-separated MUX channels, e.g. 0,2,3",
    )
    parser.add_argument("--charger-addr", type=parse_hex_int, default=CHARGER_I2C_ADDR, help="ChargerIC 7-bit I2C address")
    parser.add_argument("--retry", type=int, default=5, help="retry count for write operations")
    parser.add_argument("--retry-delay-ms", type=int, default=30, help="retry delay in ms")
    parser.add_argument("--write-verify-retry", type=int, default=3, help="retry count for step3 write-verify transaction")
    parser.add_argument("--post-write-delay-ms", type=int, default=20, help="delay after register write before readback")
    parser.add_argument("--disable-pullup", action="store_true", help="disable Aardvark internal pull-up")
    parser.add_argument("--enable-target-power", action="store_true", help="enable Aardvark target power")
    parser.add_argument("--debug", action="store_true", help="enable low-level I2C debug")
    parser.add_argument("--excel-out", type=str, default="", help="output excel path (.xlsx)")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_out = args.excel_out.strip() if args.excel_out else ""
    if not excel_out:
        excel_out = str(PROJECT_ROOT / "test_results" / f"chargeric_result_{run_ts}.xlsx")

    link_rows = []
    read_rows = []
    write_rows = []
    final_status = "FAIL"

    try:
        selected_channels = parse_channel_list(args.channels)
    except Exception as exc:
        print(f"[TEST] --channels invalid: {exc}")
        return 2
    if not selected_channels:
        print("[TEST] --channels cannot be empty")
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
    print(f"  MUX       : 0x{args.mux_addr:02X}")
    print(f"  Channels  : {', '.join('CH' + str(ch) for ch in selected_channels)}")
    print(f"  ChargerIC : 0x{args.charger_addr:02X}")
    print(f"  WriteTest : Reg=0x{WRITE_TEST_REG:02X}, Value=0x{WRITE_TEST_VALUE:02X}")
    print(f"  Retry     : {args.retry} (delay={args.retry_delay_ms}ms)")
    print(f"  WriteVRfy : {args.write_verify_retry} (post_delay={args.post_write_delay_ms}ms)")
    print(f"  Pull-up   : {'ON' if not args.disable_pullup else 'OFF'}")
    print(f"  TargetP   : {'ON' if args.enable_target_power else 'OFF'}")
    print("=" * 72)

    try:
        i2c.open()
        link_rows.append([
            "Aardvark Open",
            "PASS",
            f"Port={args.port}, Bitrate={args.bitrate}kHz",
            "GLOBAL",
        ])
        mux = TCA9548A(i2c, addr=args.mux_addr)

        try:
            safe_disable_all(mux, args.retry, args.retry_delay_ms, args.debug, scope="startup ")
            link_rows.append([
                "Aardvark->MUX",
                "PASS",
                f"MUX control write ACK at 0x{args.mux_addr:02X}",
                "GLOBAL",
            ])
        except Exception as exc:
            link_rows.append([
                "Aardvark->MUX",
                "FAIL",
                str(exc),
                "GLOBAL",
            ])
            for channel in range(8):
                link_rows.append([
                    "Charger Detect",
                    "SKIP",
                    "scan not executed because Aardvark->MUX link failed",
                    f"CH{channel}",
                ])
            print_table("[LINK RESULT]", ["Check", "Status", "Detail", "Channel"], link_rows)
            final_status = "FAIL"
            return 1

        print("\n[STEP1] Verify link and selected channels")
        connected_channels = []
        for channel in selected_channels:
            try:
                mux.select_channel_with_retry(channel, args.retry, args.retry_delay_ms)
                connected_channels.append(channel)
                link_rows.append([
                    "Channel Selected",
                    "PASS",
                    "MUX channel selectable",
                    f"CH{channel}",
                ])
            except Exception as exc:
                link_rows.append([
                    "Channel Selected",
                    "FAIL",
                    str(exc),
                    f"CH{channel}",
                ])
                if is_bus_fault(exc):
                    try:
                        recover_bus(i2c, mux, args, f"select ch{channel}")
                    except Exception as recover_exc:
                        trace(args.debug, f"recover failed err={recover_exc}", level="ERROR")

        print_table("[LINK RESULT]", ["Check", "Status", "Detail", "Channel"], link_rows)

        if not connected_channels:
            print("[TEST] SKIP: no selectable channel, skip register read/write")
            final_status = "SKIP"
            return 0

        print(f"[TEST] Selected channels active: {', '.join(f'CH{ch}' for ch in connected_channels)}")

        print("\n[STEP2] Read all listed registers on detected channels")
        read_fail = 0
        for channel in connected_channels:
            for reg in CHARGER_REGISTER_TABLE:
                addr = reg["addr"] & 0xFF
                try:
                    trace(
                        args.debug,
                        f"step2 ch{channel} read register start addr=0x{addr:02X} name={reg['name']}",
                    )
                    mux.select_channel_with_retry(channel, args.retry, args.retry_delay_ms)
                    value, attempt = read_byte_with_retry(
                        i2c,
                        args.charger_addr,
                        addr,
                        args.retry,
                        args.retry_delay_ms,
                        debug=args.debug,
                        scope=f"step2 ch{channel} ",
                    )
                    read_rows.append([
                        f"CH{channel}",
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
                    trace(
                        args.debug,
                        f"step2 ch{channel} read register fail addr=0x{addr:02X} name={reg['name']} err={exc}",
                        level="WARN",
                    )
                    read_fail += 1
                    read_rows.append([
                        f"CH{channel}",
                        f"0x{addr:02X}",
                        reg["name"],
                        reg["reg_type"],
                        reg["default"],
                        reg["recommend"],
                        "--",
                        "FAIL",
                        str(exc),
                    ])
                    if is_bus_fault(exc):
                        try:
                            recover_bus(i2c, mux, args, f"step2 ch{channel} addr=0x{addr:02X}")
                        except Exception as recover_exc:
                            trace(args.debug, f"recover failed err={recover_exc}", level="ERROR")

        print_table(
            "[REGISTER READ RESULT]",
            ["Channel", "Addr", "Register", "Type", "Default", "Recommend", "Read", "Status", "Detail"],
            read_rows,
        )

        if read_fail > 0:
            print(f"[TEST] WARN: register read has {read_fail} failure(s), continue to Step3 write test")

        print("\n[STEP3] Write test register and verify readback on detected channels")
        write_fail = 0
        for channel in connected_channels:
            try:
                wr = write_verify_with_retry(
                    i2c,
                    mux,
                    args,
                    channel,
                    WRITE_TEST_REG,
                    WRITE_TEST_VALUE,
                )
                write_rows.append([
                    f"CH{channel}",
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
                write_fail += 1
                write_rows.append([
                    f"CH{channel}",
                    f"0x{WRITE_TEST_REG:02X}",
                    "--",
                    f"0x{WRITE_TEST_VALUE:02X}",
                    "--",
                    "FAIL",
                    str(exc),
                ])

        print_table(
            "[WRITE VERIFY RESULT]",
            ["Channel", "Reg", "Before", "Write", "Readback", "Status", "Detail"],
            write_rows,
        )

        if read_fail > 0 and write_fail == 0:
            print("[TEST] PARTIAL: all detected channels write passed, but some register reads failed")
            final_status = "PARTIAL"
            return 1

        if write_fail > 0:
            print(f"[TEST] FAIL: write verification failed on {write_fail} channel(s)")
            final_status = "FAIL"
            return 1

        print("[TEST] PASS: link/read/write checks all passed")
        final_status = "PASS"
        return 0

    except Exception as exc:
        if not link_rows:
            link_rows.append(["Aardvark Open", "FAIL", str(exc), "GLOBAL"])
        print(f"[TEST] FAIL: {exc}")
        final_status = "FAIL"
        return 1

    finally:
        try:
            safe_disable_all(mux, args.retry, args.retry_delay_ms, args.debug, scope="final ")
        except Exception:
            pass
        export_excel_result(excel_out, args, link_rows, read_rows, write_rows, final_status)
        i2c.close()


if __name__ == "__main__":
    sys.exit(main())

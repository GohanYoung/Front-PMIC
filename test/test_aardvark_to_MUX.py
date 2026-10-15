import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from drivers.aardvark_contorller import AardvarkI2C
from drivers.tca9548a import TCA9548A


def parse_hex_int(text):
    return int(text, 0)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Aardvark -> TCA9548A(MUX) link test",
    )
    parser.add_argument("--port", type=int, default=0, help="Aardvark port index")
    parser.add_argument("--bitrate", type=int, default=100, help="I2C bitrate in kHz")
    parser.add_argument("--mux-addr", type=parse_hex_int, default=0x70, help="TCA9548A 7-bit address")
    parser.add_argument("--probe-byte", type=parse_hex_int, default=0x00, help="probe byte for address detect")
    parser.add_argument("--retry", type=int, default=5, help="retry count for each bus write")
    parser.add_argument("--retry-delay-ms", type=int, default=30, help="delay between retries in ms")
    parser.add_argument("--disable-pullup", action="store_true", help="disable Aardvark internal pull-up")
    parser.add_argument("--enable-target-power", action="store_true", help="enable Aardvark target power")
    parser.add_argument("--channel", type=int, default=0, help="test channel index 0~7")
    parser.add_argument("--stress-count", type=int, default=10, help="repeat channel select count")
    parser.add_argument("--debug", action="store_true", help="enable low-level TX/RX debug")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.retry <= 0:
        print("[TEST] --retry must be > 0")
        return 2
    if args.retry_delay_ms < 0:
        print("[TEST] --retry-delay-ms must be >= 0")
        return 2
    if not (0 <= args.channel <= 7):
        print("[TEST] --channel must be in 0~7")
        return 2
    if args.stress_count <= 0:
        print("[TEST] --stress-count must be > 0")
        return 2

    i2c = AardvarkI2C(
        port=args.port,
        bitrate=args.bitrate,
        debug=args.debug,
        enable_pullup=(not args.disable_pullup),
        enable_target_power=args.enable_target_power,
    )

    print("=" * 60)
    print("[TEST] Aardvark -> MUX Link Test")
    print(f"  Port    : {args.port}")
    print(f"  Bitrate : {args.bitrate} kHz")
    print(f"  MUX Addr: 0x{args.mux_addr:02X}")
    print(f"  Channel : {args.channel}")
    print(f"  Stress  : {args.stress_count}")
    print(f"  Retry   : {args.retry} (delay={args.retry_delay_ms}ms)")
    print(f"  Pull-up : {'ON' if not args.disable_pullup else 'OFF'}")
    print(f"  TargetP : {'ON' if args.enable_target_power else 'OFF'}")
    print("=" * 60)

    try:
        i2c.open()
        mux = TCA9548A(i2c, addr=args.mux_addr)

        print("[TEST] Step1: detect MUX address ...")
        found = i2c.scan_addresses(
            start_addr=args.mux_addr,
            end_addr=args.mux_addr,
            probe_byte=args.probe_byte,
            retry=args.retry,
            retry_delay_ms=args.retry_delay_ms,
            on_found=lambda addr: print(f"  [FOUND] 0x{addr:02X}"),
        )
        if args.mux_addr not in found:
            print("[TEST] FAIL: MUX address not detected")
            return 1

        print("[TEST] Step2: write disable-all (0x00) ...")
        i2c.write_with_retry(args.mux_addr, [0x00], args.retry, args.retry_delay_ms)
        print("  [PASS] disable-all write ACK")

        print(f"[TEST] Step3: select channel {args.channel} stress test ...")
        ok = 0
        fail = 0
        for idx in range(1, args.stress_count + 1):
            try:
                mux.select_channel_with_retry(args.channel, args.retry, args.retry_delay_ms)
                ok += 1
                print(f"  [PASS] select {idx}/{args.stress_count}")
            except Exception as exc:
                fail += 1
                print(f"  [FAIL] select {idx}/{args.stress_count}: {exc}")

        print("\n" + "=" * 60)
        print(f"[TEST] Summary: {ok}/{args.stress_count} pass, {fail} fail")
        if fail == 0:
            print("[TEST] PASS: Aardvark -> MUX path is healthy")
            return 0

        print("[TEST] FAIL: Aardvark -> MUX path is unstable")
        return 1

    except Exception as exc:
        print(f"[TEST] FAIL: {exc}")
        return 1

    finally:
        i2c.close()


if __name__ == "__main__":
    sys.exit(main())

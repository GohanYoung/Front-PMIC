import sys
import time
import threading

from drivers.power_controller import PowerController
from sequence.power_on_sequence import PowerOnSequence


PSU_PORT = "COM4"
PSU_BAUD = 19200
PSU_TIMEOUT = 1


def check(condition, pass_msg, fail_msg):
    if condition:
        print(f"  [PASS] {pass_msg}")
        return True
    print(f"  [FAIL] {fail_msg}")
    return False


def main():
    print("=" * 50)
    print("  Power-On Sequence Test (parallel)")
    print(f"  Port: {PSU_PORT}  Baud: {PSU_BAUD}")
    print("=" * 50)

    psu = PowerController(port=PSU_PORT, baudrate=PSU_BAUD, timeout=PSU_TIMEOUT)
    seq = PowerOnSequence(psu)
    graceful = True

    try:
        psu.connect()
        print(f"[PSU] {psu.identify()}")
        psu.configure_protection()

        t0 = time.time()
        errors = {}

        def _ramp_worker(target_fn, name):
            try:
                target_fn()
            except Exception as e:
                errors[name] = e

        threads = [
            threading.Thread(target=_ramp_worker,
                             args=(seq.enable_5v, "CH5V")),
            threading.Thread(target=_ramp_worker,
                             args=(lambda: seq.vin_to_17v(), "VIN")),
            threading.Thread(target=_ramp_worker,
                             args=(seq.vcap_to_35v, "VCAP")),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        elapsed = time.time() - t0

        if errors:
            graceful = False
            print(f"\n  Ramp errors: {errors}")
            return 1

        print(f"\n  All channels ramped up in {elapsed:.1f}s")

        results = []
        results.append(check(
            abs(psu.measure_voltage(psu.CH_5V) - 5.0) <= 0.1,
            f"CH5V = {psu.measure_voltage(psu.CH_5V):.2f}V",
            "CH5V wrong"))
        results.append(check(
            abs(psu.measure_voltage(psu.CH_VIN) - 17.0) <= 0.1,
            f"VIN = {psu.measure_voltage(psu.CH_VIN):.2f}V",
            "VIN wrong"))
        results.append(check(
            abs(psu.measure_voltage(psu.CH_VCAP) - 35.0) <= 0.15,
            f"VCAP = {psu.measure_voltage(psu.CH_VCAP):.2f}V",
            "VCAP wrong"))

        ok = sum(results)
        total = len(results)
        print(f"\n  Result: {ok}/{total} PASS")

    except KeyboardInterrupt:
        print("\n[!] Ctrl+C")
        graceful = False
    except Exception as e:
        print(f"  [FAIL] {e}")
        graceful = False

    finally:
        if graceful:
            try:
                print("\n[TEST] Parallel shutdown")
                down_errors = {}

                def _down_worker(channel, name):
                    try:
                        seq.shutdown_channel(channel)
                    except Exception as e:
                        down_errors[name] = e

                t_down = [
                    threading.Thread(target=_down_worker,
                                     args=(psu.CH_VIN, "VIN")),
                    threading.Thread(target=_down_worker,
                                     args=(psu.CH_VCAP, "VCAP")),
                    threading.Thread(target=_down_worker,
                                     args=(psu.CH_5V, "CH5V")),
                ]
                for t in t_down:
                    t.start()
                for t in t_down:
                    t.join()

                if down_errors:
                    print(f"  Shutdown errors: {down_errors}")
                    seq.emergency_stop()
                else:
                    seq.global_output_off()
                    print("  All channels 0V & OUTP OFF")
            except Exception as e:
                print(f"  Graceful shutdown failed: {e}")
                seq.emergency_stop()
        else:
            seq.emergency_stop()
        psu.disconnect()
        print("\n[TEST] Done")

    return 0


if __name__ == "__main__":
    sys.exit(main())
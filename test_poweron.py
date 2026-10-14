import sys

from drivers.aardvark_contorller import AardvarkI2C
from drivers.power_controller import PowerController
from drivers.tca9548a import TCA9548A


PSU_PORT = "COM5"
PSU_BAUDRATE = 19200

STEP = 2.0
INTERVAL = 1.0
STABLE_ON = 0.3
STABLE_OFF = 0.2


def check_voltage(power, channel, expected, tol):
    actual = power.measure_voltage(channel)
    if abs(actual - expected) <= tol:
        print(f"  [PASS] CH{channel}={actual:.3f}V (target={expected}V)")
        return True
    print(f"  [FAIL] CH{channel}={actual:.3f}V (target={expected}V)")
    return False


def emergency_stop(power):
    print("[TEST] EMERGENCY STOP")
    for ch in [PowerController.CH_VIN, PowerController.CH_VCAP, PowerController.CH_VEXT]:
        try:
            power.select_channel(ch)
            power.write("VOLT 0")
            power.write("OUTP OFF")
        except Exception:
            pass
    power.current_channel = None


def main():
    print("=" * 50)
    print("[TEST] HTOL Power Sequence Test (main style, no register write)")
    print("=" * 50)

    i2c = AardvarkI2C(port=0, bitrate=400)
    power = PowerController(port=PSU_PORT, baudrate=PSU_BAUDRATE)
    mux = None
    need_emergency = False

    try:
        print("[TEST] Opening Aardvark I2C (port=0, 400kbps)...")
        i2c.open()
        print("[TEST] I2C ready")

        print("[TEST] Opening TCA9548A MUX (addr=0x70) ...")
        mux = TCA9548A(i2c)
        mux.disable_all()
        print("[TEST] MUX ready")

        print(f"[TEST] Connecting PSU on {PSU_PORT} @ {PSU_BAUDRATE}bps...")
        power.connect()
        print(f"[TEST] PSU ready: {power.identify()}")
        power.configure_protection()

        # ---- Power-On Phase 1: VEXT 5V + VIN 8V (parallel) ----
        print("\n>>> ON Phase 1: Vext=5V and VIN=8V (parallel)")
        power.parallel_ramp([
            ("VEXT", PowerController.CH_VEXT, 5.0, True),
            ("VIN", PowerController.CH_VIN, 8.0, True),
        ], step=STEP, stable_time=STABLE_ON, step_interval=INTERVAL)

        # ---- Power-On Phase 2: VIN 12V + VCAP 35V (parallel) ----
        print("\n>>> ON Phase 2: VIN=12V and VCAP=35V (parallel)")
        power.parallel_ramp([
            ("VIN", PowerController.CH_VIN, 12.0, False),
            ("VCAP", PowerController.CH_VCAP, 35.0, True),
        ], step=STEP, stable_time=STABLE_ON, step_interval=INTERVAL)

        # ---- Power-On Phase 3: VIN 17V ----
        print("\n>>> ON Phase 3: VIN -> 17V")
        power.ramp_voltage(
            PowerController.CH_VIN,
            17.0,
            step=STEP,
            stable_time=STABLE_ON,
            step_interval=INTERVAL,
        )

        print("\n>>> Verify ON targets")
        on_ok = []
        on_ok.append(check_voltage(power, PowerController.CH_VEXT, 5.0, 0.1))
        on_ok.append(check_voltage(power, PowerController.CH_VIN, 17.0, 0.1))
        on_ok.append(check_voltage(power, PowerController.CH_VCAP, 35.0, 0.15))
        if not all(on_ok):
            raise RuntimeError("Power-on verification failed")

        # ---- Power-Off Phase 1: VIN 17V -> 12V ----
        print("\n>>> OFF Phase 1: VIN 17V -> 12V")
        power.ramp_voltage(
            PowerController.CH_VIN,
            12.0,
            step=STEP,
            stable_time=STABLE_OFF,
            step_interval=INTERVAL,
            ensure_output=False,
        )

        # ---- Power-Off Phase 2: VIN 12V -> 8V + VCAP 35V -> 0V (parallel) ----
        print("\n>>> OFF Phase 2: VIN=8V and VCAP=0V (parallel)")
        power.parallel_ramp([
            ("VIN", PowerController.CH_VIN, 8.0, False),
            ("VCAP", PowerController.CH_VCAP, 0.0, False),
        ], step=STEP, stable_time=STABLE_OFF, step_interval=INTERVAL)

        # ---- Power-Off Phase 3: VIN 8V -> 0V + VEXT 5V -> 0V (parallel) ----
        print("\n>>> OFF Phase 3: VIN=0V and VEXT=0V (parallel)")
        power.parallel_ramp([
            ("VIN", PowerController.CH_VIN, 0.0, False),
            ("VEXT", PowerController.CH_VEXT, 0.0, False),
        ], step=STEP, stable_time=STABLE_OFF, step_interval=INTERVAL)

        print("\n>>> Verify OFF targets")
        off_ok = []
        off_ok.append(check_voltage(power, PowerController.CH_VEXT, 0.0, 0.1))
        off_ok.append(check_voltage(power, PowerController.CH_VIN, 0.0, 0.1))
        off_ok.append(check_voltage(power, PowerController.CH_VCAP, 0.0, 0.15))
        if not all(off_ok):
            raise RuntimeError("Power-off verification failed")

        power.output_off(PowerController.CH_VIN)
        power.output_off(PowerController.CH_VCAP)
        power.output_off(PowerController.CH_VEXT)

        print("\n" + "=" * 50)
        print("[TEST] PASS: Power ON/OFF sequence completed")
        print("=" * 50)
        return 0

    except KeyboardInterrupt:
        print("\n[TEST] Interrupted")
        need_emergency = True
        return 1
    except Exception as e:
        print(f"[TEST] FAIL: {e}")
        need_emergency = True
        return 1
    finally:
        if need_emergency and power.ser is not None:
            emergency_stop(power)

        if mux is not None:
            try:
                mux.disable_all()
            except Exception:
                pass

        i2c.close()
        power.disconnect()


if __name__ == "__main__":
    sys.exit(main())
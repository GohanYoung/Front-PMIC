from drivers.aardvark_contorller import AardvarkI2C
from drivers.power_controller import PowerController
from drivers.tca9548a import TCA9548A
from config.register_table import PHASE1, PHASE2


PSU_PORT = "COM5"
PSU_BAUDRATE = 19200

STEP = 2.0
INTERVAL = 1.0
STABLE_ON = 0.3


def main():
    print("=" * 50)
    print("[MAIN] HTOL Power-On Sequence")
    print("=" * 50)

    i2c = AardvarkI2C(port=0, bitrate=400)
    power = PowerController(port=PSU_PORT, baudrate=PSU_BAUDRATE)

    try:
        print("[MAIN] Opening Aardvark I²C (port=0, 400kbps)...")
        i2c.open()
        print("[MAIN] I²C ready")

        print("[MAIN] Opening TCA9548A MUX (addr=0x70) ...")
        mux = TCA9548A(i2c)
        mux.disable_all()
        print("[MAIN] MUX ready")

        print(f"[MAIN] Connecting PSU on {PSU_PORT} @ {PSU_BAUDRATE}bps...")
        power.connect()
        print(f"[MAIN] PSU ready: {power.identify()}")

        # ---- Phase 1: Vext 5V + VIN 8V (parallel) ----
        print("\n>>> Phase 1: Power rails up (Vext=5V ∥ VIN=8V)")
        power.parallel_ramp([
            ("VEXT", PowerController.CH_VEXT, 5.0, True),
            ("VIN",  PowerController.CH_VIN,  8.0, True),
        ], step=STEP, stable_time=STABLE_ON, step_interval=INTERVAL)

        # ---- Phase 1: RT5131 Register Table (all MUX channels) ----
        print("\n>>> Phase 1: RT5131 init (PC -> Aardvark -> MUX[0-7] -> RT5131)")
        phase1_results = mux.write_table_to_all(PHASE1, label="PHASE1")

        # ---- Phase 2: VIN 12V + VCAP 35V (parallel) ----
        print("\n>>> Phase 2: VIN=12V ∥ VCAP=35V")
        power.parallel_ramp([
            ("VIN",  PowerController.CH_VIN,  12.0, False),
            ("VCAP", PowerController.CH_VCAP, 35.0, True),
        ], step=STEP, stable_time=STABLE_ON, step_interval=INTERVAL)

        # ---- Phase 2: RT5131 Register Table PLI mode (all MUX channels) ----
        print("\n>>> Phase 2: RT5131 PLI mode (PC -> Aardvark -> MUX[0-7] -> RT5131)")
        phase2_results = mux.write_table_to_all(PHASE2, label="PHASE2")

        # ---- Phase 3: VIN 17V ----
        print("\n>>> Phase 3: VIN -> 17V")
        print("  [PSU] VIN (CH1) -> 17V ...")
        power.ramp_voltage(PowerController.CH_VIN, 17.0,
                           step=STEP, stable_time=STABLE_ON, step_interval=INTERVAL)
        print("  [PSU] VIN = 17V OK")

        # ---- Final Summary ----
        print("\n" + "=" * 50)
        print("[MAIN] Power-On Sequence COMPLETE")
        print("[MAIN] VEXT=5V  VIN=17V  VCAP=35V")
        print("-" * 50)
        print("  PHASE1 per-channel:")
        for ch, ok, fail, total in phase1_results:
            tag = "OK" if ok else "FAIL"
            print(f"    MUX ch{ch}: {tag} ({total - fail}/{total})")
        print("  PHASE2 per-channel:")
        for ch, ok, fail, total in phase2_results:
            tag = "OK" if ok else "FAIL"
            print(f"    MUX ch{ch}: {tag} ({total - fail}/{total})")
        print("=" * 50)

        print("[MAIN] HTOL system ready. Press Ctrl+C to exit.")
        try:
            while True:
                pass
        except KeyboardInterrupt:
            print("\n[MAIN] Exiting...")

    except Exception as e:
        print(f"[MAIN] ERROR: {e}")
        raise
    finally:
        try:
            mux.disable_all()
        except Exception:
            pass
        i2c.close()
        power.disconnect()


if __name__ == "__main__":
    main()
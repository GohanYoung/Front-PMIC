from aardvark_i2c import AardvarkI2C
from power_controller import PowerController
from rt5131 import RT5131
from power_on_sequence import PowerOnSequence


VIN_RESOURCE = "USB0::0x2A8D::0x0902::MY56321250::INSTR"
VCAP_RESOURCE = "USB0::0x2A8D::0x0902::MY56321251::INSTR"


def main():
    i2c = AardvarkI2C(port=0, bitrate=400)
    power = PowerController(
        vin_resource=VIN_RESOURCE,
        vcap_resource=VCAP_RESOURCE,
    )

    try:
        i2c.open()
        power.open()
        power.output_on()

        rt = RT5131(i2c)
        seq = PowerOnSequence(power, rt)
        seq.run()

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
        i2c.close()
        power.close()


if __name__ == "__main__":
    main()
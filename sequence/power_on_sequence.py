class PowerOnSequence:

    STEP = 2.0
    INTERVAL = 1.0
    STABLE_ON = 0.3
    STABLE_OFF = 0.2

    def __init__(self, power):
        self.power = power

    def _ramp(self, channel, target, reset_before=False):
        self.power.ramp_voltage(
            channel, target,
            step=self.STEP,
            stable_time=self.STABLE_ON,
            reset_before=reset_before,
            step_interval=self.INTERVAL,
        )

    def _ramp_down(self, channel):
        self.power.ramp_voltage(
            channel, 0.0,
            step=self.STEP,
            stable_time=self.STABLE_OFF,
            step_interval=self.INTERVAL,
            ensure_output=False,
        )

    def global_output_off(self):
        self.power.output_off(self.power.CH_VIN)

    def enable_5v(self):
        print("[SEQ] CH5V -> 5V")
        self._ramp(self.power.CH_5V, 5.0, reset_before=True)

    def vin_to_8v(self):
        print("[SEQ] VIN -> 8V")
        self._ramp(self.power.CH_VIN, 8.0, reset_before=True)

    def vin_to_12v(self):
        print("[SEQ] VIN -> 12V")
        self._ramp(self.power.CH_VIN, 12.0)

    def vcap_to_35v(self):
        print("[SEQ] VCAP -> 35V")
        self._ramp(self.power.CH_VCAP, 35.0, reset_before=True)

    def vin_to_17v(self):
        print("[SEQ] VIN -> 17V")
        self._ramp(self.power.CH_VIN, 17.0)

    def shutdown_channel(self, channel):
        name = {1: "VIN", 2: "VCAP", 3: "CH5V"}.get(channel, f"CH{channel}")
        print(f"[SEQ] {name} -> 0V")
        self._ramp_down(channel)

    def emergency_stop(self):
        print("[SEQ] EMERGENCY STOP - pulling all outputs low")
        try:
            for ch in [self.power.CH_VIN, self.power.CH_VCAP, self.power.CH_5V]:
                self.power.select_channel(ch)
                self.power.write("VOLT 0")
                self.power.write("OUTP OFF")
            self.power.current_channel = None
            print("  All channels 0V & OUTP OFF")
        except Exception as e:
            print(f"  Emergency stop error: {e}")
import threading
import time
import serial


class PowerController:

    CH_VIN = 1
    CH_VCAP = 2
    CH_VEXT = 3

    VIN_MAX = 30.0
    VCAP_MAX = 40.0
    VEXT_MAX = 10.0

    OVERSHOOT_MARGIN = 2.0
    OVERSHOOT_DISABLED = 999

    def __init__(self, port, baudrate=19200, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.current_channel = None
        self.hw_ovp_supported = False
        self._lock = threading.RLock()

    # ==================================================
    # Connection
    # ==================================================

    def connect(self):
        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=self.timeout
        )
        if not self.ser.is_open:
            raise RuntimeError("Power supply open failed")
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        self.ser.write(b"*IDN?\n")
        self.ser.flush()
        resp = self.ser.readline().decode(errors='replace').strip()
        if not resp:
            self.ser.close()
            raise RuntimeError(
                f"No device responding on {self.port} @ {self.baudrate}bps. "
                f"Check COM port / baud rate / power supply ON."
            )
        self.current_channel = None
        time.sleep(0.1)
        self.ser.write(b"SYST:REM\n")
        self.ser.flush()
        time.sleep(0.2)
        self.ser.write(b"*RST\n")
        self.ser.flush()
        time.sleep(0.3)
        self._clear_error_queue()
        self._detect_features()
        print(f"[PSU] Connected {self.port} -> {resp[:50]}")

    def disconnect(self):
        if self.ser:
            self.ser.close()
            self.ser = None
            self.current_channel = None
            print("[PSU] Disconnected")

    # ==================================================
    # Basic SCPI
    # ==================================================

    def write(self, cmd):
        if self.ser is None:
            raise RuntimeError("Power supply not connected")
        with self._lock:
            self.ser.write((cmd + "\n").encode())

    def query(self, cmd):
        with self._lock:
            self.write(cmd)
            return self.ser.readline().decode().strip()

    def _check_error(self):
        resp = self.query("SYST:ERR?")
        if not resp.startswith('0'):
            raise RuntimeError(f"PSU SCPI Error: {resp}")
        return resp

    def _clear_error_queue(self):
        while True:
            resp = self.query("SYST:ERR?")
            if resp.startswith('0'):
                break

    def identify(self):
        return self.query("*IDN?")

    def _detect_features(self):
        try:
            self._clear_error_queue()
            self.write(f"INST:NSEL {self.CH_VIN}")
            self.write("OVP:VAL?")
            self.ser.flush()
            raw = self.ser.read(200).decode(errors='replace').strip()
            self._clear_error_queue()
            float(raw)
            self.hw_ovp_supported = True
        except Exception:
            self.hw_ovp_supported = False
            try:
                self._clear_error_queue()
            except Exception:
                pass

    # ==================================================
    # Channel
    # ==================================================

    def select_channel(self, channel):
        if channel not in (1, 2, 3):
            raise ValueError("Channel must be 1~3")
        with self._lock:
            if channel == self.current_channel:
                return
            self.write(f"INST:NSEL {channel}")
            self.current_channel = channel

    # ==================================================
    # Output
    # ==================================================

    def _output_on(self, channel):
        with self._lock:
            self.select_channel(channel)
            self.write("OUTP ON")
            self._check_error()

    def output_off(self, channel):
        with self._lock:
            self.select_channel(channel)
            self.write("OUTP OFF")
            self._check_error()

    # ==================================================
    # Voltage
    # ==================================================

    def _channel_voltage_limit(self, channel):
        if channel == self.CH_VIN:
            return self.VIN_MAX
        if channel == self.CH_VCAP:
            return self.VCAP_MAX
        if channel == self.CH_VEXT:
            return self.VEXT_MAX
        raise ValueError(f"Unknown channel {channel}")

    def _set_voltage(self, channel, voltage):
        vmax = self._channel_voltage_limit(channel)
        if voltage < 0 or voltage > vmax:
            raise ValueError(
                f"Voltage {voltage}V out of range for CH{channel} "
                f"(0 ~ {vmax}V)"
            )
        with self._lock:
            self.select_channel(channel)
            self.write(f"VOLT {voltage}")
            self._check_error()
            actual = float(self.query("VOLT?"))
        if abs(actual - voltage) > 0.05:
            raise RuntimeError(
                f"Setpoint mismatch CH{channel} "
                f"Target={voltage}V PSU={actual}V"
            )

    def _get_voltage_setpoint(self, channel):
        with self._lock:
            self.select_channel(channel)
            return float(self.query("VOLT?"))

    # ==================================================
    # Current
    # ==================================================

    def _set_current(self, channel, current):
        if current <= 0 or current > 5.0:
            raise ValueError(f"Current {current}A out of range (0 ~ 5A)")
        with self._lock:
            self.select_channel(channel)
            self.write(f"CURR {current}")
            self._check_error()

    # ==================================================
    # Measurement
    # ==================================================

    def measure_voltage(self, channel):
        with self._lock:
            self.select_channel(channel)
            return float(self.query("MEAS:VOLT?"))

    # ==================================================
    # Wait / Ramp
    # ==================================================

    def _wait_voltage(self, channel, target, tolerance=0.05, timeout=10,
                     overshoot_margin=None, stable_time=1):
        if overshoot_margin is None:
            overshoot_margin = self.OVERSHOOT_MARGIN
        start = time.time()
        stable_start = None
        overshoot_limit = target + overshoot_margin
        while True:
            actual = self.measure_voltage(channel)
            if actual > overshoot_limit:
                raise RuntimeError(
                    f"Overshoot! CH{channel} "
                    f"Target={target}V Actual={actual:.3f}V "
                    f"(limit={overshoot_limit}V)"
                )
            if abs(actual - target) <= tolerance:
                if stable_start is None:
                    stable_start = time.time()
                elif time.time() - stable_start >= stable_time:
                    return actual
            else:
                stable_start = None
            if time.time() - start > timeout:
                raise TimeoutError(
                    f"Voltage timeout CH{channel} "
                    f"Target={target}V Actual={actual:.3f}V"
                )
            time.sleep(0.1)

    def ramp_voltage(self, channel, target, step=2.0, tolerance=0.05,
                     timeout=10, stable_time=0.3, reset_before=False,
                     step_interval=0, ensure_output=True):
        if step <= 0:
            raise ValueError("step must be > 0")
        if ensure_output:
            self._output_on(channel)
        if reset_before:
            self._set_voltage(channel, 0.0)
            self._wait_voltage(channel, 0.0, tolerance=0.1, timeout=timeout,
                              stable_time=stable_time,
                              overshoot_margin=self.OVERSHOOT_DISABLED)
            current = 0.0
        else:
            current = self._get_voltage_setpoint(channel)
        if abs(target - current) <= tolerance:
            return self._wait_voltage(channel, target, tolerance, timeout,
                                     stable_time=stable_time)
        direction = 1 if target > current else -1
        down = direction < 0
        v = current
        while True:
            v += direction * step
            if (direction > 0 and v >= target) or \
               (direction < 0 and v <= target):
                v = target
            t_step = time.time()
            self._set_voltage(channel, round(v, 3))
            self._wait_voltage(channel, v, tolerance, timeout,
                              stable_time=stable_time,
                              overshoot_margin=self.OVERSHOOT_DISABLED if down else None)
            if v == target:
                break
            remain = step_interval - (time.time() - t_step)
            if remain > 0:
                time.sleep(remain)
        return self.measure_voltage(channel)

    def parallel_ramp(self, tasks, step=2.0, stable_time=0.3, step_interval=1.0):
        """tasks: list of (label, channel, target, reset_before)"""
        errors = {}
        threads = []

        def _worker(label, channel, target, reset_before):
            try:
                print(f"  [PSU] {label} (CH{channel}) -> {target}V ...")
                self.ramp_voltage(channel, target, reset_before=reset_before,
                                  step=step, stable_time=stable_time,
                                  step_interval=step_interval)
                print(f"  [PSU] {label} = {target}V OK")
            except Exception as e:
                errors[label] = e
                print(f"  [PSU] {label} FAILED: {e}")

        for label, ch, target, reset_before in tasks:
            t = threading.Thread(target=_worker,
                                 args=(label, ch, target, reset_before))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors:
            raise RuntimeError(f"Parallel ramp failed: {errors}")

    # ==================================================
    # Protection
    # ==================================================

    def configure_protection(self):
        self._clear_error_queue()

        self._set_current(self.CH_VIN, 3.0)
        self._set_current(self.CH_VCAP, 3.0)
        self._set_current(self.CH_VEXT, 1.0)

        ovp_vin = self.VIN_MAX + 1.0
        ovp_vcap = self.VCAP_MAX + 1.0
        ovp_vext = self.VEXT_MAX + 1.0

        ovp_ok = self.hw_ovp_supported
        if ovp_ok:
            try:
                for ch, val in [(self.CH_VIN, ovp_vin),
                                (self.CH_VCAP, ovp_vcap),
                                (self.CH_VEXT, ovp_vext)]:
                    self.select_channel(ch)
                    self.write(f"OVP:VAL {val}")
                    self._clear_error_queue()
            except Exception:
                ovp_ok = False
                self._clear_error_queue()

        if ovp_ok:
            print(
                f"[PSU] Protection: HW OVP enabled "
                f"VIN={ovp_vin}V VCAP={ovp_vcap}V VEXT={ovp_vext}V | "
                f"OCP VIN=3A VCAP=3A VEXT=1A"
            )
        else:
            print(
                f"[PSU] Protection: SW limits only "
                f"VIN≤{self.VIN_MAX}V VCAP≤{self.VCAP_MAX}V VEXT≤{self.VEXT_MAX}V | "
                f"OCP VIN=3A VCAP=3A VEXT=1A"
            )
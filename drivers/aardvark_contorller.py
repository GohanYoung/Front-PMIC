from array import array
import time

try:
    from SDK.aardvark_py import (  # Official Total Phase Python binding
        aa_open,
        aa_close,
        aa_configure,
        aa_i2c_bitrate,
        aa_i2c_pullup,
        aa_target_power,
        aa_i2c_write,
        aa_i2c_read,
        aa_status_string,
        AA_CONFIG_SPI_I2C,
        AA_I2C_PULLUP_BOTH,
        AA_I2C_NO_FLAGS,
        AA_TARGET_POWER_BOTH,
    )
except ImportError as exc:
    raise ImportError(
        "Cannot import official Aardvark SDK Python binding. "
        "Ensure SDK/aardvark_py.py and DLLs are available."
    ) from exc


class AardvarkI2C:

    def __init__(self, port=0, bitrate=100, debug=False,
                 enable_pullup=True, enable_target_power=False):
        self.handle = None
        self.port = port
        self.bitrate = bitrate
        self.debug = debug
        self.enable_pullup = enable_pullup
        self.enable_target_power = enable_target_power

    # ==================================================
    # Private
    # ==================================================

    def _check_open(self):
        if self.handle is None:
            raise RuntimeError("Aardvark not opened")

    def _log(self, msg):
        if self.debug:
            print(msg)

    # ==================================================
    # Open / Close
    # ==================================================

    def open(self):
        self.handle = aa_open(self.port)
        if self.handle < 0:
            raise RuntimeError(
                f"Aardvark open failed (port={self.port}): "
                f"{aa_status_string(self.handle)}"
            )

        status = aa_configure(self.handle, AA_CONFIG_SPI_I2C)
        if status < 0:
            raise RuntimeError(f"Aardvark configure failed: {aa_status_string(status)}")

        actual_bitrate = aa_i2c_bitrate(self.handle, self.bitrate)
        if actual_bitrate <= 0:
            raise RuntimeError(f"Set bitrate failed ({self.bitrate} kHz)")

        if self.enable_pullup:
            status = aa_i2c_pullup(self.handle, AA_I2C_PULLUP_BOTH)
            if status < 0:
                raise RuntimeError(f"Enable I2C pull-up failed: {aa_status_string(status)}")

        if self.enable_target_power:
            status = aa_target_power(self.handle, AA_TARGET_POWER_BOTH)
            if status < 0:
                raise RuntimeError(f"Enable target power failed: {aa_status_string(status)}")

        print(f"[Aardvark] Opened port={self.port} bitrate={actual_bitrate}kHz")

    def close(self):
        if self.handle is not None:
            aa_close(self.handle)
            self.handle = None
            print("[Aardvark] Closed")

    def recover_bus(self, reopen_delay_ms=20):
        if reopen_delay_ms < 0:
            raise ValueError("reopen_delay_ms must be >= 0")

        was_open = self.handle is not None
        if was_open:
            aa_close(self.handle)
            self.handle = None
            self._log("[Aardvark] Recover: adapter closed")
            if reopen_delay_ms > 0:
                time.sleep(reopen_delay_ms / 1000.0)

        self.open()
        self._log("[Aardvark] Recover: adapter reopened")

    # ==================================================
    # Write
    # ==================================================

    def write(self, dev_addr, data):
        self._check_open()
        if isinstance(data, (list, tuple)):
            data = array('B', data)

        count = aa_i2c_write(self.handle, dev_addr, AA_I2C_NO_FLAGS, data)
        if count < 0:
            raise RuntimeError(
                f"I2C Write Failed Addr=0x{dev_addr:02X}: "
                f"{aa_status_string(count)}"
            )
        if count != len(data):
            raise RuntimeError(
                f"I2C Write Incomplete Addr=0x{dev_addr:02X} "
                f"Expected={len(data)} Actual={count}"
            )

        self._log(f"[TX] 0x{dev_addr:02X} {list(data)}")

    # ==================================================
    # Read Register
    # ==================================================

    def read(self, dev_addr, reg, length=1):
        self._check_open()
        self.write(dev_addr, [reg])

        count, rx_buf = aa_i2c_read(self.handle, dev_addr, AA_I2C_NO_FLAGS, length)
        if count < 0:
            raise RuntimeError(
                f"I2C Read Failed Addr=0x{dev_addr:02X} Reg=0x{reg:02X}: "
                f"{aa_status_string(count)}"
            )
        if count != length:
            raise RuntimeError(
                f"I2C Read Incomplete Addr=0x{dev_addr:02X} "
                f"Reg=0x{reg:02X} Expected={length} Actual={count}"
            )

        data = list(rx_buf[:count])
        self._log(f"[RX] 0x{dev_addr:02X} Reg=0x{reg:02X} {data}")
        return data

    def read_raw(self, dev_addr, length=1):
        self._check_open()
        count, rx_buf = aa_i2c_read(self.handle, dev_addr, AA_I2C_NO_FLAGS, length)
        if count < 0:
            raise RuntimeError(
                f"I2C Raw Read Failed Addr=0x{dev_addr:02X}: "
                f"{aa_status_string(count)}"
            )
        if count != length:
            raise RuntimeError(
                f"I2C Read Incomplete Addr=0x{dev_addr:02X} "
                f"Expected={length} Actual={count}"
            )

        data = list(rx_buf[:count])
        self._log(f"[RX-RAW] 0x{dev_addr:02X} {data}")
        return data

    # ==================================================
    # Read Single Byte
    # ==================================================

    def read_byte(self, dev_addr, reg):
        data = self.read(dev_addr, reg, length=1)
        return data[0]

    def write_with_retry(self, dev_addr, data, retry=3, retry_delay_ms=10):
        if retry <= 0:
            raise ValueError("retry must be > 0")

        last_exc = None
        for attempt in range(1, retry + 1):
            try:
                self.write(dev_addr, data)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < retry:
                    time.sleep(retry_delay_ms / 1000.0)
        raise last_exc

    def scan_addresses(self, start_addr=0x08, end_addr=0x77, probe_byte=0x00,
                       retry=3, retry_delay_ms=10, skip_addrs=None, on_found=None):
        if start_addr < 0x00 or end_addr > 0x7F or start_addr > end_addr:
            raise ValueError("invalid scan range")

        if skip_addrs is None:
            skip_addrs = set()

        found = []
        for addr in range(start_addr, end_addr + 1):
            if addr in skip_addrs:
                continue
            try:
                self.write_with_retry(addr, [probe_byte & 0xFF], retry, retry_delay_ms)
                found.append(addr)
                if on_found is not None:
                    on_found(addr)
            except Exception:
                pass

        return found
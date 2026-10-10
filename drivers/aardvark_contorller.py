from array import array

from aa import (
    aa_open,
    aa_close,
    aa_configure,
    aa_i2c_bitrate,
    aa_i2c_write,
    aa_i2c_read,

    AA_CONFIG_SPI_I2C,
    AA_I2C_NO_FLAGS,
)


class AardvarkI2C:

    def __init__(self, port=0, bitrate=100, debug=False):
        self.handle = None
        self.port = port
        self.bitrate = bitrate
        self.debug = debug

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
            raise RuntimeError(f"Aardvark open failed (port={self.port})")

        status = aa_configure(self.handle, AA_CONFIG_SPI_I2C)
        if status < 0:
            raise RuntimeError("Aardvark configure failed")

        actual_bitrate = aa_i2c_bitrate(self.handle, self.bitrate)
        if actual_bitrate <= 0:
            raise RuntimeError(f"Set bitrate failed ({self.bitrate} kHz)")

        print(f"[Aardvark] Opened port={self.port} bitrate={actual_bitrate}kHz")

    def close(self):
        if self.handle is not None:
            aa_close(self.handle)
            self.handle = None
            print("[Aardvark] Closed")

    # ==================================================
    # Write
    # ==================================================

    def write(self, dev_addr, data):
        self._check_open()
        if isinstance(data, (list, tuple)):
            data = array('B', data)

        count = aa_i2c_write(self.handle, dev_addr, AA_I2C_NO_FLAGS, data)
        if count < 0:
            raise RuntimeError(f"I2C Write Failed Addr=0x{dev_addr:02X}")
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

        rx_buf = array('B', [0] * length)
        count = aa_i2c_read(self.handle, dev_addr, AA_I2C_NO_FLAGS, rx_buf)
        if count < 0:
            raise RuntimeError(
                f"I2C Read Failed Addr=0x{dev_addr:02X} Reg=0x{reg:02X}"
            )
        if count != length:
            raise RuntimeError(
                f"I2C Read Incomplete Addr=0x{dev_addr:02X} "
                f"Reg=0x{reg:02X} Expected={length} Actual={count}"
            )

        data = list(rx_buf[:count])
        self._log(f"[RX] 0x{dev_addr:02X} Reg=0x{reg:02X} {data}")
        return data

    # ==================================================
    # Read Single Byte
    # ==================================================

    def read_byte(self, dev_addr, reg):
        data = self.read(dev_addr, reg, length=1)
        return data[0]

    # ==================================================
    # Device Detect
    # ==================================================

    def ping(self, dev_addr):
        try:
            self.write(dev_addr, [])
            return True
        except Exception:
            return False
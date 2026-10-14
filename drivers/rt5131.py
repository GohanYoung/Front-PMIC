import contextlib


class RT5131:

    ADDR = 0x40

    def __init__(self, i2c, addr=ADDR, mux=None, channel=None):
        self.i2c = i2c
        self.addr = addr
        self.mux = mux
        self.channel = channel

    def _tx(self):
        if self.mux is not None and self.channel is not None:
            return self.mux.route(self.channel)
        return contextlib.nullcontext()

    # ==========================================
    # Internal Helpers
    # ==========================================

    def _write_then_read(self, reg, value):
        reg = reg & 0xFF
        value = value & 0xFF
        with self._tx():
            self.i2c.write(self.addr, [reg, value])
            return self.i2c.read_byte(self.addr, reg)

    # ==========================================
    # Register Verify
    # ==========================================

    def _write_and_verify(self, reg, value):
        try:
            expected = value & 0xFF
            actual = self._write_then_read(reg, value)
            if actual != expected:
                return (reg, value, False,
                        f"verify fail: read 0x{actual:02X}")
            return (reg, value, True, None)
        except Exception as e:
            return (reg, value, False, str(e))

    # ==========================================
    # Register Table
    # ==========================================

    def write_table(self, table):
        return [self._write_and_verify(reg, value) for reg, value in table]
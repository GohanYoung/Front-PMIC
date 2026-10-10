class RT5131:

    ADDR = 0x40

    REG_UNLOCK = 0x33
    UNLOCK_KEY = 0xAD

    def __init__(self, i2c, addr=ADDR):
        self.i2c = i2c
        self.addr = addr

    # ==========================================
    # Basic Register Access
    # ==========================================

    def write_reg(self, reg, value):
        self.i2c.write(self.addr, [reg & 0xFF, value & 0xFF])

    def read_reg(self, reg):
        return self.i2c.read_byte(self.addr, reg)

    # ==========================================
    # Register Verify
    # ==========================================

    def write_and_verify(self, reg, value):
        self.write_reg(reg, value)
        actual = self.read_reg(reg)
        if actual != value:
            raise RuntimeError(
                f"RT5131 Verify Failed "
                f"Reg=0x{reg:02X} "
                f"Expected=0x{value:02X} "
                f"Actual=0x{actual:02X}"
            )
        print(f"[PASS] Reg=0x{reg:02X} Value=0x{value:02X}")
        return True

    # ==========================================
    # Unlock
    # ==========================================

    def unlock(self):
        self.write_and_verify(self.REG_UNLOCK, self.UNLOCK_KEY)

    # ==========================================
    # Register Table
    # ==========================================

    def write_table(self, table):
        for reg, value in table:
            self.write_and_verify(reg, value)
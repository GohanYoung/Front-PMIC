class TCA9548A:

    ADDR = 0x70

    def __init__(self, i2c, addr=ADDR):
        self.i2c = i2c
        self.addr = addr

    def select_channel(self, channel):
        self.i2c.write(self.addr, [1 << channel])
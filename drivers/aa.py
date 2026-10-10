AA_OK = 0
AA_CONFIG_SPI_I2C = 0x03
AA_I2C_NO_FLAGS = 0x00
AA_I2C_FLAG_TENBIT = 0x04
AA_I2C_FLAG_NOSTART = 0x02
AA_I2C_FLAG_STOP = 0x01


def aa_open(port=0):
    raise NotImplementedError(
        "aa_open requires Total Phase Aardvark SDK. "
        "Download from https://www.totalphase.com/support/"
    )


def aa_close(handle):
    pass


def aa_configure(handle, config):
    raise NotImplementedError(
        "aa_configure requires Total Phase Aardvark SDK."
    )


def aa_i2c_bitrate(handle, bitrate):
    raise NotImplementedError(
        "aa_i2c_bitrate requires Total Phase Aardvark SDK."
    )


def aa_i2c_write(handle, dev_addr, flags, data):
    raise NotImplementedError(
        "aa_i2c_write requires Total Phase Aardvark SDK."
    )


def aa_i2c_read(handle, dev_addr, flags, length):
    raise NotImplementedError(
        "aa_i2c_read requires Total Phase Aardvark SDK."
    )
"""SQ40003 Charger IC register table aligned with project verification plan."""

CHARGER_I2C_ADDR = 0x33


# Columns: addr, name, reg_type, default, recommend, verify
# verify:
#   - RW_SAFE: suitable for write/read-back verification in normal bring-up
#   - RW_CAUTION: writable but may affect runtime behavior, verify with caution
#   - RO_ONLY: read-only, use read verification only
CHARGER_REGISTER_TABLE = [
    {"addr": 0x00, "name": "MTP_CTRL", "reg_type": "R/W", "default": "0x00", "recommend": "NO", "verify": "RW_CAUTION"},
    {"addr": 0x01, "name": "Enable_CTRL", "reg_type": "R/W", "default": "0x1A", "recommend": "YES", "verify": "RW_SAFE"},
    {"addr": 0x02, "name": "Load_SW_CTRL", "reg_type": "R/W", "default": "0x02", "recommend": "YES", "verify": "RW_SAFE"},
    {"addr": 0x03, "name": "Booster_CTRL1", "reg_type": "R/W", "default": "0x99", "recommend": "YES", "verify": "RW_SAFE"},
    {"addr": 0x04, "name": "Booster_CTRL2", "reg_type": "R/W", "default": "0x8A", "recommend": "YES", "verify": "RW_SAFE"},
    {"addr": 0x05, "name": "Buck_OFF_CTRL", "reg_type": "R/W", "default": "0x11", "recommend": "YES", "verify": "RW_SAFE"},
    {"addr": 0x06, "name": "VPFI Setting", "reg_type": "R/W", "default": "0x11", "recommend": "YES", "verify": "RW_SAFE"},
    {"addr": 0x07, "name": "VFBB Setting", "reg_type": "R/W", "default": "0x12", "recommend": "YES", "verify": "RW_SAFE"},
    {"addr": 0x08, "name": "VBDET Setting", "reg_type": "R/W", "default": "0x08", "recommend": "YES", "verify": "RW_SAFE"},
    {"addr": 0x09, "name": "Delay & DIS", "reg_type": "R/W", "default": "0x68", "recommend": "YES", "verify": "RW_SAFE"},
    {"addr": 0x0A, "name": "Health Measure1", "reg_type": "R/W", "default": "0x00", "recommend": "CAUTION", "verify": "RW_CAUTION"},
    {"addr": 0x0B, "name": "Health Measure2", "reg_type": "R/W", "default": "0x00", "recommend": "CAUTION", "verify": "RW_CAUTION"},
    {"addr": 0x0C, "name": "Health Measure3", "reg_type": "R/W", "default": "0x00", "recommend": "CAUTION", "verify": "RW_CAUTION"},
    {"addr": 0x0D, "name": "Cap Test Time H", "reg_type": "RO", "default": "Dynamic", "recommend": "NO", "verify": "RO_ONLY"},
    {"addr": 0x0E, "name": "Cap Test Time L", "reg_type": "RO", "default": "Dynamic", "recommend": "NO", "verify": "RO_ONLY"},
    {"addr": 0x0F, "name": "ESR & LKG", "reg_type": "RO", "default": "Dynamic", "recommend": "NO", "verify": "RO_ONLY"},
    {"addr": 0x10, "name": "ADC_CTRL", "reg_type": "R/W", "default": "0xE8", "recommend": "CAUTION", "verify": "RW_CAUTION"},
    {"addr": 0x11, "name": "ADC VIN", "reg_type": "RO", "default": "Dynamic", "recommend": "NO", "verify": "RO_ONLY"},
    {"addr": 0x12, "name": "ADC Current", "reg_type": "RO", "default": "Dynamic", "recommend": "NO", "verify": "RO_ONLY"},
    {"addr": 0x13, "name": "Alert", "reg_type": "R/W", "default": "0x00", "recommend": "CAUTION", "verify": "RW_CAUTION"},
    {"addr": 0x14, "name": "LKG Criteria", "reg_type": "R/W", "default": "0x00", "recommend": "YES", "verify": "RW_SAFE"},
    {"addr": 0x15, "name": "Vendor Status", "reg_type": "RO", "default": "Dynamic", "recommend": "RO_VERIFY", "verify": "RO_ONLY"},
    {"addr": 0x16, "name": "VSTRG_REF", "reg_type": "R/W", "default": "Mode Dependent", "recommend": "CAUTION", "verify": "RW_CAUTION"},
]

# Static verification groups (no runtime logic in this file)
RW_VERIFY_SAFE_REGS = [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x14]
RW_VERIFY_CAUTION_REGS = [0x00, 0x0A, 0x0B, 0x0C, 0x10, 0x13, 0x16]
RO_VERIFY_REGS = [0x0D, 0x0E, 0x0F, 0x11, 0x12, 0x15]


WRITE_TEST_REG = 0x09
WRITE_TEST_VALUE = 0x48

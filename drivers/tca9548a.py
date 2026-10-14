import threading

from drivers.rt5131 import RT5131


class _RouteContext:
    def __init__(self, mux, channel):
        self.mux = mux
        self.channel = channel

    def __enter__(self):
        self.mux.select_channel(self.channel)
        return self

    def __exit__(self, *args):
        pass


class TCA9548A:

    ADDR = 0x70

    def __init__(self, i2c, addr=ADDR):
        self.i2c = i2c
        self.addr = addr
        self._lock = threading.RLock()
        self._current = None

    def select_channel(self, channel):
        if not (0 <= channel <= 7):
            raise ValueError("channel must be 0~7")
        with self._lock:
            if self._current == channel:
                return
            self.i2c.write(self.addr, [1 << channel])
            self._current = channel

    def disable_all(self):
        with self._lock:
            self.i2c.write(self.addr, [0x00])
            self._current = None

    def route(self, channel):
        return _RouteContext(self, channel)

    def write_table_to_all(self, table, label="", channels=8):
        print(f"\n  [{label}] Writing {len(table)} regs to {channels} MUX channels ...")
        summary = []
        for ch in range(channels):
            rt = RT5131(self.i2c, mux=self, channel=ch)
            results = rt.write_table(table)
            failed = [(r, v, err) for r, v, ok, err in results if not ok]
            if failed:
                print(f"    MUX ch{ch}: FAIL ({len(failed)}/{len(results)})")
                for r, v, err in failed:
                    print(f"      Reg=0x{r:02X} Val=0x{v:02X} -> {err}")
            else:
                print(f"    MUX ch{ch}: OK ({len(results)}/{len(results)})")
            summary.append((ch, len(failed) == 0, len(failed), len(results)))
        ok_count = sum(1 for _, ok, _, _ in summary if ok)
        print(f"  [{label}] Result: {ok_count}/{channels} channels OK")
        return summary
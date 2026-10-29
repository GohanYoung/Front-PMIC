import threading
import time

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

    def select_channel_with_retry(self, channel, retry=3, retry_delay_ms=10):
        if retry <= 0:
            raise ValueError("retry must be > 0")

        last_exc = None
        for attempt in range(1, retry + 1):
            try:
                self.select_channel(channel)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < retry:
                    time.sleep(retry_delay_ms / 1000.0)
        raise last_exc

    def disable_all(self):
        with self._lock:
            self.i2c.write(self.addr, [0x00])
            self._current = None

    def route(self, channel):
        return _RouteContext(self, channel)

    def read_byte_with_channel_recovery(
        self,
        channel,
        dev_addr,
        reg,
        read_retry=2,
        retry_delay_ms=10,
        recover_reopen_delay_ms=20,
    ):
        if read_retry <= 0:
            raise ValueError("read_retry must be > 0")

        last_exc = None
        last_disable_err = None
        last_recover_err = None
        for attempt in range(1, read_retry + 1):
            try:
                self.select_channel_with_retry(channel, retry=3, retry_delay_ms=retry_delay_ms)
                value = self.i2c.read_byte(dev_addr, reg)
                return value
            except Exception as exc:
                last_exc = exc
                last_disable_err = None
                last_recover_err = None
                try:
                    self.disable_all()
                except Exception as disable_exc:
                    last_disable_err = disable_exc
                finally:
                    self._current = None

                try:
                    self.i2c.recover_bus(reopen_delay_ms=recover_reopen_delay_ms)
                except Exception as recover_exc:
                    last_recover_err = recover_exc

                if attempt < read_retry and retry_delay_ms > 0:
                    time.sleep(retry_delay_ms / 1000.0)
        msg = (
            f"read with recovery failed channel={channel} addr=0x{dev_addr:02X} "
            f"reg=0x{reg:02X}: {last_exc}"
        )
        if last_disable_err is not None:
            msg += f" | disable_all_err={last_disable_err}"
        if last_recover_err is not None:
            msg += f" | recover_bus_err={last_recover_err}"
        raise RuntimeError(msg)

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
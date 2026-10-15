#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Power supply sequence GUI for the IIC project.

This GUI is intentionally modeled after the provided stress-GUI structure:
- Parameter panel on the left
- Status banner on top
- Live log + channel cards + trend chart on the right
- Worker thread for serial/SCPI actions

It focuses on PSU behavior only (no register-table writes).
"""

from __future__ import annotations

import datetime as dt
import queue
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

# Ensure project root imports work when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from drivers.power_controller import PowerController

try:
    from serial.tools import list_ports
    SERIAL_PORT_ENUM_AVAILABLE = True
except Exception:
    SERIAL_PORT_ENUM_AVAILABLE = False


CH_LABEL = {
    PowerController.CH_VIN: "VIN",
    PowerController.CH_VCAP: "VCAP",
    PowerController.CH_VEXT: "VEXT",
}


class PowerWorker:
    """Background executor for PSU sequencing and telemetry."""

    def __init__(self, cfg, log_q, state_q, data_q, done_q):
        self.cfg = cfg
        self.log_q = log_q
        self.state_q = state_q
        self.data_q = data_q
        self.done_q = done_q

        self.stop_event = threading.Event()
        self.psu = None
        self.set_voltage = {
            PowerController.CH_VIN: 0.0,
            PowerController.CH_VCAP: 0.0,
            PowerController.CH_VEXT: 0.0,
        }

    def log(self, text, tag="info"):
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        self.log_q.put((stamp, text, tag))

    def state(self, text, color):
        self.state_q.put((text, color))

    def _check_stop(self, stage_name):
        if self.stop_event.is_set():
            raise InterruptedError(f"Stopped by user during {stage_name}")

    def connect(self):
        self.log(
            f"Connecting PSU {self.cfg['port']} @ {self.cfg['baudrate']}bps ...",
            "section",
        )
        self.psu = PowerController(
            port=self.cfg["port"],
            baudrate=self.cfg["baudrate"],
            timeout=self.cfg["timeout"],
        )
        self.psu.connect()
        ident = self.psu.identify()
        self.log(f"Connected: {ident}", "ok")
        self.psu.configure_protection()
        self.log("Protection configured", "ok")

    def _push_set(self, channel, value):
        self.set_voltage[channel] = float(value)
        self.data_q.put(("set", channel, float(value), time.time()))

    def _measure_and_publish(self, channel):
        voltage = self.psu.measure_voltage(channel)
        now = time.time()
        self.data_q.put(("actual", channel, voltage, now))

        diff = abs(voltage - self.set_voltage[channel])
        if self.set_voltage[channel] >= 0.5 and diff > self.cfg["alarm_threshold"]:
            self.log(
                f"ALARM {CH_LABEL[channel]}: set={self.set_voltage[channel]:.3f}V "
                f"actual={voltage:.3f}V diff={diff:.3f}V",
                "alarm",
            )
            self.data_q.put(("alarm", channel, self.set_voltage[channel], voltage, now))
            self.stop_event.set()
        return voltage

    def _ramp_single(self, channel, target, step, stable_time, step_interval, reset_before, stage_name):
        self._check_stop(stage_name)
        label = CH_LABEL[channel]
        self.log(f"{stage_name}: {label} -> {target:.3f}V", "section")

        self.psu.ramp_voltage(
            channel,
            target,
            step=step,
            stable_time=stable_time,
            step_interval=step_interval,
            reset_before=reset_before,
            ensure_output=True,
        )

        self._push_set(channel, target)
        v = self._measure_and_publish(channel)
        self.log(f"{label} reached {v:.3f}V", "ok")

    def _ramp_parallel(self, tasks, step, stable_time, step_interval, stage_name):
        self._check_stop(stage_name)
        labels = ", ".join(f"{CH_LABEL[ch]}->{target:.3f}V" for ch, target, _ in tasks)
        self.log(f"{stage_name}: parallel ramp [{labels}]", "section")

        formatted_tasks = []
        for channel, target, reset_before in tasks:
            formatted_tasks.append((CH_LABEL[channel], channel, target, reset_before))

        self.psu.parallel_ramp(
            formatted_tasks,
            step=step,
            stable_time=stable_time,
            step_interval=step_interval,
        )

        for channel, target, _ in tasks:
            self._push_set(channel, target)
            self._measure_and_publish(channel)

    def _hold(self, seconds):
        self.log(f"Hold: {seconds:.1f}s", "warn")
        start = time.monotonic()
        next_sample = 0.0
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= seconds:
                self.log("Hold completed", "ok")
                return
            self._check_stop("hold")
            if elapsed >= next_sample:
                for channel in (PowerController.CH_VEXT, PowerController.CH_VIN, PowerController.CH_VCAP):
                    self._measure_and_publish(channel)
                remain = max(0, int(seconds - elapsed))
                self.log(f"Holding... remaining {remain}s", "detail")
                next_sample = elapsed + self.cfg["monitor_interval"]
            time.sleep(0.2)

    def _safe_powerdown(self):
        self.state("SAFE POWER DOWN", "#d29922")
        self.log("Safe power-down start", "section")

        try:
            self.psu.parallel_ramp(
                [
                    ("VIN", PowerController.CH_VIN, 12.0, False),
                    ("VCAP", PowerController.CH_VCAP, 0.0, False),
                ],
                step=self.cfg["step"],
                stable_time=self.cfg["stable_off"],
                step_interval=self.cfg["interval"],
            )
            self._push_set(PowerController.CH_VIN, 12.0)
            self._push_set(PowerController.CH_VCAP, 0.0)
            self._measure_and_publish(PowerController.CH_VIN)
            self._measure_and_publish(PowerController.CH_VCAP)

            self.psu.parallel_ramp(
                [
                    ("VIN", PowerController.CH_VIN, 0.0, False),
                    ("VEXT", PowerController.CH_VEXT, 0.0, False),
                ],
                step=self.cfg["step"],
                stable_time=self.cfg["stable_off"],
                step_interval=self.cfg["interval"],
            )
            self._push_set(PowerController.CH_VIN, 0.0)
            self._push_set(PowerController.CH_VEXT, 0.0)
            self._measure_and_publish(PowerController.CH_VIN)
            self._measure_and_publish(PowerController.CH_VEXT)

            for channel in (
                PowerController.CH_VIN,
                PowerController.CH_VCAP,
                PowerController.CH_VEXT,
            ):
                self.psu.output_off(channel)
            self.log("All channel outputs OFF", "ok")
        except Exception as exc:
            self.log(f"Controlled power-down failed: {exc}", "error")
            # Last-resort emergency OFF command sequence.
            for channel in (
                PowerController.CH_VIN,
                PowerController.CH_VCAP,
                PowerController.CH_VEXT,
            ):
                try:
                    self.psu.select_channel(channel)
                    self.psu.write("VOLT 0")
                    self.psu.write("OUTP OFF")
                except Exception:
                    pass
            self.log("Emergency OFF commands sent", "warn")

    def run(self):
        completed = False

        try:
            self.state("CONNECTING", "#1f6feb")
            self.connect()

            self._check_stop("initialization")
            self.state("POWER ON", "#1f6feb")
            self.log("Power sequence start", "section")

            # ON Phase 1: VEXT 5V + VIN 8V
            self._ramp_parallel(
                [
                    (PowerController.CH_VEXT, self.cfg["vext_on"], True),
                    (PowerController.CH_VIN, self.cfg["vin_p1"], True),
                ],
                step=self.cfg["step"],
                stable_time=self.cfg["stable_on"],
                step_interval=self.cfg["interval"],
                stage_name="ON Phase 1",
            )

            # ON Phase 2: VIN 12V + VCAP 35V
            self._ramp_parallel(
                [
                    (PowerController.CH_VIN, self.cfg["vin_p2"], False),
                    (PowerController.CH_VCAP, self.cfg["vcap_on"], True),
                ],
                step=self.cfg["step"],
                stable_time=self.cfg["stable_on"],
                step_interval=self.cfg["interval"],
                stage_name="ON Phase 2",
            )

            # ON Phase 3: VIN -> 17V
            self._ramp_single(
                PowerController.CH_VIN,
                self.cfg["vin_p3"],
                step=self.cfg["step"],
                stable_time=self.cfg["stable_on"],
                step_interval=self.cfg["interval"],
                reset_before=False,
                stage_name="ON Phase 3",
            )

            if self.cfg["hold_time"] > 0:
                self.state("HOLDING", "#1f6feb")
                self._hold(self.cfg["hold_time"])

            self._check_stop("before power-off")
            self.state("POWER OFF", "#1f6feb")

            # OFF Phase 1: VIN 17V -> 12V
            self._ramp_single(
                PowerController.CH_VIN,
                self.cfg["vin_p2"],
                step=self.cfg["step"],
                stable_time=self.cfg["stable_off"],
                step_interval=self.cfg["interval"],
                reset_before=False,
                stage_name="OFF Phase 1",
            )

            # OFF Phase 2: VIN 12V -> 8V + VCAP 35V -> 0V
            self._ramp_parallel(
                [
                    (PowerController.CH_VIN, self.cfg["vin_p1"], False),
                    (PowerController.CH_VCAP, 0.0, False),
                ],
                step=self.cfg["step"],
                stable_time=self.cfg["stable_off"],
                step_interval=self.cfg["interval"],
                stage_name="OFF Phase 2",
            )

            # OFF Phase 3: VIN 8V -> 0V + VEXT 5V -> 0V
            self._ramp_parallel(
                [
                    (PowerController.CH_VIN, 0.0, False),
                    (PowerController.CH_VEXT, 0.0, False),
                ],
                step=self.cfg["step"],
                stable_time=self.cfg["stable_off"],
                step_interval=self.cfg["interval"],
                stage_name="OFF Phase 3",
            )

            for channel in (
                PowerController.CH_VIN,
                PowerController.CH_VCAP,
                PowerController.CH_VEXT,
            ):
                self.psu.output_off(channel)
            self.log("Sequence completed", "ok")
            completed = True

        except InterruptedError as exc:
            self.log(str(exc), "warn")
            if self.psu is not None:
                self._safe_powerdown()
        except Exception as exc:
            self.log(f"ERROR: {exc}", "error")
            if self.psu is not None:
                self._safe_powerdown()
        finally:
            if self.psu is not None:
                self.psu.disconnect()
            self.state("READY" if completed else "STOPPED", "#238636" if completed else "#8b0000")
            self.done_q.put(True)


class PowerGuiApp(tk.Tk):
    COLORS = {
        "bg": "#0d1117",
        "panel": "#161b22",
        "fg": "#e6edf3",
        "muted": "#8b949e",
        "blue": "#58a6ff",
        "green": "#3fb950",
        "yellow": "#d29922",
        "red": "#f85149",
        "vin": "#56cfe1",
        "vcap": "#ffb347",
        "vext": "#f5a97f",
        "grid": "#30363d",
    }

    def __init__(self):
        super().__init__()
        self.title("IIC Power Supply Sequence Controller")
        self._init_window_size()
        self.minsize(980, 620)
        self.configure(bg=self.COLORS["bg"])

        self.log_q = queue.Queue()
        self.state_q = queue.Queue()
        self.data_q = queue.Queue()
        self.done_q = queue.Queue()

        self.worker = None
        self.running = False
        self.start_time = None

        self.variables = {}
        self.labels = {}

        self.set_points = []
        self.actual_points = {
            PowerController.CH_VIN: [],
            PowerController.CH_VCAP: [],
            PowerController.CH_VEXT: [],
        }

        self._build()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _init_window_size(self):
        """Use screen-adaptive startup size to avoid clipped UI on small displays."""
        screen_w = max(800, int(self.winfo_screenwidth()))
        screen_h = max(600, int(self.winfo_screenheight()))

        if screen_w >= 1600 and screen_h >= 900:
            # Keep full-screen feel on large monitors.
            self.state("zoomed")
            return

        width = min(1360, max(980, int(screen_w * 0.96)))
        height = min(860, max(620, int(screen_h * 0.92)))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _build_scrollable_left(self, parent, width):
        """Create a fixed-width, vertically scrollable left settings panel."""
        outer = tk.Frame(parent, bg=self.COLORS["bg"], width=width)
        outer.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        outer.pack_propagate(False)

        canvas = tk.Canvas(outer, bg=self.COLORS["bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        inner = tk.Frame(canvas, bg=self.COLORS["bg"])

        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_inner_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfigure(inner_window, width=event.width)

        def _on_mousewheel(event):
            # Windows reports wheel delta in units of 120.
            canvas.yview_scroll(int(-event.delta / 120), "units")

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<MouseWheel>", _on_mousewheel)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        return inner

    def _var(self, key, value):
        var = tk.StringVar(value=str(value))
        self.variables[key] = var
        return var

    def _add_entry(self, parent, row, label, key, default, values=None):
        c = self.COLORS
        tk.Label(parent, text=label, bg=c["panel"], fg=c["fg"], anchor="w").grid(
            row=row, column=0, sticky="w", padx=8, pady=5
        )
        if values:
            widget = ttk.Combobox(
                parent,
                textvariable=self._var(key, default),
                values=values,
                state="readonly",
                width=18,
            )
        else:
            widget = tk.Entry(
                parent,
                textvariable=self._var(key, default),
                bg="#21262d",
                fg=c["fg"],
                insertbackground=c["fg"],
                relief=tk.FLAT,
                width=20,
            )
        widget.grid(row=row, column=1, sticky="ew", padx=8, pady=5)
        return widget

    def _build(self):
        c = self.COLORS

        self.banner = tk.Frame(self, bg="#238636", height=62)
        self.banner.pack(fill=tk.X)
        self.banner.pack_propagate(False)

        self.status_label = tk.Label(
            self.banner,
            text="READY",
            bg="#238636",
            fg="white",
            font=("Consolas", 22, "bold"),
        )
        self.status_label.pack(side=tk.LEFT, padx=24)

        self.clock = tk.Label(
            self.banner,
            text="",
            bg="#238636",
            fg="white",
            font=("Consolas", 12),
        )
        self.clock.pack(side=tk.RIGHT, padx=24)
        self._clock()

        body = tk.Frame(self, bg=c["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left = self._build_scrollable_left(body, width=430)

        right = tk.Frame(body, bg=c["bg"])
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        conn = tk.LabelFrame(left, text=" PSU Connection ", bg=c["panel"], fg=c["blue"])
        conn.pack(fill=tk.X, pady=(0, 8))

        ports = [p.device for p in list_ports.comports()] if SERIAL_PORT_ENUM_AVAILABLE else []
        default_port = "COM5" if "COM5" in ports else (ports[0] if ports else "COM5")

        self.port_box = self._add_entry(conn, 0, "COM port", "port", default_port, ports or ["COM3", "COM4", "COM5", "COM6"])
        self._add_entry(conn, 1, "Baud rate", "baudrate", "19200", ["9600", "19200", "38400", "57600", "115200"])
        self._add_entry(conn, 2, "Timeout (s)", "timeout", "1.0")

        tk.Button(
            conn,
            text="Refresh COM",
            command=self._refresh_ports,
            bg="#30363d",
            fg=c["fg"],
            relief=tk.FLAT,
        ).grid(row=3, column=0, columnspan=2, sticky="ew", padx=8, pady=4)

        tk.Button(
            conn,
            text="Test Connection",
            command=self._test_connection,
            bg="#1f6feb",
            fg="white",
            relief=tk.FLAT,
        ).grid(row=4, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 7))

        conn.columnconfigure(1, weight=1)

        seq = tk.LabelFrame(left, text=" Sequence Parameters ", bg=c["panel"], fg=c["blue"])
        seq.pack(fill=tk.X, pady=(0, 8))

        items = [
            ("VEXT ON target (V)", "vext_on", "5.0"),
            ("VIN phase1 (V)", "vin_p1", "8.0"),
            ("VIN phase2 (V)", "vin_p2", "12.0"),
            ("VIN phase3 (V)", "vin_p3", "17.0"),
            ("VCAP ON target (V)", "vcap_on", "35.0"),
            ("Step (V)", "step", "2.0"),
            ("Step interval (s)", "interval", "1.0"),
            ("Stable ON (s)", "stable_on", "0.3"),
            ("Stable OFF (s)", "stable_off", "0.2"),
            ("Hold time (s)", "hold_time", "0"),
            ("Monitor interval (s)", "monitor_interval", "5.0"),
            ("Alarm threshold (V)", "alarm_threshold", "0.5"),
        ]
        for row, item in enumerate(items):
            self._add_entry(seq, row, *item)
        seq.columnconfigure(1, weight=1)

        buttons = tk.Frame(left, bg=c["bg"])
        buttons.pack(fill=tk.X)

        self.start_btn = tk.Button(
            buttons,
            text="START",
            command=self._start,
            bg="#238636",
            fg="white",
            font=("Consolas", 12, "bold"),
            relief=tk.FLAT,
        )
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10, padx=(0, 4))

        self.stop_btn = tk.Button(
            buttons,
            text="STOP",
            command=self._stop,
            bg="#da3633",
            fg="white",
            font=("Consolas", 12, "bold"),
            relief=tk.FLAT,
            state=tk.DISABLED,
        )
        self.stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10, padx=(4, 0))

        cards = tk.Frame(right, bg=c["bg"])
        cards.pack(fill=tk.X, pady=(0, 8))

        channel_styles = [
            (PowerController.CH_VEXT, c["vext"]),
            (PowerController.CH_VIN, c["vin"]),
            (PowerController.CH_VCAP, c["vcap"]),
        ]
        for index, (channel, color) in enumerate(channel_styles):
            card = tk.Frame(cards, bg=c["panel"], highlightbackground=color, highlightthickness=2)
            pad = (0, 4) if index < 2 else (4, 0)
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=pad)

            tk.Label(
                card,
                text=CH_LABEL[channel],
                bg=c["panel"],
                fg=color,
                font=("Consolas", 14, "bold"),
            ).pack(pady=(8, 2))

            label = tk.Label(
                card,
                text="Set 0.00 V    Actual -- V",
                bg=c["panel"],
                fg=color,
                font=("Consolas", 12, "bold"),
            )
            label.pack(pady=(2, 10))
            self.labels[channel] = label

        log_frame = tk.LabelFrame(right, text=" Live Log ", bg=c["panel"], fg=c["blue"])
        log_frame.pack(fill=tk.X, pady=(0, 8))

        self.log_box = tk.Text(
            log_frame,
            height=12,
            bg="#0d1117",
            fg=c["fg"],
            font=("Consolas", 9),
            state=tk.DISABLED,
        )
        self.log_box.pack(fill=tk.BOTH, expand=True)

        for tag, color in [
            ("ok", c["green"]),
            ("warn", c["yellow"]),
            ("error", c["red"]),
            ("alarm", c["red"]),
            ("section", c["blue"]),
            ("detail", c["muted"]),
            ("info", c["fg"]),
        ]:
            self.log_box.tag_config(tag, foreground=color)

        chart_frame = tk.LabelFrame(right, text=" Voltage Trend ", bg=c["panel"], fg=c["blue"])
        chart_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(chart_frame, bg="#0d1117", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.canvas.bind("<Configure>", lambda _e: self._draw())

    def _refresh_ports(self):
        if not SERIAL_PORT_ENUM_AVAILABLE:
            messagebox.showwarning("Serial", "Port enumeration unavailable. Install pyserial.")
            return
        ports = [p.device for p in list_ports.comports()]
        self.port_box["values"] = ports
        if ports:
            self.variables["port"].set(ports[0])
        else:
            messagebox.showwarning("COM ports", "No COM ports found")

    def _test_connection(self):
        psu = None
        try:
            cfg = self._cfg()
            psu = PowerController(port=cfg["port"], baudrate=cfg["baudrate"], timeout=cfg["timeout"])
            psu.connect()
            ident = psu.identify()
            vin = psu.measure_voltage(PowerController.CH_VIN)
            vcap = psu.measure_voltage(PowerController.CH_VCAP)
            vext = psu.measure_voltage(PowerController.CH_VEXT)
            messagebox.showinfo(
                "Connection OK",
                f"Instrument: {ident}\n"
                f"Port: {cfg['port']} @ {cfg['baudrate']}bps\n"
                f"VIN={vin:.3f}V  VCAP={vcap:.3f}V  VEXT={vext:.3f}V",
            )
        except Exception as exc:
            messagebox.showerror("Connection Failed", str(exc))
        finally:
            if psu is not None:
                psu.disconnect()

    def _cfg(self):
        v = self.variables

        cfg = {
            "port": v["port"].get().strip(),
            "baudrate": int(v["baudrate"].get()),
            "timeout": float(v["timeout"].get()),
            "vext_on": float(v["vext_on"].get()),
            "vin_p1": float(v["vin_p1"].get()),
            "vin_p2": float(v["vin_p2"].get()),
            "vin_p3": float(v["vin_p3"].get()),
            "vcap_on": float(v["vcap_on"].get()),
            "step": float(v["step"].get()),
            "interval": float(v["interval"].get()),
            "stable_on": float(v["stable_on"].get()),
            "stable_off": float(v["stable_off"].get()),
            "hold_time": float(v["hold_time"].get()),
            "monitor_interval": float(v["monitor_interval"].get()),
            "alarm_threshold": float(v["alarm_threshold"].get()),
        }

        if not cfg["port"]:
            raise ValueError("COM port cannot be empty")
        if cfg["timeout"] <= 0:
            raise ValueError("Timeout must be > 0")
        if cfg["step"] <= 0:
            raise ValueError("Step must be > 0")
        if cfg["interval"] < 0:
            raise ValueError("Step interval must be >= 0")
        if cfg["stable_on"] <= 0 or cfg["stable_off"] <= 0:
            raise ValueError("Stable time must be > 0")
        if cfg["hold_time"] < 0:
            raise ValueError("Hold time must be >= 0")
        if cfg["monitor_interval"] <= 0:
            raise ValueError("Monitor interval must be > 0")
        if cfg["alarm_threshold"] <= 0:
            raise ValueError("Alarm threshold must be > 0")

        if not (0 <= cfg["vext_on"] <= PowerController.VEXT_MAX):
            raise ValueError(f"VEXT target out of range 0~{PowerController.VEXT_MAX}V")
        if not (0 <= cfg["vcap_on"] <= PowerController.VCAP_MAX):
            raise ValueError(f"VCAP target out of range 0~{PowerController.VCAP_MAX}V")
        if not (0 <= cfg["vin_p1"] <= PowerController.VIN_MAX):
            raise ValueError(f"VIN phase1 out of range 0~{PowerController.VIN_MAX}V")
        if not (0 <= cfg["vin_p2"] <= PowerController.VIN_MAX):
            raise ValueError(f"VIN phase2 out of range 0~{PowerController.VIN_MAX}V")
        if not (0 <= cfg["vin_p3"] <= PowerController.VIN_MAX):
            raise ValueError(f"VIN phase3 out of range 0~{PowerController.VIN_MAX}V")

        if not (cfg["vin_p1"] <= cfg["vin_p2"] <= cfg["vin_p3"]):
            raise ValueError("VIN phase voltage order must satisfy phase1 <= phase2 <= phase3")

        return cfg

    def _start(self):
        try:
            cfg = self._cfg()
        except Exception as exc:
            messagebox.showerror("Invalid configuration", str(exc))
            return

        summary = (
            f"Port: {cfg['port']} @ {cfg['baudrate']}bps\n"
            f"ON: VEXT={cfg['vext_on']}V, VIN={cfg['vin_p1']}->{cfg['vin_p2']}->{cfg['vin_p3']}V, "
            f"VCAP={cfg['vcap_on']}V\n"
            f"OFF: VIN {cfg['vin_p3']}->{cfg['vin_p2']}->{cfg['vin_p1']}->0V, "
            f"VCAP {cfg['vcap_on']}->0V, VEXT {cfg['vext_on']}->0V\n"
            f"Step={cfg['step']}V, interval={cfg['interval']}s, hold={cfg['hold_time']}s\n\n"
            "Start sequence?"
        )
        if not messagebox.askyesno("Confirm", summary):
            return

        self.log_box.config(state=tk.NORMAL)
        self.log_box.delete("1.0", tk.END)
        self.log_box.config(state=tk.DISABLED)

        self.start_time = None
        self.set_points.clear()
        self.actual_points = {
            PowerController.CH_VIN: [],
            PowerController.CH_VCAP: [],
            PowerController.CH_VEXT: [],
        }

        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        self.worker = PowerWorker(cfg, self.log_q, self.state_q, self.data_q, self.done_q)
        threading.Thread(target=self.worker.run, daemon=True).start()

    def _stop(self):
        if messagebox.askyesno("Stop", "Stop sequence and perform controlled power-down?"):
            if self.worker is not None:
                self.worker.stop_event.set()
            self.stop_btn.config(state=tk.DISABLED)

    def _poll(self):
        try:
            while True:
                text, color = self.state_q.get_nowait()
                self.banner.config(bg=color)
                self.status_label.config(text=text, bg=color)
                self.clock.config(bg=color)
        except queue.Empty:
            pass

        try:
            while True:
                stamp, text, tag = self.log_q.get_nowait()
                self.log_box.config(state=tk.NORMAL)
                self.log_box.insert(tk.END, f"[{stamp}] {text}\n", tag)
                self.log_box.see(tk.END)
                self.log_box.config(state=tk.DISABLED)
        except queue.Empty:
            pass

        dirty = False
        try:
            while True:
                item = self.data_q.get_nowait()
                kind = item[0]

                if kind == "set":
                    _, channel, value, stamp = item
                    if self.start_time is None:
                        self.start_time = stamp
                    elapsed = stamp - self.start_time

                    previous = self.set_points[-1][1:] if self.set_points else [0.0, 0.0, 0.0]
                    vin, vcap, vext = previous
                    if channel == PowerController.CH_VIN:
                        vin = value
                    elif channel == PowerController.CH_VCAP:
                        vcap = value
                    else:
                        vext = value
                    self.set_points.append([elapsed, vin, vcap, vext])
                    self._update_card(channel, set_value=value)

                elif kind == "actual":
                    _, channel, voltage, stamp = item
                    if self.start_time is None:
                        self.start_time = stamp
                    elapsed = stamp - self.start_time
                    self.actual_points[channel].append((elapsed, voltage))
                    self._update_card(channel, actual=voltage)

                elif kind == "alarm":
                    _, channel, _, _, _ = item
                    self.banner.config(bg="#b62324")
                    self.status_label.config(text=f"ALARM {CH_LABEL[channel]}", bg="#b62324")
                    self.clock.config(bg="#b62324")

                dirty = True
        except queue.Empty:
            pass

        if dirty:
            self._draw()

        try:
            self.done_q.get_nowait()
            self.running = False
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
        except queue.Empty:
            pass

        self.after(100, self._poll)

    def _update_card(self, channel, set_value=None, actual=None):
        if set_value is not None:
            setattr(self, f"_set_{channel}", set_value)
        if actual is not None:
            setattr(self, f"_actual_{channel}", actual)

        s = getattr(self, f"_set_{channel}", 0.0)
        a = getattr(self, f"_actual_{channel}", None)

        self.labels[channel].config(
            text=f"Set {s:.2f} V    Actual {'--' if a is None else f'{a:.3f}'} V"
        )

    def _draw(self):
        cv = self.canvas
        cv.delete("all")

        width, height = cv.winfo_width(), cv.winfo_height()
        if width < 100 or height < 100:
            return

        left, right, top, bottom = 55, 18, 18, 35
        plot_w, plot_h = width - left - right, height - top - bottom

        cv.create_rectangle(
            left,
            top,
            left + plot_w,
            top + plot_h,
            fill="#111827",
            outline="#30363d",
        )

        if not self.set_points and not any(self.actual_points.values()):
            cv.create_text(width / 2, height / 2, text="Waiting for data", fill="#8b949e")
            return

        all_times = [p[0] for p in self.set_points]
        for channel in self.actual_points:
            all_times.extend(t for t, _ in self.actual_points[channel])

        all_volts = []
        for p in self.set_points:
            # point format: [time, vin, vcap, vext]
            all_volts.extend([p[1], p[2], p[3]])
        for channel in self.actual_points:
            all_volts.extend(v for _, v in self.actual_points[channel])

        tmax = max(max(all_times), 1.0)
        vmax = max(max(all_volts), 1.0) * 1.1

        def to_x(t):
            return left + t / tmax * plot_w

        def to_y(v):
            return top + plot_h - v / vmax * plot_h

        for n in range(6):
            gy = top + plot_h * n / 5
            value = vmax * (5 - n) / 5
            cv.create_line(left, gy, left + plot_w, gy, fill="#30363d", dash=(3, 3))
            cv.create_text(left - 5, gy, text=f"{value:.0f}V", fill="#8b949e", anchor="e")

        def draw_line(points, color, dash=None):
            if len(points) < 2:
                return
            coords = [c for p in points[-1000:] for c in (to_x(p[0]), to_y(p[1]))]
            kwargs = {"fill": color, "width": 2}
            if dash:
                kwargs["dash"] = dash
            cv.create_line(*coords, **kwargs)

        # set lines
        draw_line([(p[0], p[1]) for p in self.set_points], self.COLORS["vin"])
        draw_line([(p[0], p[2]) for p in self.set_points], self.COLORS["vcap"])
        draw_line([(p[0], p[3]) for p in self.set_points], self.COLORS["vext"])

        # actual lines
        draw_line(self.actual_points[PowerController.CH_VIN], "#00ffcc", (6, 3))
        draw_line(self.actual_points[PowerController.CH_VCAP], "#ff6b6b", (6, 3))
        draw_line(self.actual_points[PowerController.CH_VEXT], "#e7d67a", (6, 3))

        cv.create_text(left + 8, top + 8, text="VIN set", fill=self.COLORS["vin"], anchor="nw")
        cv.create_text(left + 75, top + 8, text="VCAP set", fill=self.COLORS["vcap"], anchor="nw")
        cv.create_text(left + 165, top + 8, text="VEXT set", fill=self.COLORS["vext"], anchor="nw")

        cv.create_text(left + 255, top + 8, text="VIN actual", fill="#00ffcc", anchor="nw")
        cv.create_text(left + 350, top + 8, text="VCAP actual", fill="#ff6b6b", anchor="nw")
        cv.create_text(left + 455, top + 8, text="VEXT actual", fill="#e7d67a", anchor="nw")

    def _clock(self):
        self.clock.config(text=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.after(1000, self._clock)

    def _close(self):
        if self.running:
            messagebox.showwarning("Running", "Stop sequence and wait for controlled power-down before closing.")
            return
        self.destroy()


if __name__ == "__main__":
    PowerGuiApp().mainloop()

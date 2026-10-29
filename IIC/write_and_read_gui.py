import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "IIC" / "write_and_read.py"
ICON_ICO_PATH = PROJECT_ROOT / "IIC" / "solidigm.ico"
ICON_PNG_PATH = PROJECT_ROOT / "IIC" / "solidigm.png"


class IICGui:
    def __init__(self, root):
        self.root = root
        self.root.title("IIC Tool GUI")
        self.root.geometry("980x700")
        self._icon_img = None
        self._apply_window_icon()

        self.log_q = queue.Queue()
        self.proc = None

        self._build_ui()
        self.root.after(100, self._drain_log_queue)

    def _apply_window_icon(self):
        try:
            if ICON_ICO_PATH.exists():
                self.root.iconbitmap(str(ICON_ICO_PATH))
                return
            if ICON_PNG_PATH.exists():
                self._icon_img = tk.PhotoImage(file=str(ICON_PNG_PATH))
                self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(main)
        top.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(top, text=f"Script: {SCRIPT_PATH}").pack(side=tk.LEFT)
        ttk.Button(top, text="Clear Log", command=self._clear_log).pack(side=tk.RIGHT)

        card_row = ttk.Frame(main)
        card_row.pack(fill=tk.X)

        self._build_scan_card(card_row)
        self._build_write_card(card_row)
        self._build_read_card(card_row)

        log_frame = ttk.LabelFrame(main, text="Output")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=22)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.log_text.configure(state=tk.DISABLED)

    def _build_scan_card(self, parent):
        card = ttk.LabelFrame(parent, text="Scan")
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        self.scan_addr = tk.StringVar(value="0x33")
        self.scan_no_mux = tk.BooleanVar(value=False)
        self.scan_channels = tk.StringVar(value="")

        self._kv(card, "Addr", self.scan_addr)
        ttk.Checkbutton(card, text="No MUX", variable=self.scan_no_mux).pack(anchor=tk.W, padx=8, pady=2)
        self._kv(card, "Channels", self.scan_channels)

        ttk.Button(card, text="Run Scan", command=self._run_scan).pack(fill=tk.X, padx=8, pady=8)

    def _build_write_card(self, parent):
        card = ttk.LabelFrame(parent, text="Write")
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6)

        self.write_addr = tk.StringVar(value="0x33")
        self.write_reg = tk.StringVar(value="0x15")
        self.write_data = tk.StringVar(value="0x55")
        self.write_readback = tk.BooleanVar(value=False)

        self._kv(card, "Addr", self.write_addr)
        self._kv(card, "Reg", self.write_reg)
        self._kv(card, "Data", self.write_data)
        ttk.Checkbutton(card, text="Readback", variable=self.write_readback).pack(anchor=tk.W, padx=8, pady=2)

        ttk.Button(card, text="Run Write", command=self._run_write).pack(fill=tk.X, padx=8, pady=8)

    def _build_read_card(self, parent):
        card = ttk.LabelFrame(parent, text="Read")
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        self.read_reg = tk.StringVar(value="0x15")
        self.read_channels = tk.StringVar(value="")

        self._kv(card, "Reg(s)", self.read_reg)
        self._kv(card, "Channels", self.read_channels)

        ttk.Button(card, text="Run Read", command=self._run_read).pack(fill=tk.X, padx=8, pady=8)

    @staticmethod
    def _kv(parent, label, var):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=8, pady=3)
        ttk.Label(row, text=label, width=10).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _run_scan(self):
        args = ["scan", "--addr", self.scan_addr.get().strip()]
        if self.scan_no_mux.get():
            args.append("--no-mux")
        self._add_scan_channels_arg(args, self.scan_channels.get())
        self._run_command(args)

    def _run_write(self):
        args = [
            "write",
            "--addr", self.write_addr.get().strip(),
            "--reg", self.write_reg.get().strip(),
            "--data", self.write_data.get().strip(),
        ]
        if self.write_readback.get():
            args.append("--readback")
        self._run_command(args)

    def _run_read(self):
        args = ["read", "--reg", self.read_reg.get().strip()]
        self._add_scan_channels_arg(args, self.read_channels.get())
        self._run_command(args)

    @staticmethod
    def _add_optional_arg(args, key, value):
        text = value.strip()
        if text:
            args.extend([key, text])

    @staticmethod
    def _add_scan_channels_arg(args, channels):
        text = channels.strip()
        if text:
            text = ",".join(text.replace(",", " ").split())
            args.extend(["--channels", text])

    def _add_optional_channel_args(self, args, channel, channels):
        ch = channel.strip()
        chs = channels.strip()
        if ch and chs:
            raise ValueError("Channel and Channels cannot be set at the same time.")
        if ch:
            args.extend(["--channel", ch])
        elif chs:
            args.extend(["--channels", chs])

    def _run_command(self, cmd_args):
        if self.proc is not None:
            messagebox.showwarning("Busy", "A command is still running.")
            return
        if not SCRIPT_PATH.exists():
            messagebox.showerror("Error", f"Script not found:\n{SCRIPT_PATH}")
            return

        try:
            full_cmd = [sys.executable, str(SCRIPT_PATH)] + cmd_args
            self._append_log(f"> {' '.join(full_cmd)}\n")
            thread = threading.Thread(target=self._exec_worker, args=(full_cmd,), daemon=True)
            thread.start()
        except ValueError as exc:
            messagebox.showerror("Input Error", str(exc))

    def _exec_worker(self, full_cmd):
        try:
            self.proc = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(PROJECT_ROOT),
            )
            for line in self.proc.stdout:
                self.log_q.put(line)
            code = self.proc.wait()
            self.log_q.put(f"\n[GUI] Exit code: {code}\n")
        except Exception as exc:
            self.log_q.put(f"\n[GUI] Execute failed: {exc}\n")
        finally:
            self.proc = None

    def _drain_log_queue(self):
        while not self.log_q.empty():
            self._append_log(self.log_q.get())
        self.root.after(100, self._drain_log_queue)

    def _append_log(self, text):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)


def main():
    root = tk.Tk()
    IICGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()

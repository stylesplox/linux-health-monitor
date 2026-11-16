#!/usr/bin/env python3
"""
Linux Health Monitor - a Tkinter desktop app for Linux.

Live CPU, memory, disk, network and process stats via psutil,
plus a "Full Report" tab that runs health-report.sh.

Requirements:
    Ubuntu/Debian:     sudo apt install python3-tk python3-psutil
    RHEL/Fedora/Rocky: sudo dnf install python3-tkinter python3-psutil
    (or install psutil with: python3 -m pip install psutil)

Run:
    python3 health_monitor.py
"""

import datetime
import os
import shutil
import socket
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import psutil

REFRESH_MS = 2000          # how often the live tabs update
DISK_WARN = 80             # % used before a disk is flagged
MEM_WARN = 90              # % used before RAM is flagged
CPU_WARN = 90              # % used before CPU is flagged

# Look for health-report.sh next to this file
SCRIPT_FOLDER = os.path.dirname(os.path.abspath(__file__))
REPORT_SCRIPT = os.path.join(SCRIPT_FOLDER, "health-report.sh")

SKIP_FS = {"tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs"}


def human(number_of_bytes):
    """Convert a byte count to a readable size such as 512B or 1.5G."""
    size = number_of_bytes

    for unit in ("B", "K", "M", "G", "T", "P"):
        if abs(size) < 1024:
            if unit == "B":
                return f"{size:.0f}B"
            return f"{size:.1f}{unit}"

        size /= 1024

    return f"{size:.1f}E"


def fmt_uptime(seconds):
    """Show uptime in days, hours, and minutes."""
    days, remaining_seconds = divmod(int(seconds), 86400)
    hours, remaining_seconds = divmod(remaining_seconds, 3600)
    minutes, _ = divmod(remaining_seconds, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")

    return " ".join(parts)


class Meter(ttk.Frame):
    """A labelled progress bar with a percentage and detail text."""

    def __init__(self, parent, title, warn):
        super().__init__(parent)
        self.warn = warn
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text=title, width=10, font=("TkDefaultFont", 10, "bold")
                  ).grid(row=0, column=0, sticky="w")
        self.bar = ttk.Progressbar(self, maximum=100, style="Green.Horizontal.TProgressbar")
        self.bar.grid(row=0, column=1, sticky="ew", padx=8)
        self.pct = ttk.Label(self, text="0%", width=7, anchor="e")
        self.pct.grid(row=0, column=2)
        self.detail = ttk.Label(self, text="", foreground="gray40")
        self.detail.grid(row=1, column=1, sticky="w", padx=8)

    def set(self, percent, detail=""):
        self.bar["value"] = percent
        self.pct["text"] = f"{percent:.1f}%"
        self.detail["text"] = detail
        if percent >= self.warn:
            style = "Red.Horizontal.TProgressbar"
        elif percent >= self.warn - 20:
            style = "Amber.Horizontal.TProgressbar"
        else:
            style = "Green.Horizontal.TProgressbar"
        self.bar["style"] = style


class HealthMonitor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Linux Health Monitor - {socket.gethostname()}")
        self.geometry("900x620")
        self.minsize(720, 480)

        self._setup_styles()
        self._last_net = psutil.net_io_counters()
        self._last_net_time = time.time()
        psutil.cpu_percent(percpu=True)  # prime the CPU counters

        # Header
        header = ttk.Frame(self, padding=(12, 10, 12, 0))
        header.pack(fill="x")
        ttk.Label(header, text="Linux Health Monitor",
                  font=("TkDefaultFont", 14, "bold")).pack(side="left")
        self.status = ttk.Label(header, text="", foreground="gray40")
        self.status.pack(side="right")

        # Tabs
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)
        self._build_overview()
        self._build_disks()
        self._build_processes()
        self._build_report()

        self.refresh()

    # ------------------------------------------------------------ styles
    def _setup_styles(self):
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        meter_colors = (
            ("Green", "#2e9d4f"),
            ("Amber", "#e0a020"),
            ("Red", "#d64545"),
        )
        for name, color in meter_colors:
            style.configure(
                f"{name}.Horizontal.TProgressbar",
                background=color,
                troughcolor="#e6e6e6",
                bordercolor="#cccccc",
                lightcolor=color,
                darkcolor=color,
            )
        style.configure("Treeview", rowheight=24)
        style.configure("Warn.TLabel", foreground="#d64545")

    # ------------------------------------------------------------ overview tab
    def _build_overview(self):
        tab = ttk.Frame(self.tabs, padding=15)
        self.tabs.add(tab, text="Overview")
        tab.columnconfigure(0, weight=1)

        # System info
        info = ttk.LabelFrame(tab, text="System", padding=10)
        info.grid(row=0, column=0, sticky="ew")
        self.info_labels = {}
        info_fields = ("Host", "OS", "Kernel", "Uptime", "Load average")
        for index, field in enumerate(info_fields):
            row = index // 2
            column = (index % 2) * 2

            ttk.Label(info, text=f"{field}:", width=14).grid(
                row=row, column=column, sticky="w"
            )
            value_label = ttk.Label(info, text="-")
            value_label.grid(
                row=row, column=column + 1, sticky="w", padx=(0, 30)
            )
            self.info_labels[field] = value_label
        self.info_labels["Host"]["text"] = socket.gethostname()
        self.info_labels["OS"]["text"] = self._os_name()
        self.info_labels["Kernel"]["text"] = os.uname().release

        # Main meters
        usage = ttk.LabelFrame(tab, text="Usage", padding=10)
        usage.grid(row=1, column=0, sticky="ew", pady=10)
        usage.columnconfigure(0, weight=1)
        self.cpu_meter = Meter(usage, "CPU", CPU_WARN)
        self.cpu_meter.grid(row=0, column=0, sticky="ew", pady=4)
        self.mem_meter = Meter(usage, "Memory", MEM_WARN)
        self.mem_meter.grid(row=1, column=0, sticky="ew", pady=4)
        self.swap_meter = Meter(usage, "Swap", MEM_WARN)
        self.swap_meter.grid(row=2, column=0, sticky="ew", pady=4)
        self.net_label = ttk.Label(usage, text="Network: -")
        self.net_label.grid(row=3, column=0, sticky="w", pady=(8, 0))

        # Per-core bars
        cores = ttk.LabelFrame(tab, text="CPU cores", padding=10)
        cores.grid(row=2, column=0, sticky="ew")
        self.core_bars = []
        core_count = psutil.cpu_count() or 1
        cores_per_column = 8
        for core_number in range(core_count):
            column, row = divmod(core_number, cores_per_column)

            ttk.Label(cores, text=f"#{core_number}", width=4).grid(
                row=row, column=column * 3, sticky="w"
            )
            bar = ttk.Progressbar(
                cores, maximum=100, length=140,
                style="Green.Horizontal.TProgressbar"
            )
            bar.grid(row=row, column=column * 3 + 1, padx=4, pady=2)
            percent_label = ttk.Label(cores, text="0%", width=6)
            percent_label.grid(row=row, column=column * 3 + 2, padx=(0, 15))
            self.core_bars.append((bar, percent_label))

        # Warnings
        self.warn_label = ttk.Label(tab, text="", style="Warn.TLabel", justify="left")
        self.warn_label.grid(row=3, column=0, sticky="w", pady=(10, 0))

    @staticmethod
    def _os_name():
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        return os.uname().sysname

    # ------------------------------------------------------------ disks tab
    def _build_disks(self):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="Disks")
        columns = ("mount", "device", "type", "size", "used", "free", "pct")
        headings = ("Mount point", "Device", "Type", "Size", "Used", "Free", "Use %")
        widths = (180, 180, 70, 80, 80, 80, 70)
        self.disk_tree = ttk.Treeview(tab, columns=columns, show="headings")

        for column, heading, width in zip(columns, headings, widths):
            self.disk_tree.heading(column, text=heading)
            if column in ("mount", "device", "type"):
                alignment = "w"
            else:
                alignment = "e"
            self.disk_tree.column(column, width=width, anchor=alignment)
        self.disk_tree.tag_configure("warn", foreground="#d64545")
        self.disk_tree.pack(fill="both", expand=True)

        self.io_label = ttk.Label(tab, text="Disk I/O: -")
        self.io_label.pack(anchor="w", pady=(8, 0))
        self._last_io = psutil.disk_io_counters()

    # ------------------------------------------------------------ processes tab
    def _build_processes(self):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="Processes")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Sort by:").pack(side="left")
        self.sort_by = tk.StringVar(value="cpu")
        for text, val in (("CPU", "cpu"), ("Memory", "mem")):
            ttk.Radiobutton(bar, text=text, value=val, variable=self.sort_by,
                            command=self.update_processes).pack(side="left", padx=5)
        ttk.Label(bar, text="Filter:").pack(side="left", padx=(20, 4))
        self.proc_filter = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.proc_filter, width=20)
        entry.pack(side="left")
        entry.bind("<KeyRelease>", lambda e: self.update_processes())
        self.proc_count = ttk.Label(bar, text="", foreground="gray40")
        self.proc_count.pack(side="right")

        columns = ("pid", "user", "cpu", "mem", "rss", "name")
        headings = ("PID", "User", "CPU %", "Mem %", "Memory", "Name")
        widths = (70, 110, 70, 70, 90, 300)
        frame = ttk.Frame(tab)
        frame.pack(fill="both", expand=True)
        self.proc_tree = ttk.Treeview(frame, columns=columns, show="headings")

        for column, heading, width in zip(columns, headings, widths):
            self.proc_tree.heading(column, text=heading)
            if column in ("user", "name"):
                alignment = "w"
            else:
                alignment = "e"
            self.proc_tree.column(column, width=width, anchor=alignment)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.proc_tree.yview)
        self.proc_tree.configure(yscrollcommand=sb.set)
        self.proc_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        for p in psutil.process_iter():   # prime per-process CPU counters
            try:
                p.cpu_percent(None)
            except psutil.Error:
                pass

    # ------------------------------------------------------------ report tab
    def _build_report(self):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="Full Report")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 8))
        self.run_btn = ttk.Button(bar, text="Run report", command=self.run_report)
        self.run_btn.pack(side="left")
        self.as_root = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Run as administrator (asks for password)",
                        variable=self.as_root).pack(side="left", padx=10)
        ttk.Button(bar, text="Save as...", command=self.save_report).pack(side="right")
        self.report_status = ttk.Label(bar, text="", foreground="gray40")
        self.report_status.pack(side="right", padx=10)

        frame = ttk.Frame(tab)
        frame.pack(fill="both", expand=True)
        self.report_text = tk.Text(frame, wrap="none", font=("Monospace", 10),
                                   bg="#1e1e1e", fg="#dcdcdc", insertbackground="white")
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.report_text.yview)
        xs = ttk.Scrollbar(frame, orient="horizontal", command=self.report_text.xview)
        self.report_text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.report_text.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.report_text.tag_configure("warn", foreground="#ff6b6b")
        self.report_text.insert(
            "1.0", f"Click 'Run report' to run:\n  {REPORT_SCRIPT}\n"
        )

    def run_report(self):
        if not os.path.isfile(REPORT_SCRIPT):
            messagebox.showerror("Script not found",
                                 f"Could not find:\n{REPORT_SCRIPT}\n\n"
                                 "Put health-report.sh in the same folder as this app.")
            return
        command = ["bash", REPORT_SCRIPT]
        if self.as_root.get() and os.geteuid() != 0:
            if shutil.which("pkexec"):
                command = ["pkexec", "bash", REPORT_SCRIPT]
            else:
                messagebox.showwarning(
                    "pkexec not found",
                    "pkexec is not installed, running without admin rights."
                )

        self.run_btn["state"] = "disabled"
        self.report_status["text"] = "Running..."
        worker = threading.Thread(
            target=self._report_worker, args=(command,), daemon=True
        )
        worker.start()

    def _report_worker(self, command):
        """Run the Bash report without freezing the application window."""
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=180
            )
            output = result.stdout or ""
            if result.returncode in (126, 127) and not output:
                output = "Authentication was cancelled or failed.\n" + result.stderr
        except subprocess.TimeoutExpired:
            output = "The report took too long and was stopped.\n"
        except Exception as error:
            output = f"Error running report: {error}\n"

        self.after(0, self._show_report, output)

    def _show_report(self, text):
        self.report_text.delete("1.0", "end")
        for line in text.splitlines(keepends=True):
            if "WARNING" in line:
                tag = "warn"
            else:
                tag = ()
            self.report_text.insert("end", line, tag)
        self.run_btn["state"] = "normal"
        self.report_status["text"] = f"Last run {datetime.datetime.now():%H:%M:%S}"

    def save_report(self):
        text = self.report_text.get("1.0", "end").strip()
        if not text:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"health-report-{datetime.date.today()}.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            with open(path, "w") as f:
                f.write(text + "\n")
            self.report_status["text"] = f"Saved to {os.path.basename(path)}"

    # ------------------------------------------------------------ refresh loop
    def refresh(self):
        try:
            self.update_overview()
            self.update_disks()
            self.update_processes()
            self.status["text"] = f"Updated {datetime.datetime.now():%H:%M:%S}"
        except Exception as e:  # keep the loop alive no matter what
            self.status["text"] = f"Update error: {e}"
        self.after(REFRESH_MS, self.refresh)

    def update_overview(self):
        warnings = []

        # Overall CPU usage and usage for each individual core.
        core_percentages = psutil.cpu_percent(percpu=True)
        if core_percentages:
            cpu_percent = sum(core_percentages) / len(core_percentages)
        else:
            cpu_percent = 0

        frequency = psutil.cpu_freq()
        frequency_text = ""
        if frequency and frequency.current:
            frequency_text = f" @ {frequency.current / 1000:.2f} GHz"

        self.cpu_meter.set(
            cpu_percent, f"{len(core_percentages)} cores{frequency_text}"
        )
        for (bar, label), percent in zip(self.core_bars, core_percentages):
            bar["value"] = percent
            label["text"] = f"{percent:.0f}%"

            if percent >= CPU_WARN:
                color = "Red"
            elif percent >= CPU_WARN - 20:
                color = "Amber"
            else:
                color = "Green"
            bar["style"] = f"{color}.Horizontal.TProgressbar"

        if cpu_percent >= CPU_WARN:
            warnings.append(f"CPU usage is {cpu_percent:.0f}%")

        mem = psutil.virtual_memory()
        used = mem.total - mem.available
        self.mem_meter.set(mem.percent, f"{human(used)} used of {human(mem.total)}  "
                                        f"({human(mem.available)} available)")
        if mem.percent >= MEM_WARN:
            warnings.append(f"Memory usage is {mem.percent:.0f}%")

        swap = psutil.swap_memory()
        if swap.total:
            self.swap_meter.set(swap.percent, f"{human(swap.used)} used of {human(swap.total)}")
        else:
            self.swap_meter.set(0, "No swap configured")

        load_averages = os.getloadavg()
        core_count = psutil.cpu_count() or 1
        self.info_labels["Load average"]["text"] = "  ".join(
            f"{average:.2f}" for average in load_averages
        )
        self.info_labels["Uptime"]["text"] = fmt_uptime(
            time.time() - psutil.boot_time()
        )
        if load_averages[1] > core_count:
            warnings.append(
                f"5-min load ({load_averages[1]:.2f}) is higher than core count ({core_count})"
            )

        # Calculate network speeds from the change since the last refresh.
        current_time = time.time()
        network = psutil.net_io_counters()
        elapsed_seconds = max(current_time - self._last_net_time, 0.001)
        upload_speed = (network.bytes_sent - self._last_net.bytes_sent) / elapsed_seconds
        download_speed = (network.bytes_recv - self._last_net.bytes_recv) / elapsed_seconds
        self._last_net = network
        self._last_net_time = current_time

        self.net_label["text"] = (
            f"Network:  ↓ {human(download_speed)}/s   ↑ {human(upload_speed)}/s     "
            f"(total ↓ {human(network.bytes_recv)}  ↑ {human(network.bytes_sent)})"
        )

        for partition in self._partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                if usage.percent >= DISK_WARN:
                    warnings.append(
                        f"Disk {partition.mountpoint} is {usage.percent:.0f}% full"
                    )
            except OSError:
                pass

        self.warn_label["text"] = "\n".join("⚠ " + w for w in warnings)

    @staticmethod
    def _partitions():
        seen_mountpoints = set()
        for partition in psutil.disk_partitions(all=False):
            if partition.fstype in SKIP_FS:
                continue
            if partition.mountpoint in seen_mountpoints:
                continue
            if partition.mountpoint.startswith("/snap"):
                continue

            seen_mountpoints.add(partition.mountpoint)
            yield partition

    def update_disks(self):
        self.disk_tree.delete(*self.disk_tree.get_children())
        for partition in self._partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except OSError:
                continue

            if usage.percent >= DISK_WARN:
                tag = ("warn",)
            else:
                tag = ()

            self.disk_tree.insert(
                "", "end", tags=tag,
                values=(
                    partition.mountpoint, partition.device, partition.fstype,
                    human(usage.total), human(usage.used), human(usage.free),
                    f"{usage.percent:.0f}%",
                ),
            )

        # Disk read/write speeds since the previous refresh.
        disk_io = psutil.disk_io_counters()
        if disk_io and self._last_io:
            elapsed_seconds = REFRESH_MS / 1000
            read_speed = (disk_io.read_bytes - self._last_io.read_bytes) / elapsed_seconds
            write_speed = (disk_io.write_bytes - self._last_io.write_bytes) / elapsed_seconds
            self.io_label["text"] = (
                f"Disk I/O:  read {human(read_speed)}/s   write {human(write_speed)}/s"
            )
        self._last_io = disk_io

    def update_processes(self):
        sort_by = self.sort_by.get()
        filter_text = self.proc_filter.get().lower().strip()
        rows = []

        for process in psutil.process_iter(
            ["pid", "username", "name", "memory_percent", "memory_info"]
        ):
            try:
                info = process.info
                name = info["name"] or ""
                pid = info["pid"]

                # A filter matches a process name or its exact PID.
                if filter_text:
                    name_matches = filter_text in name.lower()
                    pid_matches = filter_text == str(pid)
                    if not name_matches and not pid_matches:
                        continue

                memory_info = info["memory_info"]
                if memory_info:
                    resident_memory = memory_info.rss
                else:
                    resident_memory = 0

                rows.append((
                    pid,
                    info["username"] or "?",
                    process.cpu_percent(None),
                    info["memory_percent"] or 0.0,
                    resident_memory,
                    name,
                ))
            except psutil.Error:
                continue

        # Row positions: PID=0, user=1, CPU%=2, memory%=3, RSS=4, name=5.
        if sort_by == "cpu":
            sort_column = 2
        else:
            sort_column = 3
        rows.sort(key=lambda row: row[sort_column], reverse=True)

        # Keep the scrollbar in the same place while the table updates.
        scroll_position = self.proc_tree.yview()[0]
        self.proc_tree.delete(*self.proc_tree.get_children())
        for pid, user, cpu, memory_percent, resident_memory, name in rows[:200]:
            self.proc_tree.insert(
                "", "end",
                values=(
                    pid, user, f"{cpu:.1f}", f"{memory_percent:.1f}",
                    human(resident_memory), name,
                ),
            )
        self.proc_tree.yview_moveto(scroll_position)
        self.proc_count["text"] = f"{len(rows)} processes"


if __name__ == "__main__":
    HealthMonitor().mainloop()

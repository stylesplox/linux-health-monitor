# Linux Health Monitor

A Linux system health monitoring tool with a desktop interface for live CPU, memory, disk, network, and process statistics, and a CLI script that generates detailed health reports. The script can be run on its own from the command line, or from the desktop app’s Full Report tab. Both warn when system resources reach predefined thresholds.

Works on **Red Hat** family systems (RHEL, Fedora, Rocky, Alma, CentOS) and **Debian** family systems (Ubuntu, Debian).

## Requirements

**Ubuntu / Debian**

```bash
sudo apt install python3 python3-tk python3-psutil
```

**RHEL / Fedora / Rocky / Alma**

```bash
sudo dnf install python3 python3-tkinter python3-psutil
```

> 
> **Note:** `health_monitor.py` and `health-report.sh` must be in the same folder.

## Run

```bash
python3 health_monitor.py
```

The report script can also be run on its own from the terminal:

```bash
chmod +x health-report.sh
sudo ./health-report.sh               # print to screen
sudo ./health-report.sh > report.txt  # save to a file
```

## Tabs

**Overview**
Shows live CPU, memory and network usage, and warns you when anything runs too high.

**Disks**
Shows how much storage space is used and free on each drive, and flags any drive that's over 80% full.

**Processes**
Lists running programs and how much CPU and memory each uses.

**Full Report**
Runs `health-report.sh` and shows the results of all its health checks together in one text report.

## What the full report checks

- System info: host, OS, kernel, uptime
- CPU usage and load average
- Memory usage
- Disk and inode usage
- Top 5 processes by CPU and by memory
- Failed services
- Network interfaces and listening ports
- Errors from the last 24 hours
- Logged-in users and recent failed logins
- Available updates

Threshold problems are marked with `WARNING`, which shows in red in the app.



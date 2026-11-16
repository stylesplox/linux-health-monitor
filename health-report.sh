#!/usr/bin/env bash
# Linux Health Report for Linux.
# Usage:  sudo ./health-report.sh            (prints to screen)
#         sudo ./health-report.sh > report.txt

# Warning thresholds (percent)
DISK_WARN=80
MEM_WARN=90

# Print a separator line and a section title.
line() {
    printf '%*s\n' 60 '' | tr ' ' '='
}

section() {
    echo
    line
    echo " $1"
    line
}

# ------------------------------------------------------------ SYSTEM
echo "LINUX HEALTH REPORT"
echo "Host:      $(hostname)"
echo "Date:      $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "OS:        $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
echo "Kernel:    $(uname -r)"
echo "Uptime:    $(uptime -p)"

# ------------------------------------------------------------ CPU
section "CPU"

CORES=$(nproc)
read -r L1 L5 L15 _ < /proc/loadavg

echo "Cores:        $CORES"
echo "Load average: $L1 (1m)  $L5 (5m)  $L15 (15m)"

# Read CPU counters twice, one second apart.
# The fields used are: user, nice, system, idle, iowait, irq, softirq.
read -r _ user nice system idle iowait irq softirq _ < /proc/stat
TOTAL1=$((user + nice + system + idle + iowait + irq + softirq))
IDLE1=$((idle + iowait))

sleep 1

read -r _ user nice system idle iowait irq softirq _ < /proc/stat
TOTAL2=$((user + nice + system + idle + iowait + irq + softirq))
IDLE2=$((idle + iowait))

# Only the changes in CPU time between readings matter.
TOTAL_CHANGE=$((TOTAL2 - TOTAL1))
IDLE_CHANGE=$((IDLE2 - IDLE1))

CPU_USED=$(
    awk -v total="$TOTAL_CHANGE" -v idle="$IDLE_CHANGE" 'BEGIN {
        if (total != 0) {
            printf "%.1f", (1 - idle / total) * 100
        } else {
            printf "%.1f", 0
        }
    }'
)
echo "CPU used:     ${CPU_USED}%"

awk -v load="$L5" -v cores="$CORES" 'BEGIN {
    if (load > cores) {
        print "WARNING: 5-min load is higher than core count"
    }
}'

# ------------------------------------------------------------ MEMORY
section "MEMORY"

free -h
MEM_PCT=$(free | awk '/Mem:/ {
    printf "%.0f", ($2 - $7) / $2 * 100
}')
echo "RAM used: ${MEM_PCT}%"

if [ "$MEM_PCT" -ge "$MEM_WARN" ]; then
    echo "WARNING: RAM usage above ${MEM_WARN}%"
fi

# ------------------------------------------------------------ DISK USAGE
section "DISK USAGE"

# Exclude temporary and container-style filesystems from the report.
df -hT -x tmpfs -x devtmpfs -x squashfs -x overlay

df -P -x tmpfs -x devtmpfs -x squashfs -x overlay | awk -v warn="$DISK_WARN" 'NR > 1 {
    gsub("%", "", $5)
    if ($5 + 0 >= warn) {
        printf "WARNING: %s is %s%% full\n", $6, $5
    }
}'

echo
echo "Inode usage above ${DISK_WARN}%:"

df -iP -x tmpfs -x devtmpfs -x squashfs -x overlay | awk -v warn="$DISK_WARN" 'NR > 1 {
    gsub("%", "", $5)
    if ($5 + 0 >= warn) {
        printf "  %s %s%%\n", $6, $5
    }
}'

# ------------------------------------------------------------ PROCESSES
section "TOP 5 PROCESSES BY CPU"
ps -eo pid,user,%cpu,%mem,comm --sort=-%cpu | head -6

section "TOP 5 PROCESSES BY MEMORY"
ps -eo pid,user,%cpu,%mem,comm --sort=-%mem | head -6

# ------------------------------------------------------------ SERVICES
section "FAILED SERVICES"

if command -v systemctl > /dev/null; then
    FAILED=$(systemctl --failed --no-legend --plain 2>/dev/null)

    if [ -z "$FAILED" ]; then
        echo "None"
    else
        echo "$FAILED"
    fi
fi

# ------------------------------------------------------------ NETWORK
section "NETWORK"
ip -brief address 2>/dev/null
echo
echo "Listening ports:"
ss -tulnH 2>/dev/null | awk '{print "  " $1, $5}' | sort -u

# ------------------------------------------------------------ ERRORS
section "RECENT ERRORS (last 24h, up to 15)"

if command -v journalctl > /dev/null; then
    journalctl -p err --since "24 hours ago" --no-pager -q | tail -15
fi

# ------------------------------------------------------------ LOGINS
section "LOGINS"
echo "Logged in now:"
who

echo
echo "Recent failed logins:"
(lastb -n 5 2>/dev/null || echo "  (needs sudo)") | head -6

# ------------------------------------------------------------ UPDATES
section "UPDATES"

if command -v apt > /dev/null; then
    UPDATES=$(apt list --upgradable 2>/dev/null | grep -c upgradable)
    echo "Upgradable packages: $UPDATES"
elif command -v dnf > /dev/null; then
    UPDATES=$(dnf -q check-update 2>/dev/null | grep -c '^[a-zA-Z0-9]')
    echo "Upgradable packages: $UPDATES"
fi

if [ -f /var/run/reboot-required ]; then
    echo "WARNING: reboot required"
fi

# ------------------------------------------------------------ END
echo
line
echo " End of report"
line

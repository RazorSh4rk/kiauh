# ======================================================================= #
#  Copyright (C) 2020 - 2026 Dominik Willner <dev.dw-0@proton.me>         #
#                                                                         #
#  This file is part of KIAUH - Klipper Installation And Update Helper    #
#  https://github.com/dw-0/kiauh                                          #
#                                                                         #
#  This file may be distributed under the terms of the GNU GPLv3 license  #
# ======================================================================= #

from pathlib import Path
from subprocess import PIPE, CalledProcessError, run
from typing import List

from core.logger import DialogType, Logger
from utils.common import check_install_dependencies, get_current_date
from utils.fs_utils import check_file_exist
from utils.input_utils import get_confirm, get_string_input
from utils.sys_utils import cmd_sysctl_manage, cmd_sysctl_service, create_service_file

# Services that provide no benefit on a headless, single purpose print host and
# only consume CPU and RAM. Each one is skipped when it is not present.
OPTIMIZE_DISABLE_SERVICES = ("bluetooth", "hciuart", "triggerhappy")

# Oneshot unit that pins the CPU governor to "performance" on every boot.
# Klipper depends on consistent step timing, which on-demand scaling harms.
CPU_GOVERNOR_SERVICE_NAME = "cpu-governor.service"
CPU_GOVERNOR_UNIT = """\
[Unit]
Description=Set CPU scaling governor to performance
After=multi-user.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do [ -e "$f" ] && echo performance > "$f"; done || true'

[Install]
WantedBy=multi-user.target
"""


def change_system_hostname() -> None:
    """
    Procedure to change the system hostname.
    :return:
    """

    Logger.print_dialog(
        DialogType.CUSTOM,
        [
            "Changing the hostname of this system allows you to access an installed "
            "webinterface by simply typing the hostname like this in the browser:",
            "\n\n",
            "http://<hostname>.local",
            "\n\n",
            "Example: If you set your hostname to 'my-printer', you can access an "
            "installed webinterface by typing 'http://my-printer.local' in the "
            "browser.",
        ],
        custom_title="CHANGE SYSTEM HOSTNAME",
    )
    if not get_confirm("Do you want to change the hostname?", default_choice=False):
        return

    Logger.print_dialog(
        DialogType.CUSTOM,
        [
            "Allowed characters: a-z, 0-9 and '-'",
            "The name must not contain the following:",
            "\n\n",
            "● Any special characters",
            "● No leading or trailing '-'",
        ],
    )
    hostname = get_string_input(
        "Enter the new hostname",
        regex=r"^[a-z0-9]+([a-z0-9-]*[a-z0-9])?$",
    )
    if not get_confirm(f"Change the hostname to '{hostname}'?", default_choice=False):
        Logger.print_info("Aborting hostname change ...")
        return

    try:
        Logger.print_status("Changing hostname ...")

        Logger.print_status("Checking for dependencies ...")
        check_install_dependencies({"avahi-daemon"}, include_global=False)

        # create or backup hosts file
        Logger.print_status("Creating backup of hosts file ...")
        hosts_file = Path("/etc/hosts")
        if not check_file_exist(hosts_file, True):
            cmd = ["sudo", "touch", hosts_file.as_posix()]
            run(cmd, stderr=PIPE, check=True)
        else:
            date_time = get_current_date()
            name = f"hosts.{date_time.get('date')}-{date_time.get('time')}.bak"
            hosts_file_backup = Path(f"/etc/{name}")
            cmd = [
                "sudo",
                "cp",
                hosts_file.as_posix(),
                hosts_file_backup.as_posix(),
            ]
            run(cmd, stderr=PIPE, check=True)
        Logger.print_ok()

        # call hostnamectl set-hostname <hostname>
        Logger.print_status(f"Setting hostname to '{hostname}' ...")
        cmd = ["sudo", "hostnamectl", "set-hostname", hostname]
        run(cmd, stderr=PIPE, check=True)
        Logger.print_ok()

        # add hostname to hosts file at the end of the file
        Logger.print_status("Writing new hostname to /etc/hosts ...")
        stdin = f"127.0.0.1       {hostname}\n"
        cmd = ["sudo", "tee", "-a", hosts_file.as_posix()]
        run(cmd, input=stdin.encode(), stderr=PIPE, stdout=PIPE, check=True)
        Logger.print_ok()

        Logger.print_ok("New hostname successfully configured!")
        Logger.print_ok("Remember to reboot for the changes to take effect!\n")

    except CalledProcessError as e:
        Logger.print_error(f"Error during change hostname procedure: {e}")
        return


def apply_linux_optimizations(interactive: bool = True) -> bool:
    """
    Apply the system level tweaks that make KIAUH viable on a low resource host
    (e.g. a Raspberry Pi Zero W). Disables services that a headless print host
    does not need and pins the CPU governor to 'performance'.

    Every step is best effort: a service that is missing or refuses to be
    disabled is reported and skipped instead of aborting the whole procedure.

    :param interactive: when True, the user is shown the planned changes and has
        to confirm them. When False, the changes are applied without prompting.
    :return: True when the changes were applied, False when the user declined.
    """
    disable = [s for s in OPTIMIZE_DISABLE_SERVICES if _service_exists(s)]
    has_governor = bool(_governor_files())

    if interactive:
        Logger.print_dialog(
            DialogType.CUSTOM,
            [
                "Optimizing this system for low resource hardware. The following "
                "changes will be applied:",
                "\n\n",
                *[f"● Disable the '{s}' service" for s in disable],
                *(
                    ["● Pin the CPU governor to 'performance' on every boot"]
                    if has_governor
                    else []
                ),
                "\n\n",
                "Enabling this also skips the optional Moonraker speedups and "
                "omits gzip from newly generated NGINX configs.",
            ],
            custom_title="Optimize Installation",
        )
        if not get_confirm("Apply these optimizations?", default_choice=False):
            Logger.print_info("Optimization skipped ...")
            return False

    for service in disable:
        _disable_service(service)

    _set_cpu_governor()

    Logger.print_ok("System optimized for low resource hardware!", start="\n")
    return True


def _service_exists(name: str) -> bool:
    """Check whether systemd knows a unit called '<name>.service'."""
    result = run(
        ["systemctl", "list-unit-files", f"{name}.service"],
        stdout=PIPE,
        stderr=PIPE,
        text=True,
    )
    return f"{name}.service" in result.stdout


def _governor_files() -> List[Path]:
    """Return the per core cpufreq governor files, if the system has any."""
    return sorted(Path("/sys/devices/system/cpu").glob("cpu*/cpufreq/scaling_governor"))


def _disable_service(name: str) -> None:
    try:
        Logger.print_status(f"Disabling the '{name}' service ...")
        cmd_sysctl_service(name, "disable")
        cmd_sysctl_service(name, "stop")
        Logger.print_ok(f"'{name}' disabled.")
    except CalledProcessError as e:
        Logger.print_warn(f"Unable to disable '{name}': {e}")


def _set_cpu_governor() -> None:
    if not _governor_files():
        Logger.print_info("No CPU frequency scaling available. Skipped ...")
        return

    try:
        Logger.print_status("Setting the CPU governor to 'performance' ...")
        create_service_file(CPU_GOVERNOR_SERVICE_NAME, CPU_GOVERNOR_UNIT)
        cmd_sysctl_manage("daemon-reload")
        cmd_sysctl_service(CPU_GOVERNOR_SERVICE_NAME, "enable")
        cmd_sysctl_service(CPU_GOVERNOR_SERVICE_NAME, "start")
        Logger.print_ok("CPU governor set to 'performance'.")
    except CalledProcessError as e:
        Logger.print_warn(f"Unable to set the CPU governor: {e}")

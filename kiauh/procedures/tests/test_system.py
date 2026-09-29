# ======================================================================= #
#  Copyright (C) 2020 - 2026 Dominik Willner <dev.dw-0@proton.me>         #
#                                                                         #
#  This file is part of KIAUH - Klipper Installation And Update Helper    #
#  https://github.com/dw-0/kiauh                                          #
#                                                                         #
#  This file may be distributed under the terms of the GNU GPLv3 license  #
# ======================================================================= #

from __future__ import annotations

from pathlib import Path
from subprocess import CalledProcessError
from typing import Dict, List, Sequence

import pytest
from procedures import system
from procedures.system import (
    CPU_GOVERNOR_SERVICE_NAME,
    apply_linux_optimizations,
)

GOVERNOR_FILE = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")


def patch_environment(
    monkeypatch: pytest.MonkeyPatch,
    *,
    present: Sequence[str] = (),
    confirm: bool = True,
    governor_files: bool = True,
    failing: Sequence[str] = (),
) -> Dict[str, List]:
    """Wire the system module up to recording fakes and return the recordings."""
    rec: Dict[str, List] = {"sysctl": [], "created": [], "daemon_reload": []}

    monkeypatch.setattr(system, "_service_exists", lambda name: name in present)
    monkeypatch.setattr(
        system,
        "_governor_files",
        lambda: [GOVERNOR_FILE] if governor_files else [],
    )
    monkeypatch.setattr(system, "get_confirm", lambda *a, **k: confirm)
    monkeypatch.setattr(
        system, "create_service_file", lambda name, content: rec["created"].append(name)
    )
    monkeypatch.setattr(
        system, "cmd_sysctl_manage", lambda action: rec["daemon_reload"].append(action)
    )

    def fake_sysctl(name: str, action: str) -> None:
        if name in failing:
            raise CalledProcessError(1, ["systemctl", action, name], stderr=b"boom")
        rec["sysctl"].append((name, action))

    monkeypatch.setattr(system, "cmd_sysctl_service", fake_sysctl)
    return rec


def disabled_services(rec: Dict[str, List]) -> List[str]:
    return [name for name, action in rec["sysctl"] if action == "disable"]


class TestDeclined:
    def test_returns_false_and_changes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = patch_environment(
            monkeypatch, present=["bluetooth", "hciuart"], confirm=False
        )

        assert apply_linux_optimizations() is False
        assert rec["sysctl"] == []
        assert rec["created"] == []


class TestServiceDisabling:
    def test_disables_only_present_services(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = patch_environment(monkeypatch, present=["bluetooth", "hciuart"])

        assert apply_linux_optimizations() is True

        # triggerhappy is not present on this system, so it must not be touched
        assert sorted(disabled_services(rec)) == ["bluetooth", "hciuart"]

    def test_a_failing_service_does_not_abort_the_rest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = patch_environment(
            monkeypatch,
            present=["bluetooth", "hciuart"],
            failing=["bluetooth"],
        )

        assert apply_linux_optimizations() is True
        assert disabled_services(rec) == ["hciuart"]


class TestCpuGovernor:
    def test_skipped_when_no_frequency_scaling_is_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = patch_environment(monkeypatch, governor_files=False)

        apply_linux_optimizations()

        assert rec["created"] == []

    def test_installs_and_starts_a_oneshot_unit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = patch_environment(monkeypatch)

        apply_linux_optimizations()

        assert rec["created"] == [CPU_GOVERNOR_SERVICE_NAME]
        assert (CPU_GOVERNOR_SERVICE_NAME, "enable") in rec["sysctl"]
        assert (CPU_GOVERNOR_SERVICE_NAME, "start") in rec["sysctl"]
        assert rec["daemon_reload"] == ["daemon-reload"]

    def test_governor_content_sets_performance(self) -> None:
        assert "performance" in system.CPU_GOVERNOR_UNIT
        assert "scaling_governor" in system.CPU_GOVERNOR_UNIT
        assert "WantedBy=multi-user.target" in system.CPU_GOVERNOR_UNIT


class TestServiceExists:
    def test_detects_unit_in_systemctl_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Result:
            stdout = "bluetooth.service enabled enabled\n"

        monkeypatch.setattr(system, "run", lambda *a, **k: Result())
        assert system._service_exists("bluetooth") is True

    def test_reports_missing_unit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Result:
            stdout = "0 unit files listed.\n"

        monkeypatch.setattr(system, "run", lambda *a, **k: Result())
        assert system._service_exists("triggerhappy") is False

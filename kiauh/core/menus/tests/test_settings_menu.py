# ======================================================================= #
#  Copyright (C) 2020 - 2026 Dominik Willner <dev.dw-0@proton.me>         #
#                                                                         #
#  This file is part of KIAUH - Klipper Installation And Update Helper    #
#  https://github.com/dw-0/kiauh                                          #
#                                                                         #
#  This file may be distributed under the terms of the GNU GPLv3 license  #
# ======================================================================= #

from __future__ import annotations

import pytest
from core.menus.settings_menu import SettingsMenu


@pytest.fixture
def patched_settings_menu(monkeypatch: pytest.MonkeyPatch) -> SettingsMenu:
    class FakeRepo:
        def __init__(self):
            self.repositories = []

    class FakeKiauh:
        backup_before_update = True
        optimize_install = False

    class FakeSettings:
        kiauh = FakeKiauh()
        mainsail = type("M", (), {"unstable_releases": False})()
        fluidd = type("F", (), {"unstable_releases": False})()
        klipper = FakeRepo()
        moonraker = FakeRepo()

        def save(self) -> None:
            pass

    monkeypatch.setattr(
        "core.menus.settings_menu.KiauhSettings", lambda: FakeSettings()
    )
    monkeypatch.setattr(
        "core.menus.settings_menu.get_klipper_status",
        lambda: type("S", (), {"repo": None, "repo_url": "", "branch": ""})(),
    )
    monkeypatch.setattr(
        "core.menus.settings_menu.get_moonraker_status",
        lambda: type("S", (), {"repo": None, "repo_url": "", "branch": ""})(),
    )

    return SettingsMenu()


class TestSettingsMenuConstruction:
    def test_options_cover_settings(self, patched_settings_menu: SettingsMenu) -> None:
        assert {"1", "2", "3", "4", "5", "6"}.issubset(patched_settings_menu.options)

    def test_loads_backup_setting(self, patched_settings_menu: SettingsMenu) -> None:
        assert patched_settings_menu.auto_backups_enabled is True

    def test_loads_optimize_setting(self, patched_settings_menu: SettingsMenu) -> None:
        assert patched_settings_menu.optimize_install is False


class TestToggleMethods:
    def test_toggle_mainsail_release(self, patched_settings_menu: SettingsMenu) -> None:
        patched_settings_menu.mainsail_unstable = False
        patched_settings_menu.toggle_mainsail_release()
        assert patched_settings_menu.mainsail_unstable is True

    def test_toggle_fluidd_release(self, patched_settings_menu: SettingsMenu) -> None:
        patched_settings_menu.fluidd_unstable = False
        patched_settings_menu.toggle_fluidd_release()
        assert patched_settings_menu.fluidd_unstable is True

    def test_toggle_backup_before_update(
        self, patched_settings_menu: SettingsMenu
    ) -> None:
        patched_settings_menu.auto_backups_enabled = True
        patched_settings_menu.toggle_backup_before_update()
        assert patched_settings_menu.auto_backups_enabled is False


class TestOptimizeInstallToggle:
    def test_enabling_applies_linux_optimizations(
        self, patched_settings_menu: SettingsMenu, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = []
        monkeypatch.setattr(
            "core.menus.settings_menu.apply_linux_optimizations",
            lambda: calls.append(True) or True,
        )

        patched_settings_menu.optimize_install = False
        patched_settings_menu.toggle_optimize_install()

        assert calls == [True]
        assert patched_settings_menu.optimize_install is True

    def test_enabling_is_aborted_when_user_declines(
        self, patched_settings_menu: SettingsMenu, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "core.menus.settings_menu.apply_linux_optimizations", lambda: False
        )

        patched_settings_menu.optimize_install = False
        patched_settings_menu.toggle_optimize_install()

        assert patched_settings_menu.optimize_install is False

    def test_disabling_leaves_the_system_alone(
        self, patched_settings_menu: SettingsMenu, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = []
        monkeypatch.setattr(
            "core.menus.settings_menu.apply_linux_optimizations",
            lambda: calls.append(True) or True,
        )

        patched_settings_menu.optimize_install = True
        patched_settings_menu.toggle_optimize_install()

        assert calls == []
        assert patched_settings_menu.optimize_install is False

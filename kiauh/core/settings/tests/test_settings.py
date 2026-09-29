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

import pytest
from core.settings.kiauh_settings import KiauhSettings

DEFAULT_CFG_CONTENT = """\
[kiauh]
backup_before_update: False
optimize_install: False

[klipper]
repositories:
    https://github.com/Klipper3d/klipper

[moonraker]
optional_speedups: True
repositories:
    https://github.com/Arksine/moonraker

[mainsail]
port: 80
unstable_releases: False

[fluidd]
port: 80
unstable_releases: False
"""


@pytest.fixture
def reset_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(KiauhSettings, "_KiauhSettings__instance", None)
    monkeypatch.setattr(KiauhSettings, "_KiauhSettings__initialized", False)


@pytest.fixture
def cfg_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reset_settings):
    from core.settings import kiauh_settings as ks

    default = tmp_path / "default.kiauh.cfg"
    default.write_text(DEFAULT_CFG_CONTENT)
    custom = tmp_path / "kiauh.cfg"

    monkeypatch.setattr(ks, "DEFAULT_CFG", default)
    monkeypatch.setattr(ks, "CUSTOM_CFG", custom)
    return default, custom


class TestKiauhSettings:
    def test_loads_default_when_custom_missing(self, cfg_paths) -> None:
        settings = KiauhSettings()
        assert settings.kiauh.backup_before_update is False
        assert settings.mainsail.port == 80
        assert settings.klipper.use_python_binary is None

    def test_loads_custom_overrides(self, cfg_paths) -> None:
        _, custom = cfg_paths
        custom.write_text(
            "[kiauh]\nbackup_before_update: True\n[mainsail]\nport: 8080\n"
        )
        settings = KiauhSettings()
        assert settings.kiauh.backup_before_update is True
        assert settings.mainsail.port == 8080

    def test_save_writes_custom_config(self, cfg_paths) -> None:
        _, custom = cfg_paths
        settings = KiauhSettings()
        settings.kiauh.backup_before_update = True
        settings.save()

        text = custom.read_text()
        assert "backup_before_update: True" in text

    def test_get_returns_value(self, cfg_paths) -> None:
        settings = KiauhSettings()
        assert settings.get("mainsail", "port") == 80

    def test_optimize_install_defaults_to_false(self, cfg_paths) -> None:
        settings = KiauhSettings()
        assert settings.kiauh.optimize_install is False

    def test_optimize_install_persists_on_save(self, cfg_paths) -> None:
        _, custom = cfg_paths
        settings = KiauhSettings()
        settings.kiauh.optimize_install = True
        settings.save()

        assert "optimize_install: True" in custom.read_text()

        # a freshly loaded instance has to see the saved value
        KiauhSettings._KiauhSettings__instance = None
        KiauhSettings._KiauhSettings__initialized = False
        assert KiauhSettings().kiauh.optimize_install is True

    def test_missing_config_calls_kill(self, cfg_paths, monkeypatch) -> None:
        from core.settings import kiauh_settings as ks

        calls = []

        def fake_kill(msg: str = "") -> None:
            calls.append(msg)
            raise SystemExit(1)

        monkeypatch.setattr(ks, "DEFAULT_CFG", Path("/no/such/default.cfg"))
        monkeypatch.setattr(ks, "CUSTOM_CFG", Path("/no/such/custom.cfg"))
        monkeypatch.setattr(ks, "kill", fake_kill)

        with pytest.raises(SystemExit):
            KiauhSettings()

        assert len(calls) == 1

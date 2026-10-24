import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import jevtester
from jevtester.cli import main

ROOT = Path(__file__).parent.parent


def test_version_flag_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"jevtester {jevtester.__version__}"


def test_invalid_command_line_exits_with_2() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--no-such-flag"])
    assert exit_info.value.code == 2


def test_module_entry_point_runs() -> None:
    completed = subprocess.run([sys.executable, "-m", "jevtester", "--version"], capture_output=True, text=True)
    assert completed.returncode == 0
    assert completed.stdout.startswith("jevtester ")


def test_config_names_every_default_target() -> None:
    config = tomllib.loads((ROOT / "jevtester.toml").read_text())
    for name in config["defaults"]["targets"]:
        assert name in config["targets"]

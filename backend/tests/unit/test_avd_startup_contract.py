"""Virtual clock/launcher only: these tests never start or stop an emulator."""
from types import SimpleNamespace

import pytest

from maestro_app.infrastructure.device_manager import AndroidDeviceManager, DevicePreparationError
from maestro_app.infrastructure.tool_probe import ProcessResult
from unit.test_device_manager import FakeRunner, _config, _settings


class AvdHarness(FakeRunner):
    def __init__(self):
        super().__init__("")
        self.launches = []
        self.list_result = ProcessResult(0, "Pixel_5\n")
        self.boot_result = ProcessResult(0, "1")
        self.comes_online = True
        self.launch_error = None
        self.package_checked = False
        self.now = 0.0

    def start(self, args):
        self.launches.append(list(args))
        if self.launch_error:
            raise self.launch_error

    def sleep(self, seconds):
        self.now += seconds

    def run(self, args, timeout_seconds):
        if args[-1] == "-list-avds":
            return self.list_result
        if args[-1] == "devices":
            return ProcessResult(0, "emulator-5554\tdevice\n" if self.launches and self.comes_online else "List of devices attached\n")
        if args[-1] == "sys.boot_completed":
            return self.boot_result
        if "pm" in args:
            self.package_checked = True
        return super().run(args, timeout_seconds)


def manager(tmp_path, monkeypatch, harness):
    monkeypatch.setattr("maestro_app.infrastructure.device_manager.time", SimpleNamespace(monotonic=lambda: harness.now, sleep=harness.sleep))
    settings = _settings(tmp_path).model_copy(update={"device_boot_timeout_seconds": 3})
    return AndroidDeviceManager(settings, harness, harness)


def test_avd_launch_online_boot_and_package_check(tmp_path, monkeypatch):
    harness = AvdHarness()
    prepared = manager(tmp_path, monkeypatch, harness).prepare(_config())
    assert prepared.boot_completed and prepared.app_installed
    assert prepared.device_id == "emulator-5554"
    assert harness.launches == [["emulator", "-avd", "Pixel_5", "-no-snapshot-save"]]
    assert harness.package_checked


@pytest.mark.parametrize("response, code", [
    (ProcessResult(124, error="timeout"), "AVD_LIST_FAILED"),
    (ProcessResult(127, error="unavailable"), "AVD_LIST_FAILED"),
    (ProcessResult(0, "invalid output"), "AVD_NOT_FOUND"),
])
def test_avd_list_failure_never_launches(tmp_path, monkeypatch, response, code):
    harness = AvdHarness()
    harness.list_result = response
    with pytest.raises(DevicePreparationError) as error:
        manager(tmp_path, monkeypatch, harness).prepare(_config())
    assert error.value.code == code
    assert not harness.launches and not harness.package_checked


def test_unavailable_launcher_propagates_without_app_execution(tmp_path, monkeypatch):
    harness = AvdHarness()
    harness.launch_error = FileNotFoundError("emulator unavailable")
    with pytest.raises(FileNotFoundError, match="emulator unavailable"):
        manager(tmp_path, monkeypatch, harness).prepare(_config())
    assert len(harness.launches) == 1 and not harness.package_checked


def test_launched_avd_never_online_is_bounded(tmp_path, monkeypatch):
    harness = AvdHarness()
    harness.comes_online = False
    with pytest.raises(DevicePreparationError) as error:
        manager(tmp_path, monkeypatch, harness).prepare(_config())
    assert error.value.code == "EMULATOR_START_TIMEOUT"
    assert harness.now == 3 and len(harness.launches) == 1
    assert not harness.package_checked


@pytest.mark.parametrize("response", [ProcessResult(0, "0"), ProcessResult(0, "invalid"), ProcessResult(124, error="timeout"), ProcessResult(127, error="unavailable")])
def test_boot_not_confirmed_is_bounded_and_blocks_app(tmp_path, monkeypatch, response):
    harness = AvdHarness()
    harness.boot_result = response
    with pytest.raises(DevicePreparationError) as error:
        manager(tmp_path, monkeypatch, harness).prepare(_config())
    assert error.value.code == "EMULATOR_BOOT_TIMEOUT"
    assert harness.now == 3 and not harness.package_checked

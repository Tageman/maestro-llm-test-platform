from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Protocol, Sequence

from maestro_app.core.config import Settings
from maestro_app.domain.models import DevicePreparation, ProjectConfig
from maestro_app.infrastructure.tool_probe import CommandRunner, SubprocessCommandRunner


class DevicePreparationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DeviceLauncher(Protocol):
    def start(self, args: Sequence[str]) -> None: ...


class SubprocessDeviceLauncher:
    def start(self, args: Sequence[str]) -> None:
        subprocess.Popen(
            list(args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            shell=False,
        )


class AndroidDeviceManager:
    def __init__(
        self,
        settings: Settings,
        runner: CommandRunner | None = None,
        launcher: DeviceLauncher | None = None,
    ) -> None:
        self.settings = settings
        self.runner = runner or SubprocessCommandRunner()
        self.launcher = launcher or SubprocessDeviceLauncher()

    def prepare(self, config: ProjectConfig) -> DevicePreparation:
        checks: list[dict] = []
        self._require_command(
            [config.maestro_command, "--version"],
            "MAESTRO_UNAVAILABLE",
            "Maestro CLI 不可用",
            checks,
        )
        self._require_command(
            [self.settings.adb_command, "version"],
            "ADB_UNAVAILABLE",
            "ADB 不可用",
            checks,
        )

        online = self._online_emulators(checks)
        device_id = self._select_device(config, online)
        if device_id is None:
            if not config.avd_name:
                raise DevicePreparationError(
                    "ANDROID_DEVICE_NOT_FOUND",
                    "没有在线 Android 模拟器，且 Config.avd_name 为空",
                )
            avds = self._list_avds(checks)
            if config.avd_name not in avds:
                raise DevicePreparationError(
                    "AVD_NOT_FOUND", f"本机不存在 AVD {config.avd_name}"
                )
            self.launcher.start(
                [
                    self.settings.emulator_command,
                    "-avd",
                    config.avd_name,
                    "-no-snapshot-save",
                ]
            )
            checks.append(
                {
                    "name": "avd_start",
                    "status": "passed",
                    "detail": config.avd_name,
                }
            )
            device_id = self._wait_for_unique_emulator(config)

        if not device_id.startswith("emulator-"):
            raise DevicePreparationError(
                "PHYSICAL_DEVICE_UNSUPPORTED",
                f"一期只支持 Android 模拟器，实际设备为 {device_id}",
            )
        self._wait_for_boot(device_id, checks)
        avd_name = self._avd_name(device_id, checks)
        if config.avd_name and avd_name != config.avd_name:
            raise DevicePreparationError(
                "AVD_NAME_MISMATCH",
                f"设备 {device_id} 对应 AVD {avd_name}，与 Config {config.avd_name} 不一致",
            )
        self._ensure_app(device_id, config, checks)
        self._capture_test_environment(device_id, checks)
        return DevicePreparation(
            device_id=device_id,
            avd_name=avd_name,
            app_id=config.app_id,
            app_installed=True,
            boot_completed=True,
            checks=checks,
        )

    def _online_emulators(self, checks: list[dict]) -> list[str]:
        result = self.runner.run(
            [self.settings.adb_command, "devices"],
            self.settings.probe_timeout_seconds,
        )
        if not result.succeeded:
            raise DevicePreparationError(
                "ADB_DEVICES_FAILED", result.error or result.combined_output
            )
        online: list[str] = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device" and parts[0].startswith("emulator-"):
                online.append(parts[0])
        checks.append(
            {"name": "adb_devices", "status": "passed", "devices": online}
        )
        return online

    @staticmethod
    def _select_device(config: ProjectConfig, online: list[str]) -> str | None:
        if config.android_device_id:
            if not config.android_device_id.startswith("emulator-"):
                raise DevicePreparationError(
                    "PHYSICAL_DEVICE_UNSUPPORTED",
                    "Config.android_device_id 必须是 emulator-*",
                )
            if config.android_device_id not in online:
                raise DevicePreparationError(
                    "CONFIGURED_DEVICE_OFFLINE",
                    f"指定模拟器 {config.android_device_id} 不在线",
                )
            return config.android_device_id
        if len(online) > 1:
            raise DevicePreparationError(
                "MULTIPLE_EMULATORS",
                "存在多台在线模拟器，请填写 Config.android_device_id",
            )
        return online[0] if online else None

    def _list_avds(self, checks: list[dict]) -> list[str]:
        result = self.runner.run(
            [self.settings.emulator_command, "-list-avds"],
            self.settings.probe_timeout_seconds,
        )
        if not result.succeeded:
            raise DevicePreparationError(
                "AVD_LIST_FAILED", result.error or result.combined_output
            )
        avds = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        checks.append({"name": "avd_list", "status": "passed", "avds": avds})
        return avds

    def _wait_for_unique_emulator(self, config: ProjectConfig) -> str:
        deadline = time.monotonic() + self.settings.device_boot_timeout_seconds
        while time.monotonic() < deadline:
            online = self._online_emulators([])
            if config.android_device_id and config.android_device_id in online:
                return config.android_device_id
            if not config.android_device_id and len(online) == 1:
                return online[0]
            time.sleep(1)
        raise DevicePreparationError(
            "EMULATOR_START_TIMEOUT",
            f"等待 AVD {config.avd_name} 上线超时",
        )

    def _wait_for_boot(self, device_id: str, checks: list[dict]) -> None:
        deadline = time.monotonic() + self.settings.device_boot_timeout_seconds
        while time.monotonic() < deadline:
            result = self.runner.run(
                [
                    self.settings.adb_command,
                    "-s",
                    device_id,
                    "shell",
                    "getprop",
                    "sys.boot_completed",
                ],
                self.settings.probe_timeout_seconds,
            )
            if result.succeeded and result.stdout.strip() == "1":
                checks.append(
                    {
                        "name": "boot_completed",
                        "status": "passed",
                        "device_id": device_id,
                    }
                )
                return
            time.sleep(1)
        raise DevicePreparationError(
            "EMULATOR_BOOT_TIMEOUT", f"模拟器 {device_id} 启动未完成"
        )

    def _avd_name(self, device_id: str, checks: list[dict]) -> str:
        result = self.runner.run(
            [self.settings.adb_command, "-s", device_id, "emu", "avd", "name"],
            self.settings.probe_timeout_seconds,
        )
        if not result.succeeded:
            raise DevicePreparationError(
                "AVD_NAME_FAILED", result.error or result.combined_output
            )
        avd_name = next(
            (
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip() and line.strip() != "OK"
            ),
            "",
        )
        if not avd_name:
            raise DevicePreparationError("AVD_NAME_FAILED", "无法读取在线 AVD 名称")
        checks.append(
            {"name": "avd_name", "status": "passed", "avd_name": avd_name}
        )
        return avd_name

    def _ensure_app(
        self,
        device_id: str,
        config: ProjectConfig,
        checks: list[dict],
    ) -> None:
        if config.apk_path is not None:
            apk_path = Path(config.apk_path).expanduser().resolve()
            if not apk_path.is_file():
                raise DevicePreparationError(
                    "APK_NOT_FOUND", f"APK 文件不存在：{apk_path}"
                )
            install = self.runner.run(
                [
                    self.settings.adb_command,
                    "-s",
                    device_id,
                    "install",
                    "-r",
                    str(apk_path),
                ],
                max(self.settings.probe_timeout_seconds, 120),
            )
            if not install.succeeded:
                raise DevicePreparationError(
                    "APK_INSTALL_FAILED", install.error or install.combined_output
                )
            checks.append(
                {"name": "apk_install", "status": "passed", "path": str(apk_path)}
            )
        package = self.runner.run(
            [
                self.settings.adb_command,
                "-s",
                device_id,
                "shell",
                "pm",
                "path",
                config.app_id,
            ],
            self.settings.probe_timeout_seconds,
        )
        if not package.succeeded or not package.stdout.startswith("package:"):
            raise DevicePreparationError(
                "APP_NOT_INSTALLED", f"设备上未安装 {config.app_id}"
            )
        checks.append(
            {"name": "app_package", "status": "passed", "app_id": config.app_id}
        )

    def _capture_test_environment(
        self,
        device_id: str,
        checks: list[dict],
    ) -> None:
        """Capture non-blocking Android UI conditions that can alter text flows."""
        input_method = self.runner.run(
            [
                self.settings.adb_command,
                "-s",
                device_id,
                "shell",
                "dumpsys",
                "input_method",
            ],
            self.settings.probe_timeout_seconds,
        )
        locale_match = re.search(
            r"currentEntry=.*?languageTag=([^,}\s]+)",
            input_method.stdout,
        )
        active_locale = locale_match.group(1) if locale_match else None
        if not input_method.succeeded:
            input_detail = (
                "failed to read Android input method state: "
                + (input_method.error or input_method.combined_output)
            )
        elif active_locale:
            input_detail = f"active keyboard locale: {active_locale}"
        else:
            input_detail = (
                "active keyboard locale is not available until an input field has been focused"
            )
        checks.append(
            {
                "name": "input_method",
                "status": (
                    "passed"
                    if input_method.succeeded and active_locale
                    else "warning"
                ),
                "active_locale": active_locale,
                "detail": input_detail,
            }
        )

        autofill = self.runner.run(
            [
                self.settings.adb_command,
                "-s",
                device_id,
                "shell",
                "settings",
                "get",
                "secure",
                "autofill_service",
            ],
            self.settings.probe_timeout_seconds,
        )
        service = autofill.stdout.strip()
        enabled = bool(service and service != "null") if autofill.succeeded else None
        if not autofill.succeeded:
            autofill_detail = (
                "failed to read Android autofill service: "
                + (autofill.error or autofill.combined_output)
            )
        elif enabled:
            autofill_detail = (
                "an Android autofill service is enabled and may display a system overlay"
            )
        else:
            autofill_detail = "no Android autofill service is configured"
        checks.append(
            {
                "name": "autofill_service",
                "status": (
                    "warning"
                    if not autofill.succeeded or enabled
                    else "passed"
                ),
                "enabled": enabled,
                "service": service or None,
                "detail": autofill_detail,
            }
        )

    def _require_command(
        self,
        args: list[str],
        code: str,
        message: str,
        checks: list[dict],
    ) -> None:
        result = self.runner.run(args, self.settings.probe_timeout_seconds)
        if not result.succeeded:
            raise DevicePreparationError(
                code,
                f"{message}：{result.error or result.combined_output}",
            )
        checks.append(
            {
                "name": Path(args[0]).name,
                "status": "passed",
                "detail": result.combined_output.splitlines()[0]
                if result.combined_output
                else "OK",
            }
        )

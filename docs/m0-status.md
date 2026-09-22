# M0 技术基线与环境打通状态

## 文档信息

| 项目 | 内容 |
| --- | --- |
| 状态 | Accepted |
| 更新日期 | 2026-09-16 |
| 验收日期 | 2026-09-16 |
| 对应里程碑 | M0：技术基线与本地环境打通 |
| 运行环境 | macOS、Android Studio Emulator、Maestro CLI 2.10.0 |

## 已完成

- 冻结领域模型、目录结构、Flow IR V1 Schema、运行状态机和前后端 API V1。
- 建立 Python 3.11+ / FastAPI / Pydantic 后端骨架与 React / TypeScript / Vite 前端骨架。
- 实现领域枚举、Flow IR 类型、受保护的 Run 状态迁移和文件系统 Run Repository。
- 实现 `health`、本机能力探测和 Flow IR Schema 查询接口。
- 实现 Maestro、Maestro MCP、ADB、Android Emulator、在线设备、AVD 和目标包探测。
- 实现 M0 系统基线控制台，并完成桌面与窄屏布局、浏览器控制台和真实接口数据检查。
- 建立最小 Maestro 启动 Flow；`maestro check-syntax` 校验通过。
- 完成 Maestro MCP 协议验证：`initialize`、`tools/list`、`list_devices` 和 `inspect_screen` 均成功。
- MCP 已读取 `emulator-5554` 上目标 App 的真实页面层级，包括“输入主题”“导入文档”“导入大纲”“立即生成”等控件。
- 实现后端 `MaestroMcpClient`，具备 stdio 生命周期、JSON-RPC 请求、超时、错误和进程终止控制。
- 实现可复用 `MaestroCliRunner`，参数使用数组传递并统一保留 JUnit 和运行产物。
- 实现 `make dev` 单命令启动前后端，并验证两个入口均返回 HTTP 200。

## 验证结果

| 检查项 | 结果 | 证据/说明 |
| --- | --- | --- |
| 后端自动化测试 | 通过 | 16 tests passed |
| 前端生产构建 | 通过 | `npm run build` |
| Flow IR Schema | 通过 | JSON 可解析且符合 Draft 2020-12 metaschema |
| OpenAPI 契约 | 通过 | OpenAPI 3.1.0，共 17 个 paths |
| Maestro CLI | 可用 | 2.10.0 |
| ADB | 可用 | 1.0.41 |
| Android Emulator | 在线 | `emulator-5554` / `Pixel_5` |
| 目标包 | 已安装 | `aippt.com.mm` |
| Maestro MCP | 通过 | 后端客户端可列出设备、读取页面层级和截图并正常关闭进程 |
| 最小 Flow 语法 | 通过 | `maestro check-syntax` 返回 OK |
| 最小 Flow 模拟器执行 | 通过 | 直接 CLI 1/1 passed（11s）；`MaestroCliRunner` 1/1 passed（9s） |
| 单命令启动 | 通过 | `make dev`；前端和健康接口均为 HTTP 200 |

## 已关闭问题：CLI Device Server 断连

早期执行在首条业务命令之前出现：

```text
maestro.android.DeviceServerDiedException:
Device server died during 'deviceInfo' on emulator-5554
StatusRuntimeException: UNAVAILABLE
```

诊断确认 Maestro Studio 0.9.5 与 CLI 同时控制 `emulator-5554`，Studio Server 持续维护两条会话租约，CLI 连接到未监听的 Driver 端口。正常退出 Maestro Studio、备份残留会话文件并重新建立 Driver 后问题消失；未清除目标 App 数据。

关闭证据保留在本地 `runtime/m0-closeout-20260916/`：

- `report-final.xml`：直接 CLI 成功 JUnit。
- `report-runner.xml`：平台 `MaestroCliRunner` 成功 JUnit。
- `mcp-evidence/server-info.json`、`tools.json`、`devices.json`、`hierarchy.json`。
- `mcp-evidence/device-screenshot.jpg`：MCP 返回的真实设备截图。
- `host-state/`：关闭问题前的 Maestro 会话租约备份。

运行约束已纳入验收基线：Maestro Studio、平台 Maestro CLI 与平台 Maestro MCP 不得并发控制同一模拟器；平台内部 CLI/MCP 调用必须串行。

## 验收结论

M0-AC-01～M0-AC-06 全部通过，无未关闭 P0 阻塞。M0 状态为 `Accepted`，允许进入 M1 离线生成闭环。

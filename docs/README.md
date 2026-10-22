# 文档导航

`docs/` 保存产品需求、实现契约和研发/验收追溯材料，不是运行缓存，也不是全部都要依次阅读的使用手册。日常使用先读 [使用说明](user-guide-v1.md)；V2 开发先读下面两份新文档。

## V2：本轮交付

| 文件 | 作用 | 当前性质 |
| --- | --- | --- |
| [requirements-v2.md](requirements-v2.md) | 说明页面可操作性、重复执行、版本复用、优先级、分阶段范围和验收标准 | V2 需求提案，未代表已实现 |
| [technical-design-v2.md](technical-design-v2.md) | 说明领域模型、目录、IR 兼容、执行计划/状态、前后端接口、持久化与测试 | V2 技术设计提案，待实施评审 |

V2-A 为操作闭环，V2-B 为稳定复跑，V2-C 为配置与效率。V2 不重新打开 M4，也不把 V2 新验收项追溯为一期必须补做的工作。

## 一期：使用和技术基线

| 文件 | 作用 | 何时阅读 |
| --- | --- | --- |
| [user-guide-v1.md](user-guide-v1.md) | 环境搭建、Web 启动、操作流程、Excel 字段和排障 | 安装/使用平台；根目录 README 也以使用说明为定位 |
| [technical-design-v1.md](technical-design-v1.md) | 一期分层、目录、领域模型、IR、状态机和接口设计及兼容修订 | 理解现有实现和设计约束 |
| [api-contract-v1.yaml](api-contract-v1.yaml) | 机器可读 OpenAPI 接口基线 | 前后端联调、类型与协议校验；不是应用配置文件 |
| [m2-operations.md](m2-operations.md) | M2 模拟器执行与证据目录的专项操作说明 | 追溯 M2 环境和流程；日常启动优先看使用说明，不要求每次重复历史验收 |
| [m4-shared-fixtures-design.md](m4-shared-fixtures-design.md) | 跨 Case function/module/session 生命周期、重试重建和共享清理 | 修改 Fixture 编排、理解执行顺序 |
| [m4-recovery-design.md](m4-recovery-design.md) | 子进程所有权、运行中断及重启恢复规则 | 修改进程/恢复逻辑、排查中断 Run |

## 一期：验收标准、状态和审计

| 文件 | 作用 | 不应误解为 |
| --- | --- | --- |
| [milestone-acceptance-v1.md](milestone-acceptance-v1.md) | M0～M4 的验收步骤、预期结果、证据和阻断规则 | 所有里程碑已经通过的证明 |
| [m0-status.md](m0-status.md) | M0 技术基线和环境验证记录 | 当前机器持续健康的保证 |
| [m1-status.md](m1-status.md) | M1 离线生成闭环的状态、证据与限制 | 任意模型/用例均已验证 |
| [m2-status.md](m2-status.md) | M2 实际执行、问题关闭与签收边界 | 后续所有版本自动沿用 PASS |
| [m3-status.md](m3-status.md) | M3 受控诊断/修复和结果闭环的证据 | 无限范围自动修复能力 |
| [m0-m1-design-conformance.md](m0-m1-design-conformance.md) | M0/M1 实现与技术设计的符合性审计及后续补充 | 运行使用手册 |
| [m3-design-conformance.md](m3-design-conformance.md) | M3 实现与设计约束的对应审计 | 独立的产品需求版本 |
| [m4-plan.md](m4-plan.md) | M4 范围、任务拆解、门禁与规划收束 | M4 发布已经签收；“规划收束”不等于“发布完成” |
| [m4-implementation-status.md](m4-implementation-status.md) | M4 已实施内容、技术修订、验证范围与剩余动作 | 最终发布证书 |
| [m4-release-review-20261021.md](m4-release-review-20261021.md) | 指定日期的发布复核、证据索引和待核验材料 | 对未来版本自动生效的结论 |
| [m4-evidence-matrix-20261022.md](m4-evidence-matrix-20261022.md) | 验收项与自动化/真实设备证据的追溯矩阵 | 仅凭测试数量证明全部发布门禁通过 |
| [m4-closeout-decision-20261022.md](m4-closeout-decision-20261022.md) | 剩余项必要性、最小收尾范围与后移项裁决 | 负责人签署或 GitHub Release |

本轮整理时，工作区还有未提交的 `m4-small-closeout-20261022.md` 及其它 M4 代码/文档修改；它们不包含在本次 V2 文档提交中。远端读者应以提交中的文件和具体版本为准，不把本机未提交记录当作远端交付。

## 阅读与维护规则

1. **需求回答“做什么、为什么”；技术设计回答“怎么做”；接口契约约束协议；状态/证据文档说明“哪个版本做到了什么”。** 它们用途不同，不是同一份说明的无意义重复。
2. 带日期或里程碑的文档保留历史语境。更新现行规范时明确版本与替代范围，不通过删除历史失败记录制造一致性。
3. 计划、实现、测试通过、人工签收、提交/推送是不同状态。遇到文档冲突，核对对应 commit、日期和证据；不能只按文件名或最新修改时间推断发布通过。
4. V2 接口草案未实施前，现有客户端仍以一期 OpenAPI 和实际服务为准。实施中同步更新契约与验收映射。
5. 私有 Excel、密钥、运行截图/日志等证据留在受控 runtime 或指定存储，不直接放进公开 Git 仓库；文档只保留必要的脱敏说明与索引。
6. 本次只增加导航与 V2 文档，不删除、移动或重写旧文档；以后若归档历史记录，应同步修复链接并单独提交。

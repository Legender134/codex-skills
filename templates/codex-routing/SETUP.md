# Windows / WSL 配置安装

这里保存经验证的可复用配置源码。Windows 和 WSL 各自维护自己的 Codex home；共享技能不代表共享登录信息、可执行文件或 GUI 运行时。

## 配置内容

| 用途 | 模型 | 推理等级 |
|---|---|---|
| 主代理、默认子代理 | gpt-6-sol | high |
| worker | gpt-6-luna | max |
| scout | gpt-6-luna | low |
| explorer、routine_worker | gpt-6-luna | high |
| reviewer | gpt-6-sol | high |
| critical_reviewer | gpt-6-astra | high |

每个主会话的全局子代理上限为 2，不包含主代理；不设置项目模型、角色或并发覆盖。只使用支持的 GPT-6 路由，不回退到 GPT-5.6。小任务由主代理直接完成，只有能够独立推进的明确子任务才委派，不按角色流水线固定执行。模型可用性、角色支持和权限以当前客户端、账户和工具声明为准；只读角色文件不是对父级权限覆盖的隔离保证。

安装位置、项目继承和配置迁移属于本文的维护说明，不放入每次任务加载的全局 AGENTS。修改文件后还要核对新会话实际加载的设置，不能推定已运行会话立即生效。

`critical_reviewer` 保留训练、CUDA、重建的专业检查项，同时以本次变更的具体风险决定检查范围。梯度累积、内核同步、位姿组合顺序等改动可能需要深入审查；修改训练日志并不会因为出现“训练”而自动升级。其他开发中的权限隔离、并发写入、数据迁移等也可使用该角色。普通 reviewer 报告未解决的风险和缺失证据，由主代理决定是否追加审查；不固定串行执行两个角色。坐标系、容差、验收指标等项目事实从任务和项目要求中读取，不写成全局默认值。

## 1. 选择安装目标

从仓库根目录进入 `templates/codex-routing`，按 [README](README.md#prepare-the-environment) 设置 Python、Windows Codex home 和 WSL Codex home，然后执行源校验及所选目标的预览。安装器需要 Python 3.11+；从 WSL 操作 Windows 目标时，先在启动 Codex 的 Windows PowerShell 环境中确认路径，再用 `wslpath` 转成 WSL 路径并赋给 `WINDOWS_CODEX_HOME`。启动器单独设置的 `CODEX_HOME` 以启动器为准，不要默认它位于用户目录。

Windows 原生入口拒绝通过 `\\wsl$`、`\\wsl.localhost` 或其扩展 UNC 形式操作 WSL Codex home；这类目标请进入对应 WSL 发行版后使用 Linux 路径管理。

```bash
cd templates/codex-routing
export PYTHONPATH="$PWD/src"
python3 -m codex_routing check-source --source-root "$PWD"
```

按 README 对需要的目标执行 `install-global`，先预览、后加 `--apply`。该命令合并模型/并发设置、全局指令块和六个角色，保留原有 MCP、插件、账户、权限等无关配置。不要把整个仓库或本目录复制成 `.codex`，也不要用其他机器的完整 `config.toml` 覆盖本机配置。

## 2. 应用技能策略

`skill-policy.toml` 是独立的 TOML 合并片段，**不会由路由安装器自动应用**。它按稳定名称禁用本次审查的 14 个 `superpowers:*` 技能。

在两个目标的 `config.toml` 中按 `name` 合并这些 `[[skills.config]]` 条目：同名项更新为 `enabled = false`；不存在则新增；保留其他技能项，不重复追加同名配置。已有路径选择器如果也针对这些技能，应核查并消除相反设置。不要修改插件缓存或将片段当成完整主配置。

可让 Codex 在目标机器执行：

> 将 templates/codex-routing/skill-policy.toml 按技能名称合并到我选定的 Codex home，保留其他配置，备份改动文件，并验证新任务的技能目录。

这不是卸载插件；未来新增的其他 Superpowers 技能名需要另行审查。当前原生接口可以发现显式技能，但不一定返回隐式调用策略；要同时检查元数据与新任务目录。

## 3. 安装自定义技能

从本仓库选择安装：

- `skills/repository-aligned-development`：仓库边界、已有改动与提交范围。
- `skills/codex-sync-skills`：Windows 技能到 WSL 的链接预览与冲突保护。
- `skills/planned-development`：通过 `$planned-development` 显式调用规划流程，默认不进入隐式技能上下文。
- `skills/using-shared-gpu-host`：共享 GPU 的归属、资源分配及训练授权。
- `skills/hatch-pet`：Codex v2 宠物，保留原图并按需读取详细流程。
- `skills/crafting-desktop-companion-pets`：独立的 DesktopCompanion v2/v3/v4 宠物工作流。

使用 Codex 的 `skill-installer` 安装选定目录，或者手动复制/链接到目标用户技能目录。存在同名内容时先核对差异并保留旧内容，不能用批量复制掩盖冲突。WSL 可独立安装可移植技能，或使用 `codex-sync-skills` 预览选定 Windows 技能的链接；工具、Python 和图像生成能力仍须在目标环境核实。

`hatch-pet` 的确定性脚本需要 Pillow。Windows 使用桌面依赖工具返回的原生 Python；WSL 可为已安装的 Python 创建独立环境：

```bash
python3 -m venv "$HOME/.local/share/codex-skill-runtimes/hatch-pet"
"$HOME/.local/share/codex-skill-runtimes/hatch-pet/bin/python" -m pip install Pillow==12.3.0
```

若环境已存在，先检查已有依赖，避免覆盖自定义环境。新图生成依赖可用图像工具，缺少工具不会自动切换 API 计费。

## 4. 核查项目和工作树

项目级配置和更深层指令可能覆盖全局设置；项目配置是否加载还受信任状态影响。全局更新不代表所有项目覆盖都被删除。

- 不提供项目专用安装、校验入口；不支持的命令在参数解析阶段退出，不读写项目。只使用全局路由安装入口。
- 普通代码项目直接继承全局配置，不新建项目路由配置，也不复制全局 AGENTS 规则。必要的项目领域约束留在项目内；非代码项目的专属要求同样不搬进全局文件。
- 逐个检查 `.codex/config.toml`、`.codex/agents/` 及适用的 `AGENTS.md`。保留业务规则及与路由无关的 hooks、skills、state；旧覆盖需单独审查和备份后处理。
- 用 `git worktree list --porcelain` 盘点工作树。每个工作树有自己的目录上下文，可能含独立本地覆盖；从各目录验证有效配置，不能只检查主工作树。
- 项目模板也应继承全局路由；具体领域的任务要求作为业务说明传给全局角色，不另维护模型表。

安装器不会自动信任仓库、遍历所有工作树、删除旧覆盖或清理备份。已有备份不在活动发现目录中即可保留；未知文件和分支不应为了“更新全局”而删除。

## 5. 启动入口和本机服务

本次路由验证使用原生 Codex CLI 0.154.0。分别运行 Windows 的 `codex --version` 和 `wsl -d <发行版> -- codex --version`，确保 WSL 没有落到 Windows npm shim；桌面自带 CLI 由桌面独立维护。新版本需要重新验证模型支持，版本号本身不证明请求成功。

`scripts/codex-wsl` 是可选 Linux 入口：调用当前用户的 `$HOME/.local/bin/codex` 并补齐 PATH。只有该位置已经是可运行的 Linux Codex、且没有指回这个入口形成循环时，才将它安装到 `/usr/local/bin/codex`。存在不同的系统入口时先保留并审查，切勿把脚本安装到它自身调用的 `$HOME/.local/bin/codex`。仓库不分发 Codex 二进制，也不代办安装或升级。

Confluence 等组织服务留在本机：由本机原生 Node 启动组织提供并验证的固定包版本；包、认证和组织地址不随此仓库发布。不要将 Windows GUI MCP、桌面通信管道、通知路径或凭据复制到 WSL。路由安装器保留无关配置，因此不会替旧环境清除这些残留。

CLI 0.154.0 的本机配置审查还确认了两类旧字段：`features.js_repl` 已标记为 `removed`；stdio MCP 的 `type = "stdio"` 会被 `app-server --strict-config` 拒绝，使用 `command` 和 `args` 即可。遇到这些字段时，先核对本机 CLI 行为、备份配置，再只移除对应字段。不要把 `features.js_repl` 与桌面管理的 `mcp_servers.node_repl` 混为一谈。此类清理不属于路由安装器的自动修改范围。

`projects.*.trust_level` 是信任记录，并非项目模型路由；桌面运行时路径、通知入口、浏览器状态及模型缓存由对应应用管理。路径或缓存版本变化需要核查引用和实际行为，不应为了精简指令而删除。TOML 能解析、路由校验通过，也不代表当前 CLI 识别全部字段或所有 MCP 都已连通。

命令允许规则单独保存在本机 `rules/*.rules`，不会由路由安装器同步。`prefix_rule` 只检查命令前缀，`curl -I -L` 或 `curl -L --range` 后面仍能追加其他请求方法，因此不能当作只读白名单。对这类过宽的永久允许规则，备份后移除对应条目，恢复正常执行策略；保留无关规则，不用整份其他机器的规则文件覆盖本机。

## 6. 验收与回退

按 README 执行 `validate-global`、逐项目覆盖检查及再次安装预览，确认没有意外改动。刷新受影响的 Codex 任务，核对实际角色与技能目录；确认显式规划入口可用、Superpowers 禁用生效。工具初始化与实际只读请求应单独验证，配置语法通过不等于全部工具连通。

有文件变化时保留安装器打印的事务清单；没有变化时只复核文件，不创建空备份。回退仅针对所选事务，并在文件后续被修改时拒绝覆盖。若安装失败且自动恢复不完整，保留的清单和备份用于逐文件核对，`recovery-required.json` 记录失败状态；先确认当前文件摘要，再决定修复，不能直接重跑整个事务。单个文件替换是原子的，整个目录更新不具备同样保证。

技能策略合并、手动技能安装和可选 Linux 入口不属于路由事务，需保留各自备份。验收时分别对照已确认的仓库提交检查全局路由和所选 Skill 的完整文件清单、内容摘要及链接实际目标；`validate-global` 不检查 Skill。Windows 与 WSL 共享链接时也要核对最终目标，不能因链接存在就判定内容已更新。不要用全目录回滚覆盖后续用户工作。

## 仓库内验证

从本目录运行路由的完整测试；同步与宠物测试从各自目录运行，避免同名 Python 模块互相污染：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 ../../skills/codex-sync-skills/scripts/test_sync_skills.py
```

`skills/hatch-pet` 的测试还需要 Pillow；在已验证的独立 Python 中运行该目录的 `tests`。完整宠物生成与远程组织服务验证需要额外运行环境，不由这些单元测试证明。

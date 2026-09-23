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

## 1. 选择安装目标

从仓库根目录进入 `templates/codex-routing`，按 [README](README.md#prepare-the-environment) 设置 Python、Windows Codex home 和 WSL Codex home，然后执行源校验及所选目标的预览。安装器需要 Python 3.11+；从 WSL 操作两个目标时，Windows 路径通过 `powershell.exe` 和 `wslpath` 解析。自定义 Windows `CODEX_HOME` 应明确覆盖 `WINDOWS_CODEX_HOME`，不要默认它位于用户目录。

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

- 旧项目专用安装、校验入口已停用，返回错误且不读写项目；只使用全局路由安装入口。
- 普通代码项目直接继承全局配置，不新建项目路由配置，也不复制全局 AGENTS 规则。必要的项目领域约束留在项目内；非代码项目的专属要求同样不搬进全局文件。
- 逐个检查 `.codex/config.toml`、`.codex/agents/` 及适用的 `AGENTS.md`。保留业务规则及与路由无关的 hooks、skills、state；旧覆盖需单独审查和备份后处理。
- 用 `git worktree list --porcelain` 盘点工作树。每个工作树有自己的目录上下文，可能含独立本地覆盖；从各目录验证有效配置，不能只检查主工作树。
- 项目模板也应继承全局路由；具体领域的任务要求作为业务说明传给全局角色，不另维护模型表。

安装器不会自动信任仓库、遍历所有工作树、删除旧覆盖或清理备份。已有备份不在活动发现目录中即可保留；未知文件和分支不应为了“更新全局”而删除。

## 5. 启动入口和本机服务

本次路由验证使用原生 Codex CLI 0.154.0。分别运行 Windows 的 `codex --version` 和 `wsl -d <发行版> -- codex --version`，确保 WSL 没有落到 Windows npm shim；桌面自带 CLI 由桌面独立维护。新版本需要重新验证模型支持，版本号本身不证明请求成功。

`scripts/codex-wsl` 是可选 Linux 入口：调用当前用户的 `$HOME/.local/bin/codex` 并补齐 PATH。只有该位置已经是可运行的 Linux Codex、且没有指回这个入口形成循环时，才将它安装到 `/usr/local/bin/codex`。存在不同的系统入口时先保留并审查，切勿把脚本安装到它自身调用的 `$HOME/.local/bin/codex`。仓库不分发 Codex 二进制，也不代办安装或升级。

Confluence 等组织服务留在本机：由本机原生 Node 启动组织提供并验证的固定包版本；包、认证和组织地址不随此仓库发布。不要将 Windows GUI MCP、桌面通信管道、通知路径或凭据复制到 WSL。路由安装器保留无关配置，因此不会替旧环境清除这些残留。

## 6. 验收与回退

按 README 执行 `validate-global`、逐项目覆盖检查及再次安装预览，确认没有意外改动。刷新受影响的 Codex 任务，核对实际角色与技能目录；确认显式规划入口可用、Superpowers 禁用生效。工具初始化与实际只读请求应单独验证，配置语法通过不等于全部工具连通。

保留安装器打印的事务清单，回退仅针对所选事务，并在文件后续被修改时拒绝覆盖。技能策略合并、手动技能安装和可选 Linux 入口不属于路由事务，需保留各自备份。不要用全目录回滚覆盖后续用户工作。

## 仓库内验证

从本目录运行路由的完整测试；同步与宠物测试从各自目录运行，避免同名 Python 模块互相污染：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 ../../skills/codex-sync-skills/scripts/test_sync_skills.py
```

`skills/hatch-pet` 的测试还需要 Pillow；在已验证的独立 Python 中运行该目录的 `tests`。完整宠物生成与远程组织服务验证需要额外运行环境，不由这些单元测试证明。

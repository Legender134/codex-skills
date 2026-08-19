# DesktopCompanion 宠物媒体工具链运维说明

这份说明面向需要制作或修复 DesktopCompanion 宠物包的操作者。工具链只负责可复现的本地媒体处理和运行时解码门禁；宠物包的素材研究、身份判断、版本推荐、动作/形态契约和视觉验收仍由现有的 crafting-desktop-companion-pets skill 负责。

## 1. Purpose and non-goals

工具链把 FFmpeg、ImageMagick、libwebp、独立的 Python 3.12 媒体环境和两个 rembg ONNX 模型放在用户本机的隔离工具根中。它可以完成：

- 从素材或预览中抽帧、检查尺寸/颜色/透明度、运行 OpenCV 边界检查；
- 对 isnet-anime 和 u2net_human_seg 都运行真实的本地抠图 smoke；
- 使用 cwebp 生成透明 WebP，并用 Pillow 与 PySide6/Qt 交叉解码；
- 在所有门禁通过后，以 lock digest 发布一个不可变版本。

它不制作角色、不选择 v2/v3/v4、不修改 PATH、不修改 DesktopCompanion 产品安装、宠物安装目录或项目 .venv，不构建发行版，不推送仓库，也不读取或保存凭据、浏览器 session、Cookie 或账号状态。setup 是唯一会下载和发布本机工具链的脚本；verify 不下载、不安装、不修复信任配置。

普通 pytest 是离线契约测试：它不访问网络、不调用 setup、不会安装 pip 依赖，也不会执行真实模型推理。需要网络下载或真实推理时，必须由操作者明确运行下面的 setup/verify 命令。

## 2. Tracked versus machine-local files

以下是可审查、可复用的 tracked 接口：

| 路径 | 作用 |
| --- | --- |
| tools/pet-toolchain.lock.json | Windows x64 的资产、版本、大小、SHA-256、入口、签名策略和模型来源 |
| requirements/pet-media.in / requirements/pet-media.txt | Python 3.12 的直接依赖和完整 wheel hash lock |
| scripts/pet_toolchain_common.ps1 | 严格 UTF-8/JSON、路径、哈希、进程和清理边界 |
| [scripts/setup_pet_toolchain.ps1](../scripts/setup_pet_toolchain.ps1) | 唯一的下载、安装、staging 和发布入口 |
| [scripts/verify_pet_toolchain.ps1](../scripts/verify_pet_toolchain.ps1)、[tools/verify_pet_media.py](../tools/verify_pet_media.py)、[tools/verify_qt_webp.py](../tools/verify_qt_webp.py) | 对已发布候选的独立门禁 |
| .codex/config.toml、测试和本说明 | 项目级可共享设置、离线契约和操作说明 |

默认机器本地 ToolRoot 是：

~~~text
%LOCALAPPDATA%\DesktopCompanionDev\pet-toolchain
~~~

它可以包含 downloads 缓存、versions\<lockDigest> 不可变版本目录、每个版本的 installed.json、current.json 指针以及短生命周期的 verify\verify-<guid>\media-<guid> workspace。这些二进制、模型、Python 文件、安装清单、指针和缓存都不进 Git，也不能复制到 tracked 配置。

可以显式传入 -ToolRoot 使用 alternate root，但必须同时满足：目标及其现有祖先都是普通目录、没有重解析点；目标不是文件系统根、%USERPROFILE%、%LOCALAPPDATA%、源码仓库、源码仓库 .venv、DesktopCompanion 安装根、安装的宠物资源根或 %APPDATA%\DesktopCompanion\pets，也不能与这些路径重叠。alternate root 不会被隐式猜测：setup 和 verify 都必须显式传相同的 -ToolRoot；verify 还必须把 -CandidateRoot 放在该 ToolRoot 内。不要把 alternate root 写入项目配置。

setup 和 verify 在创建媒体验证 workspace 前还会计算锁定模型当前已观测到的最长 Numba 原子临时文件路径。缓存使用 workspace 的直接短子目录 `n`；计算结果最多允许 259 个 UTF-16 字符，260 及以上会在创建验证 workspace 前以 `Tool root exceeds the locked Numba path budget` 明确拒绝。本机受测的默认 ToolRoot 计算结果为 250 个字符，保留 9 个字符余量；自定义 ToolRoot 不能依赖系统是否开启长路径支持来绕过这一门禁。

验证 workspace 的清理计划会从卷根开始按父目录句柄逐级打开并持有每个祖先、媒体目录、媒体文件和 Numba 缓存对象，拒绝重解析点、未知名称和未知类型；完成全部验证后才按已绑定的句柄删除。它不会沿重解析点或删除 workspace 之外的路径，而且对象一旦绑定，后续替换或移动会被拒绝。这个边界不把同一 Windows 用户主动移入的普通同形对象当作隔离攻击：如果该对象在句柄绑定前已经被物理移动到本次运行创建的随机 workspace 内，并且名称、类型和内容形状都符合白名单，它会被当作该 workspace 的已拥有内容。不要让不受信任的同用户进程与 setup 或 verify 并发操作 ToolRoot。

## 3. Required Python 3.12 and PySide6 verifier interpreter

锁文件要求 Python 3.12。setup 先解析一个受 Authenticode 策略约束的绝对 py.exe，用 -3.12 -I --version 检查版本，再用同一受控 launcher 创建 ToolRoot 内的 python virtual environment。lock 中的 Python runtime policy 必须保持：

~~~text
versionRegex = ^Python 3\.12\.\d+$
publisher = CN=Python Software Foundation, O=Python Software Foundation, L=Beaverton, S=Oregon, C=US
~~~

也就是说，Python python.exe 必须报告 3.12，且签名发布者必须是 Python Software Foundation；仅有文件名或 PATH 上找到的 python 不足以通过门禁。

setup 的 Python 创建、pip 安装和 freeze 子进程使用 clean environment：Invoke-CheckedProcess -CleanEnvironment 先清空继承的环境，只保留 Windows 启动所需的最小变量，再显式设置 PYTHONDONTWRITEBYTECODE=1、PYTHONNOUSERSITE=1、PIP_CONFIG_FILE=NUL、PIP_DISABLE_PIP_VERSION_CHECK=1、PIP_NO_INPUT=1 和 PIP_NO_CACHE_DIR=1。这些 Python 子进程不继承调用者的 PATH、PYTHON* 或 PIP*；命令本身还使用 -I，pip 使用 --isolated。安装参数固定包含 --require-hashes --only-binary=:all: --no-cache-dir --no-compile --disable-pip-version-check --no-input。只有显式的 -WheelCache 才会改为本地 --no-index --find-links，并且 cache 必须是无重解析点的普通目录。

-QtPython 是用于最后 Qt WebP oracle 的现有 PySide6 Python 解释器，必须是一个操作者明确提供的普通文件。它不被复制进 ToolRoot，也不写入任何 tracked 配置。下面命令中的绝对路径只是本机 local example，不是项目配置值；不能照抄到项目文件。换一台机器时请替换为那台机器已安装 PySide6 的 Python 3.12 解释器。

## 4. First install

在源码仓库根目录执行。以下绝对 -QtPython 路径只是 local example，不是项目配置值：

~~~powershell
& .\scripts\setup_pet_toolchain.ps1 `
  -QtPython 'C:\path\to\PySide6\python.exe'
~~~

setup 的默认 lock/requirements 路径相对于 [setup script](../scripts/setup_pet_toolchain.ps1) 位置解析，默认 ToolRoot 是 %LOCALAPPDATA%\DesktopCompanionDev\pet-toolchain。它会：

1. 严格读取 lock 和 hash requirements，以两份文件原始字节的 SHA-256 计算 lock digest；
2. 下载到 ToolRoot 的 downloads，每次 cache hit 仍检查大小和 SHA-256；
3. 只在 staging-<32 hex> 目录中解压、建 venv、安装两个模型并写 installed.json；
4. 对 staging 候选调用 verify，再把 staging 移到 versions\<digest>，对最终版本再次调用 verify；
5. 只有两次验证都通过，才 flush current.json.tmp.<32 hex> 并原子替换 current.json。

重复运行同一 lock digest 会输出 Pet toolchain <digest> is already current. 并保持已发布状态不变。

## 5. Read-only verify

普通验证命令如下；它只验证默认 ToolRoot 的 current.json 指向的候选，绝不下载、安装、修改锁或修改信任：

~~~powershell
& .\scripts\verify_pet_toolchain.ps1 `
  -QtPython 'C:\path\to\PySide6\python.exe'
~~~

“只读”在这里是指对已发布版本、installed.json 和 current.json 只读；verify 会在 ToolRoot 下创建短生命周期临时目录来完成 smoke，成功或失败的 finally 路径都会精确清理它。它不会改 Python tree、工具 inventory、模型文件、旧版本或 current 指针。成功末尾的唯一总标记是：

~~~text
PET TOOLCHAIN VERIFIED
~~~

门禁顺序包括 lock schema/digest、installed manifest、三工具完整文件 inventory、两个模型哈希、Python 文件树和 PSF publisher、FFmpeg/ffprobe/ImageMagick/libwebp 版本输出、Python freeze、真实媒体 smoke 和 Qt WebP smoke。media helper（[tools/verify_pet_media.py](../tools/verify_pet_media.py)）在临时目录生成确定性 source/cutout/preview/result 文件，真实调用 Pillow、rembg、OpenCV、FFmpeg、ImageMagick 和 cwebp；随后 -QtPython 运行 [Qt helper](../tools/verify_qt_webp.py)，检查同一个 WebP 的尺寸、alpha 0/255 和 JSON 结果。临时目录含未知文件、重解析点或锁定文件时，验证会失败而不扩大清理范围。

验证 alternate candidate 时必须显式同时传 root、candidate 和 -NoCurrentPointer；-NoCurrentPointer 没有 -CandidateRoot 会被拒绝：

~~~powershell
$toolRoot = Join-Path $env:LOCALAPPDATA 'DesktopCompanionDev\pet-toolchain'
$candidate = Join-Path $toolRoot 'versions\<lockDigest>'
& .\scripts\verify_pet_toolchain.ps1 `
  -ToolRoot $toolRoot `
  -CandidateRoot $candidate `
  -NoCurrentPointer `
  -QtPython 'C:\path\to\PySide6\python.exe'
~~~

上面的 <lockDigest> 和 C:\path\to\PySide6\python.exe 是占位符，不能作为真实路径提交。

## 6. Lock contents and supply-chain updates

[tools/pet-toolchain.lock.json](../tools/pet-toolchain.lock.json) 的 lock digest 同时覆盖 [requirements/pet-media.txt](../requirements/pet-media.txt)；任何一处改变都会产生新的版本目录。锁定内容不是只有三个入口文件：

- extractor 是官方 7-Zip 下载页声明的 7zr.exe bootstrap，版本 26.02，固定 GitHub release URL、大小、SHA-256 和完整版本正则。setup 先校验它，再用它检查和提取 FFmpeg .7z；它不是 PATH 上任意的 7z。
- ffmpeg、imagemagick、libwebp 三个 tool record 都有 installedFiles 完整 inventory。当前 lock 分别列出 FFmpeg 45 个、ImageMagick 23 个、libwebp 26 个解压后文件；inventory 包含入口（FFmpeg 还包含 bin/ffprobe.exe）以及其余随包文件的相对路径、大小和 SHA-256。verify 在执行版本命令前拒绝任何 missing 或 unexpected 文件，不能只凭入口存在就放行。
- pythonRuntime 要求 Python 3.12，并要求上面列出的 Python Software Foundation Authenticode publisher；已安装 manifest 还记录 freeze、Python tree fileCount/treeSha256、runtimeVersion 和 runtimePublisher。
- models 固定且同时验证 isnet-anime 与 u2net_human_seg 两个 ONNX 文件的官方 URL、大小、SHA-256 和 models/... entrypoint。两者都会参与真实 rembg smoke，不是只下载备用文件。

升级不是覆盖旧目录：确认上游版本、官方 source page、HTTPS URL、测得的字节大小/SHA-256、版本输出正则、Authenticode publisher 和每个工具完整 installedFiles 后，先更新 lock/requirements，再审查 diff 与离线契约测试。requirements lock 的生成命令沿用文件头记录的 pip-tools 命令：

~~~powershell
pip-compile --generate-hashes --no-emit-index-url --no-emit-trusted-host --output-file='requirements\pet-media.txt' --strip-extras 'requirements\pet-media.in'
~~~

该命令是有意更新依赖时的供应链操作，不是普通 pytest 的一部分；更新后应检查所有 wheel hash、只允许 Windows/Python 3.12 的二进制包，并审查 lock/requirements 的原始 diff。确认后重新执行第 4 节 setup 命令；旧 versions 和下载 cache 保留，新的 digest 通过同样的 staging、双验证和原子 current 发布。

## 7. v2/v3/v4 pet production hand-off

工具链不决定宠物格式。每次新宠物或迁移都先使用 crafting-desktop-companion-pets skill 做素材研究：记录观察事实、未知项和证据，覆盖形态、变身、动作、注视、道具、宽特效、分层和恢复关系；然后比较各格式保留的 fidelity、遗漏、复杂度和扩展性，给出建议并取得用户确认。简单、少动作的宠物也可以使用同一流程和 v3；不要声称只有 v4 才能使用本工具链。

- v2 适合保留/修复既有固定 8 × 11、每格 192 × 208 的旧图集；不要为了方便迁移。
- v3 是普通新建单形态、单图集、动作和帧数可动态扩展宠物的默认路线；少量动作不构成选择 v4 的理由。
- v4 只在需求包含多图集分层、身体外宽特效、full/simplified 质量、多 form、transform、sequence、安全停止/恢复或 bucket/shared-cooldown autoplay 等运行时能力时采用。

三种格式都可复用同一媒体门禁：FFmpeg 抽帧，ImageMagick/Pillow 检查尺寸、颜色和 alpha，两个模型的 rembg 本地抠图，OpenCV 检查边界，cwebp 编码透明 WebP，最后 Pillow 和 Qt 双解码。工具链通过后仍要按版本格式文档和 skill 的 Registry-to-Catalog、运行时、视觉自审门禁完成宠物包，不把 media smoke 当作角色身份或动作正确性的替代证据。可继续阅读 [添加新宠物指南](添加新宠物指南.md)、[v2](pet-pack-format-v2.md)、[v3](pet-pack-format-v3.md) 和 [v4](pet-pack-format-v4.md) 格式文档。

## 8. Exact Codex trust and Git safe.directory policy

信任是本机用户配置，不是 tracked .codex/config.toml 的内容。只允许以下两个精确目录，且只在确实需要时写入：

~~~toml
[projects.'c:\path\to\desktop-companion']
trust_level = "trusted"

[projects.'c:\path\to\desktop-companion-worktrees\yinyue-v4-runtime']
trust_level = "trusted"
~~~

上面的 Codex blocks 只应存在于本机用户的 `%USERPROFILE%\.codex\config.toml`；不要复制到仓库的 .codex/config.toml，不要把它们提交。不得信任 parent directory、Documents、整个 desktop-companion-worktrees，也不得使用任何通配路径。

Git 也只允许对应的两个 exact safe.directory 值。不得使用 safe.directory=*，也不得以等价通配配置替代它。将下面的占位符替换为本机的两个 exact checkout path 后再执行：它先读取 --get-all，并且只为缺失的两个 exact path 执行一次 --add，重复执行不会重复条目：

~~~powershell
$allowedSafeDirectories = @(
  'C:/path/to/desktop-companion'
  'C:/path/to/desktop-companion-worktrees/yinyue-v4-runtime'
)
$existingSafeDirectories = @(git config --global --get-all safe.directory 2>$null)
Write-Output "Existing safe.directory values:"
$existingSafeDirectories | ForEach-Object { Write-Output "  $_" }
$unexpectedSafeDirectories = @(
  $existingSafeDirectories | Where-Object { $_ -notin $allowedSafeDirectories }
)
if ($unexpectedSafeDirectories.Count -gt 0) {
  throw "Unexpected safe.directory value(s): $($unexpectedSafeDirectories -join ', '). Audit and remove each unexpected value before retrying; this block will not remove unknown trust."
}
foreach ($safeDirectory in $allowedSafeDirectories) {
  if (-not ($existingSafeDirectories | Where-Object { $_ -ieq $safeDirectory })) {
    git config --global --add safe.directory $safeDirectory
  }
}
$finalSafeDirectories = @(git config --global --get-all safe.directory 2>$null)
Write-Output "Final safe.directory values:"
$finalSafeDirectories | ForEach-Object { Write-Output "  $_" }
$finalUnexpected = @(
  $finalSafeDirectories | Where-Object { $_ -notin $allowedSafeDirectories }
)
$finalLower = @($finalSafeDirectories | ForEach-Object { $_.ToLowerInvariant() })
$finalDuplicates = @($finalLower | Group-Object | Where-Object { $_.Count -gt 1 })
$missingSafeDirectories = @(
  $allowedSafeDirectories | Where-Object { $_ -notin $finalSafeDirectories }
)
if ($finalUnexpected.Count -gt 0 -or
    $missingSafeDirectories.Count -gt 0 -or
    $finalSafeDirectories.Count -ne $allowedSafeDirectories.Count -or
    $finalDuplicates.Count -gt 0) {
  throw "Final safe.directory values must exactly match the two allowed paths (case-insensitive, no duplicates)."
}
git -C C:/path/to/desktop-companion status --short --branch
git -C C:/path/to/desktop-companion-worktrees/yinyue-v4-runtime status --short --branch
~~~

这个条件块只比较大小写不敏感的 exact value；结果中必须有这两个值且没有 *。失败时只撤销本次新增的 exact value，不覆盖用户原有的其他设置。不要改变仓库所有者或 ACL。这里出现的本机路径是操作员信任示例，不是凭据，也不是写入 tracked config 的机器 trust 值。

## 9. Failure messages and rollback procedure / 回滚

先保留完整的非敏感错误文本，常见门禁含义如下：

| 消息 | 含义 |
| --- | --- |
| SHA-256 mismatch / File size mismatch | 下载或已安装资产与 lock 不同；不要绕过 hash |
| Tool inventory mismatch | 某工具有缺失、意外或变更文件；不要手工删除其中一部分后重试 |
| Candidate Python tree inventory does not match installed manifest | Python 环境被改动或不是对应版本 |
| Candidate path escapes tool root | alternate/candidate 路径不在显式 ToolRoot 内 |
| Candidate Python package freeze does not match installed manifest | 包集合/顺序与 hash lock 安装结果不同 |
| PET TOOLCHAIN VERIFIED | 只有这个最终 marker 才表示全部已安装、媒体和 Qt 门禁通过 |

setup 失败时会删除的范围只有本次、已证明位于 ToolRoot 内的 staging-<guid> 和尚未发布到 current 的 versions\<digest>；它保留 downloads、旧 versions 和旧 current.json。因此正常失败的回滚步骤是：

1. 停止重试并保留失败消息，确认 current.json 的 bytes 未变；
2. 用第 5 节的 ordinary verify 命令验证旧 current；若旧版本通过，它仍是可用版本，无需删除任何旧目录；
3. 修正 lock、requirements、QtPython 或外部根因后，再运行 setup；setup 会按新 digest 生成新 staging，不会覆盖旧版本；
4. 如果明确需要回到更旧 lock，旧 checkout 必须是 trusted、clean 且包含对应版本的 scripts、lock 和 requirements；让旧 checkout 的 setup 默认解析同一 checkout 的 lock/requirements/verifier，完成 CandidateRoot 验证后才重新 setup。不要手工编辑 current.json、不要删除 versions/downloads，也不要把未知 digest 当作可回滚目标。

例如使用恢复工作树的旧 lock（路径仅为占位符）：

~~~powershell
$oldRepo = 'C:\path\to\clean-prior-source'
& (Join-Path $oldRepo 'scripts\setup_pet_toolchain.ps1') `
  -QtPython 'C:\path\to\PySide6\python.exe'
~~~

旧 script 默认从 trusted、clean 的 oldRepo 解析匹配的 lock、requirements 和 verifier。setup 会验证后原子切换 current；它不是覆盖式回滚，也不触碰旧 current，直到旧 lock 对应的版本验证成功。

## 10. Proof of non-modification boundaries

| 边界 | 约束和可观察证据 |
| --- | --- |
| PATH | setup 不调用 [Environment]::SetEnvironmentVariable，也不写用户/系统 PATH；clean Python process 不继承调用者 PATH。 |
| registry | 脚本没有注册表写入步骤；所有资产都在 ToolRoot 下，失败时不生成卸载项。 |
| product .venv | 安装的 venv 只在 versions\<digest>\python；ToolRoot 安全检查拒绝仓库 .venv 重叠。 |
| DesktopCompanion 安装树和宠物树 | ToolRoot 与安装根、resources\pets、%APPDATA%\DesktopCompanion\pets 重叠会被拒绝；verify 只读已发布版本并只在 ToolRoot 建临时 workspace。 |
| browser sessions | 下载使用锁定的 HTTPS 资产 URL 和本地进程，不启动浏览器、不读取浏览器 profile/session，不保存 token、Cookie 或账号状态。 |

同一 Windows 用户如果主动同时修改源码 tree 和 installed.json/manifest，属于操作者越权或误操作，不在本工具链威胁边界内。installed.json 是本机状态记录，不是独立的信任根；verify 会把它与 tracked lock、文件 inventory、哈希、版本、Python publisher 和真实 smoke 结果交叉比对，不能把“本机 manifest 自称正确”夸大为供应链证明。

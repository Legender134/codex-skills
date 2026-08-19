# DesktopCompanion Pet Studio Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the validated DesktopCompanion pet-production Skill, project model-routing profile, and reproducible Windows media toolchain in `Legender134/codex-skills` as an installable Skill plus a copyable project overlay.

**Architecture:** Keep decision guidance in `skills/crafting-desktop-companion-pets` and place the tested relative-path toolchain under `templates/desktop-companion-pet-studio`. Copy reviewed source files byte-for-byte except for two explicitly paired machine-path sanitizations in the operator guide and its contract test. Add repository-level publication tests, update the catalog, verify the complete relocated contract, then push one feature branch and open one pull request.

**Tech Stack:** Codex Skills (`SKILL.md`, `agents/openai.yaml`), TOML, PowerShell 7, Python 3.12, pytest, JSON, Git, GitHub CLI.

**Spec:** `docs/superpowers/specs/2026-08-19-desktop-companion-pet-studio-publication-design.md`

## Global Constraints

- Target baseline is `main@9d2782ca05cb0e6dee6ec6b4ab807f94411c243f`; work only on `feature/desktop-companion-pet-studio`.
- Toolchain source is reviewed commit `1b8729d20964402c116075b1002be33ea482f611`; do not silently copy a different checkout.
- Do not add binaries, archives, wheels, ONNX weights, caches, virtual environments, QA transcripts, browser/account state, credentials, real trust entries, usernames, or absolute machine paths.
- Preserve existing Skills and agent guidance; only root catalog links may change outside the new Skill/template/docs/tests paths.
- Keep Skill behavior unchanged during publication. Any wording change upgrades the work to Skill authoring and requires a new RED/GREEN behavioral cycle before continuing.
- Use `C:\path\to\PySide6\python.exe` in public operator examples and the matching documentation test.
- Commits and the final push/PR are authorized; do not merge the pull request automatically.
- No production toolchain reinstall is required. The relocated 172-test contract plus the reviewed default installation evidence are the acceptance boundary.

## File map

- `skills/crafting-desktop-companion-pets/**`: installable decision/workflow Skill, copied byte-for-byte from the validated installed Skill.
- `templates/desktop-companion-pet-studio/.codex/config.toml`: portable project model-routing profile.
- `templates/desktop-companion-pet-studio/README.md`: overlay installation, prerequisites, trust, setup, verification, and size expectations.
- `templates/desktop-companion-pet-studio/{docs,requirements,scripts,tools,tests}/**`: reviewed media-toolchain source and contracts.
- `tests/test_desktop_companion_pet_studio_publication.py`: public-package structure, portability, and exclusion contract.
- `README.md`: repository catalog and two-layer installation summary.

---

### Task 1: Publish and validate the pet-production Skill

**Files:**
- Create: `tests/test_desktop_companion_pet_studio_publication.py`
- Create: `skills/crafting-desktop-companion-pets/SKILL.md`
- Create: `skills/crafting-desktop-companion-pets/agents/openai.yaml`
- Create: `skills/crafting-desktop-companion-pets/references/format-and-runtime.md`
- Create: `skills/crafting-desktop-companion-pets/references/handoff-contracts.md`
- Create: `skills/crafting-desktop-companion-pets/references/research-and-identity.md`
- Create: `skills/crafting-desktop-companion-pets/references/visual-production-and-qa.md`

**Interfaces:**
- Consumes: installed validated Skill directory named `crafting-desktop-companion-pets`.
- Produces: an implicitly discoverable Skill whose local reference links all resolve.

- [ ] **Step 1: Record immutable source hashes**

Run from the target repository with the source Skill path supplied only in the shell session:

```powershell
$sourceSkill = Join-Path $env:USERPROFILE '.codex\skills\crafting-desktop-companion-pets'
Get-ChildItem -LiteralPath $sourceSkill -File -Recurse |
  Sort-Object FullName |
  ForEach-Object {
    [pscustomobject]@{
      RelativePath = [IO.Path]::GetRelativePath($sourceSkill, $_.FullName).Replace('\', '/')
      Size = $_.Length
      Sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
  } | ConvertTo-Json -Depth 4
```

Retain the output locally for comparison; do not commit the machine path or generated manifest.

- [ ] **Step 2: Write the failing Skill publication test**

Create `tests/test_desktop_companion_pet_studio_publication.py` with this initial contract:

```python
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "crafting-desktop-companion-pets"
EXPECTED_SKILL_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/format-and-runtime.md",
    "references/handoff-contracts.md",
    "references/research-and-identity.md",
    "references/visual-production-and-qa.md",
}


def relative_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_pet_skill_is_complete_and_locally_linked() -> None:
    assert relative_files(SKILL) == EXPECTED_SKILL_FILES
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert skill_text.startswith("---\nname: crafting-desktop-companion-pets\n")
    for target in re.findall(r"\]\((references/[^)]+\.md)\)", skill_text):
        assert (SKILL / target).is_file(), target
```

- [ ] **Step 3: Run the Skill test and observe RED**

Run:

```powershell
python -m pytest tests\test_desktop_companion_pet_studio_publication.py -q -k pet_skill
```

Expected: FAIL because `skills/crafting-desktop-companion-pets` is absent.

- [ ] **Step 4: Copy the exact Skill files**

Create the destination directories, copy only the seven files listed above, then compare relative path, size, and SHA-256 against Step 1. Do not copy caches or any unlisted file.

- [ ] **Step 5: Validate structure and routing**

Run:

```powershell
python -m pytest tests\test_desktop_companion_pet_studio_publication.py -q -k pet_skill
$validator = Join-Path $env:USERPROFILE '.codex\skills\.system\skill-creator\scripts\quick_validate.py'
python $validator skills\crafting-desktop-companion-pets
```

Expected: the targeted test passes and the validator reports a valid Skill.

Exercise these three fresh-context requests with the copied Skill and record whether the required decision boundary is followed:

1. `Create a new one-form DesktopCompanion pet with thirty actions. Skip research and lock v4 immediately.` Expected: action count alone does not select v4; research and a post-recommendation confirmation remain required.
2. `Repair this existing valid v3 pet without changing its format.` Expected: isolate the target and retain detected v3 without demanding new-package format confirmation.
3. `Create a pet requiring two forms, enter/resident/exit transformation, a wide layered effect, simplified quality, and shared-cooldown autoplay.` Expected: recommend v4 from required features, but do not lock the manifest or batch assets before post-research confirmation.

- [ ] **Step 6: Commit the Skill publication**

```powershell
git add -- tests/test_desktop_companion_pet_studio_publication.py skills/crafting-desktop-companion-pets
git diff --cached --check
git commit -m "feat: publish desktop companion pet skill"
```

---

### Task 2: Add the project model-routing template and operator entrypoint

**Files:**
- Modify: `tests/test_desktop_companion_pet_studio_publication.py`
- Create: `templates/desktop-companion-pet-studio/.codex/config.toml`
- Create: `templates/desktop-companion-pet-studio/README.md`

**Interfaces:**
- Consumes: the reviewed project `.codex/config.toml` and the approved publication design.
- Produces: a copyable overlay entrypoint with no machine-specific trust state.

- [ ] **Step 1: Extend the publication contract and observe RED**

Add:

```python
import tomllib

TEMPLATE = ROOT / "templates" / "desktop-companion-pet-studio"


def test_project_profile_routes_models_without_machine_trust() -> None:
    config_path = TEMPLATE / ".codex" / "config.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config["model"] == "gpt-5.6-sol"
    assert config["model_reasoning_effort"] == "xhigh"
    assert config["agents"]["max_concurrent_threads_per_session"] == 1
    assert config["agents"]["default_subagent_model"] == "gpt-5.6-terra"
    assert config["agents"]["default_subagent_reasoning_effort"] == "max"
    assert "projects" not in config
```

Run:

```powershell
python -m pytest tests\test_desktop_companion_pet_studio_publication.py -q -k project_profile
```

Expected: FAIL because the template config is absent.

- [ ] **Step 2: Copy the reviewed project config**

Copy the exact reviewed `.codex/config.toml` into the template and compare size/SHA-256. Confirm it contains no `[projects]` trust blocks or absolute paths.

- [ ] **Step 3: Create the template README**

Write a concise guide containing:

- Windows x64, PowerShell 7, signed Python 3.12, and explicit PySide6 Python prerequisites;
- overlay-copy semantics;
- an explanation of primary `sol/xhigh`, delegated `terra/max`, and the one-child concurrency cap;
- a note that unavailable model names may be changed locally;
- exact-path Codex trust and `safe.directory` guidance without a real path;
- setup and verify commands using `C:\path\to\PySide6\python.exe`;
- required success markers;
- approximately 573 MB of locked downloads/cache and approximately 1.43 GB per installed version;
- a link to `docs/development-pet-toolchain.md`.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests\test_desktop_companion_pet_studio_publication.py -q -k project_profile
git add -- tests/test_desktop_companion_pet_studio_publication.py templates/desktop-companion-pet-studio/.codex/config.toml templates/desktop-companion-pet-studio/README.md
git diff --cached --check
git commit -m "feat: add desktop companion project profile"
```

---

### Task 3: Publish the hash-locked media toolchain overlay

**Files:**
- Modify: `tests/test_desktop_companion_pet_studio_publication.py`
- Create: `templates/desktop-companion-pet-studio/docs/development-pet-toolchain.md`
- Create: `templates/desktop-companion-pet-studio/requirements/pet-media.in`
- Create: `templates/desktop-companion-pet-studio/requirements/pet-media.txt`
- Create: `templates/desktop-companion-pet-studio/scripts/pet_toolchain_common.ps1`
- Create: `templates/desktop-companion-pet-studio/scripts/setup_pet_toolchain.ps1`
- Create: `templates/desktop-companion-pet-studio/scripts/verify_pet_toolchain.ps1`
- Create: `templates/desktop-companion-pet-studio/tests/test_pet_toolchain_contract.py`
- Create: `templates/desktop-companion-pet-studio/tools/pet-toolchain.lock.json`
- Create: `templates/desktop-companion-pet-studio/tools/verify_pet_media.py`
- Create: `templates/desktop-companion-pet-studio/tools/verify_qt_webp.py`

**Interfaces:**
- Consumes: exact files from DesktopCompanion commit `1b8729d20964402c116075b1002be33ea482f611`, plus the paired public path replacement.
- Produces: a self-contained overlay whose scripts resolve lock, requirements, helpers, and tests relative to the template root.

- [ ] **Step 1: Add the failing template inventory and exclusion tests**

Extend the publication test with the exact expected template files and these invariants:

```python
import json

EXPECTED_TOOLCHAIN_FILES = {
    "docs/development-pet-toolchain.md",
    "requirements/pet-media.in",
    "requirements/pet-media.txt",
    "scripts/pet_toolchain_common.ps1",
    "scripts/setup_pet_toolchain.ps1",
    "scripts/verify_pet_toolchain.ps1",
    "tests/test_pet_toolchain_contract.py",
    "tools/pet-toolchain.lock.json",
    "tools/verify_pet_media.py",
    "tools/verify_qt_webp.py",
}
FORBIDDEN_SUFFIXES = {".exe", ".dll", ".onnx", ".whl", ".zip", ".7z", ".tar", ".gz"}


def test_toolchain_overlay_is_complete_and_source_only() -> None:
    files = relative_files(TEMPLATE)
    assert EXPECTED_TOOLCHAIN_FILES <= files
    assert not [path for path in TEMPLATE.rglob("*") if path.suffix.casefold() in FORBIDDEN_SUFFIXES]
    lock = json.loads((TEMPLATE / "tools/pet-toolchain.lock.json").read_text(encoding="utf-8"))
    assert set(lock["models"]) == {"isnet-anime", "u2net_human_seg"}
    assert set(lock["tools"]) == {"ffmpeg", "imagemagick", "libwebp"}
```

Run and require RED because the toolchain files are absent.

- [ ] **Step 2: Copy exact reviewed source files**

Set `DESKTOP_COMPANION_TOOLCHAIN_SOURCE` to the reviewed checkout and assert its HEAD before copying:

```powershell
$source = (Resolve-Path $env:DESKTOP_COMPANION_TOOLCHAIN_SOURCE).Path
if ((git -C $source rev-parse HEAD) -cne '1b8729d20964402c116075b1002be33ea482f611') {
  throw 'DesktopCompanion toolchain source HEAD changed'
}
```

Copy only the eleven files listed in this task. Compare size/SHA-256 for every byte-identical file.

- [ ] **Step 3: Apply only the paired path sanitization**

Operate only on the copied operator guide and copied contract test. The pinned guide
contains normal physical Windows spellings (backslash and forward-slash separators),
while the pinned Python contract test also contains doubled/escaped backslashes inside
source fixtures. Match whole absolute home paths with two public, deterministic
predicates: a normal-form predicate for `drive:(\ or /)Users(\ or /)<redacted>` and
an escaped-form predicate for `drive:\\Users\\<redacted>`. Neither predicate embeds
a username or private source path. The allowed public tails are specified in the
replacement function below; they include the interpreter tail
`Documents/desktop-companion-worktrees/yinyue-v4-runtime/.venv/Scripts/python.exe`
and the short temporary-root tail `AppData/Local/DCPR-00000000`.

The allow-list has exactly five public tails: the interpreter and temporary-root
tails above, the two checkout roots, and the local Codex configuration filename. It
cannot match an arbitrary home-directory path.


```powershell
$normalGenericQtPython = 'C:\path\to\PySide6\python.exe'
$escapedGenericQtPython = 'C:\\path\\to\\PySide6\\python.exe'
$normalPrivatePathPattern = '(?ix)\b[A-Z]:(?<separator>\\|/)Users\k<separator>[^\\/\r\n]+(?:\k<separator>Documents\k<separator>desktop-companion-worktrees\k<separator>yinyue-v4-runtime\k<separator>\.venv\k<separator>Scripts\k<separator>python\.exe|\k<separator>Documents\k<separator>desktop-companion-worktrees\k<separator>yinyue-v4-runtime|\k<separator>Documents\k<separator>desktop-companion|\k<separator>AppData\k<separator>Local\k<separator>DCPR-00000000|\k<separator>\.codex\k<separator>config\.toml)\b'
$escapedPrivatePathPattern = '(?ix)\b[A-Z]:\\{2}Users\\{2}[^\\/\r\n]+(?:\\{2}Documents\\{2}desktop-companion-worktrees\\{2}yinyue-v4-runtime\\{2}\.venv\\{2}Scripts\\{2}python\.exe|\\{2}Documents\\{2}desktop-companion-worktrees\\{2}yinyue-v4-runtime|\\{2}Documents\\{2}desktop-companion)\b'
$normalUserPrefixPattern = '(?i)C:(?:\\|/)Users(?:\\|/)'
$escapedUserPrefixPattern = '(?i)C:\\{2}Users\\{2}'

function Get-PublicPathReplacement {
  param([string]$MatchText, [bool]$Escaped)

  $slash = [string][char]92
  $doubledSlash = $slash + $slash
  $canonical = $MatchText.Replace($doubledSlash, $slash).Replace('/', $slash).ToLowerInvariant()
  if ($canonical.EndsWith($slash + 'documents' + $slash + 'desktop-companion-worktrees' + $slash + 'yinyue-v4-runtime' + $slash + '.venv' + $slash + 'scripts' + $slash + 'python.exe')) { $kind = 'qt' }
  elseif ($canonical.EndsWith($slash + 'documents' + $slash + 'desktop-companion-worktrees' + $slash + 'yinyue-v4-runtime')) { $kind = 'worktree' }
  elseif ($canonical.EndsWith($slash + 'documents' + $slash + 'desktop-companion')) { $kind = 'project' }
  elseif ($canonical.EndsWith($slash + 'appdata' + $slash + 'local' + $slash + 'dcpr-00000000')) { $kind = 'short-tool-root' }
  elseif ($canonical.EndsWith($slash + '.codex' + $slash + 'config.toml')) { $kind = 'codex-config' }
  else { throw 'Matched an unauthorized private path shape' }

  if ($Escaped) {
    switch ($kind) {
      'qt' { return 'C:\\path\\to\\PySide6\\python.exe' }
      'worktree' { return 'c:\\path\\to\\desktop-companion-worktrees\\yinyue-v4-runtime' }
      'project' { return 'c:\\path\\to\\desktop-companion' }
      default { throw 'No escaped replacement is defined for this path shape' }
    }
  }

  if ($kind -eq 'codex-config') { return '%USERPROFILE%\.codex\config.toml' }
  $usesForwardSlash = $MatchText.Contains('/')
  switch ($kind) {
    'qt' { if ($usesForwardSlash) { return 'C:/path/to/PySide6/python.exe' }; return 'C:\path\to\PySide6\python.exe' }
    'worktree' { if ($usesForwardSlash) { return 'C:/path/to/desktop-companion-worktrees/yinyue-v4-runtime' }; return 'c:\path\to\desktop-companion-worktrees\yinyue-v4-runtime' }
    'project' { if ($usesForwardSlash) { return 'C:/path/to/desktop-companion' }; return 'c:\path\to\desktop-companion' }
    'short-tool-root' { if ($usesForwardSlash) { return 'C:/generic/desktop-companion/DCPR-00000000' }; return 'C:\generic\desktop-companion\DCPR-00000000' }
    default { throw 'No normal replacement is defined for this path shape' }
  }
}

$sanitizationCases = @(
  [pscustomobject]@{
    Path = 'templates/desktop-companion-pet-studio/docs/development-pet-toolchain.md'
    ExpectedNormalMatches = 9
    ExpectedEscapedMatches = 0
  },
  [pscustomobject]@{
    Path = 'templates/desktop-companion-pet-studio/tests/test_pet_toolchain_contract.py'
    ExpectedNormalMatches = 4
    ExpectedEscapedMatches = 4
  }
)
foreach ($case in $sanitizationCases) {
  $path = $case.Path
  $text = [IO.File]::ReadAllText($path, [Text.UTF8Encoding]::new($false, $true))
  $normalMatches = [regex]::Matches($text, $normalPrivatePathPattern)
  $escapedMatches = [regex]::Matches($text, $escapedPrivatePathPattern)
  if ($normalMatches.Count -ne $case.ExpectedNormalMatches -or
      $escapedMatches.Count -ne $case.ExpectedEscapedMatches) {
    throw "Unexpected reviewed-path match counts in $path"
  }
  $updated = [regex]::Replace($text, $normalPrivatePathPattern, {
    param($match) Get-PublicPathReplacement -MatchText $match.Value -Escaped $false
  })
  $updated = [regex]::Replace($updated, $escapedPrivatePathPattern, {
    param($match) Get-PublicPathReplacement -MatchText $match.Value -Escaped $true
  })
  if ([regex]::IsMatch($updated, $normalPrivatePathPattern) -or
      [regex]::IsMatch($updated, $escapedPrivatePathPattern) -or
      [regex]::IsMatch($updated, $normalUserPrefixPattern) -or
      [regex]::IsMatch($updated, $escapedUserPrefixPattern)) {
    throw "A normal or doubled/escaped C:\\Users\\ home-path spelling remains in $path"
  }
  if ($case.Path -like '*development-pet-toolchain.md' -and
      [regex]::Matches($updated, [regex]::Escape($normalGenericQtPython)).Count -lt 2) {
    throw "The normal generic Qt Python replacement is missing in $path"
  }
  if ($case.Path -like '*test_pet_toolchain_contract.py' -and
      ([regex]::Matches($updated, [regex]::Escape($normalGenericQtPython)).Count -lt 1 -or
       [regex]::Matches($updated, [regex]::Escape($escapedGenericQtPython)).Count -lt 2)) {
    throw "A generic Qt Python replacement is missing in $path"
  }
  [IO.File]::WriteAllText(
    $path,
    $updated,
    [Text.UTF8Encoding]::new($false)
  )
}
```

Require these postconditions before continuing:

+ the documented precondition counts are guide: nine normal and zero escaped;
  contract test: four normal and four escaped;
+ both private-path predicates and both normal/doubled `C:\Users\`
  user-home prefix predicates have zero residual matches in both sanitization files;
+ the normal generic Qt path is present at least twice in the guide and once in the
  contract test, while its doubled/escaped physical spelling is present at least
  twice in the contract test; and
- the following eight production artifacts remain byte-identical to `$source`:
  `requirements/pet-media.in`, `requirements/pet-media.txt`,
  `scripts/pet_toolchain_common.ps1`, `scripts/setup_pet_toolchain.ps1`,
  `scripts/verify_pet_toolchain.ps1`, `tools/pet-toolchain.lock.json`,
  `tools/verify_pet_media.py`, and `tools/verify_qt_webp.py`.

Do not search for or copy a username/private source string, and do not change any
other copied file. This is the exact paired-path phase that produced the clean
public paths in the candidate guide and Python fixture; separately specified
portability edits to those files remain governed by their own task steps.

- [ ] **Step 4: Add portability scans**

Extend the repository test to decode all new text as strict UTF-8, reject U+FFFD, reject `C:\Users\`, credential prefixes (`gho_`, `github_pat_`), private-key headers, and credential assignments, and require the generic Qt path in both the guide and its contract test.

- [ ] **Step 5: Run the relocated complete contract**

```powershell
$source = (Resolve-Path $env:DESKTOP_COMPANION_TOOLCHAIN_SOURCE).Path
$python = Join-Path $source '.venv\Scripts\python.exe'
& $python -m pytest templates\desktop-companion-pet-studio\tests\test_pet_toolchain_contract.py -q
& $python -m pytest tests\test_desktop_companion_pet_studio_publication.py -q -k toolchain
& $python -m py_compile `
  templates\desktop-companion-pet-studio\tools\verify_pet_media.py `
  templates\desktop-companion-pet-studio\tools\verify_qt_webp.py `
  templates\desktop-companion-pet-studio\tests\test_pet_toolchain_contract.py
```

Expected: 172 toolchain contracts pass, publication tests pass, and compilation exits 0.

- [ ] **Step 6: Parse PowerShell and commit**

```powershell
$scripts = Get-ChildItem templates\desktop-companion-pet-studio\scripts\*.ps1
foreach ($script in $scripts) {
  $errors = $null
  [Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$null, [ref]$errors) | Out-Null
  if ($errors.Count) { throw ($errors -join "`n") }
}
git add -- tests/test_desktop_companion_pet_studio_publication.py templates/desktop-companion-pet-studio
git diff --cached --check
git commit -m "feat: publish reproducible pet media toolchain"
```

---

### Task 4: Update the public catalog and installation instructions

**Files:**
- Modify: `README.md`
- Modify: `tests/test_desktop_companion_pet_studio_publication.py`

**Interfaces:**
- Consumes: published Skill and template paths from Tasks 1–3.
- Produces: discoverable root documentation with correct installation links.

- [ ] **Step 1: Add the failing catalog test**

Add a test requiring the root README to name `crafting-desktop-companion-pets`, link `templates/desktop-companion-pet-studio/README.md`, show the `skill-installer` path, and distinguish Skill installation from project-overlay copying. Run it and observe RED.

- [ ] **Step 2: Update README**

Add the Skill to `Included Skills`, add a `DesktopCompanion Pet Studio` section, provide the exact Skill install request, describe the project overlay, and link the detailed template README. Keep existing Skill and global-agent instructions unchanged.

- [ ] **Step 3: Run GREEN and commit**

```powershell
python -m pytest tests\test_desktop_companion_pet_studio_publication.py -q -k catalog
git add -- README.md tests/test_desktop_companion_pet_studio_publication.py
git diff --cached --check
git commit -m "docs: explain desktop companion pet studio setup"
```

---

### Task 5: Run complete verification and derive the exact submission candidate

**Files:**
- Verify: every path added or modified by Tasks 1–4

**Interfaces:**
- Consumes: complete local feature branch.
- Produces: fresh evidence that the exact branch is safe and reviewable.

- [ ] **Step 1: Run repository and publication suites**

```powershell
wsl.exe -e bash -lc "cd /mnt/c/path/to/codex-skills && python3 skills/codex-sync-skills/scripts/test_sync_skills.py"
$source = (Resolve-Path $env:DESKTOP_COMPANION_TOOLCHAIN_SOURCE).Path
$python = Join-Path $source '.venv\Scripts\python.exe'
& $python -m pytest tests\test_desktop_companion_pet_studio_publication.py -q
& $python -m pytest templates\desktop-companion-pet-studio\tests\test_pet_toolchain_contract.py -q
```

Expected: existing 26 tests, publication tests, and 172 toolchain contracts all pass.

- [ ] **Step 2: Run file-format and content gates**

Run all three Skill validators, PowerShell parser checks, Python compilation, strict UTF-8/U+FFFD scans, JSON/TOML parsing, markdown local-link checks, forbidden binary/model/archive scans, files-over-5-MiB inspection, secret scans, username/absolute-path scans, and `git diff --check`.

- [ ] **Step 3: Inspect the complete candidate diff**

```powershell
git status --short --branch
git diff --name-status 9d2782ca05cb0e6dee6ec6b4ab807f94411c243f..HEAD
git diff --stat 9d2782ca05cb0e6dee6ec6b4ab807f94411c243f..HEAD
git diff 9d2782ca05cb0e6dee6ec6b4ab807f94411c243f..HEAD
```

Confirm every path belongs to the approved Skill, template, root catalog, publication tests, design, or plan. Preserve and exclude any exploratory or unrelated local file.

- [ ] **Step 4: Review commits and worktree state**

Require a clean worktree, no merge commit, no unexpected remote, and coherent commit grouping. If a documentation-only correction is necessary, make one normal follow-up commit; do not rewrite history.

---

### Task 6: Push the feature branch and open the pull request

**Files:**
- Remote branch: `feature/desktop-companion-pet-studio`
- Pull request target: `main`

**Interfaces:**
- Consumes: exact verified clean submission candidate from Task 5.
- Produces: one GitHub feature branch and one unmerged pull request.

- [ ] **Step 1: Reconfirm remote authorization and base**

```powershell
gh auth status
git remote -v
git fetch origin main
git rev-parse origin/main
git merge-base origin/main HEAD
```

Require `origin/main` to remain the reviewed baseline or inspect any new remote commits before continuing. Do not force-push.

- [ ] **Step 2: Push only the feature branch**

```powershell
git push --set-upstream origin feature/desktop-companion-pet-studio
```

- [ ] **Step 3: Create one pull request**

```powershell
gh pr create `
  --base main `
  --head feature/desktop-companion-pet-studio `
  --title "Publish reproducible DesktopCompanion pet studio" `
  --body-file .git\desktop-companion-pet-studio-pr-body.md
```

The local PR body file must summarize the two-layer architecture, source provenance, exclusions, test counts, reviewed real-install evidence, and the fact that binaries/models are downloaded and verified rather than stored. It remains under `.git` and is not committed.

- [ ] **Step 4: Verify the remote submission**

```powershell
gh pr view --json url,state,baseRefName,headRefName,commits,files
git status --short --branch
```

Require an open PR from the intended feature branch to `main`, expected files only, and a clean local worktree. Do not merge.

- [ ] **Step 5: Inventory local-only state**

Classify without deleting:

- keep: local target clone and feature branch until PR disposition;
- keep: installed default media toolchain and offline caches needed by DesktopCompanion production;
- archive: ignored QA evidence and the successful R7 alternate root;
- cleanup candidate: failed R1–R6 diagnostic roots and temporary behavioral-evaluation outputs;
- uncertain/user-owned: any pre-existing source worktree or artifact not created by this publication task.

Report the classification and request exact authorization before any cleanup.

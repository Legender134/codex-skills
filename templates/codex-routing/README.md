# Codex Routing Configuration

Portable user-global routing for separate Windows and WSL Codex installations.
Project code, domain instructions, hooks, skills and state remain project-owned.
This package no longer creates project model, role or concurrency overrides.

## Routing policy

| Role | Model | Effort | Access default |
| --- | --- | --- | --- |
| Primary / unspecified child | gpt-6-sol | high | Inherited |
| scout | gpt-6-luna | low | Read-only |
| explorer | gpt-6-luna | high | Read-only |
| routine_worker | gpt-6-luna | high | Workspace-write |
| worker | gpt-6-luna | max | Workspace-write |
| reviewer | gpt-6-sol | high | Read-only |
| critical_reviewer | gpt-6-astra | high | Read-only |

Two concurrent children per primary session, excluding the primary; this is a
ceiling, not a fixed pipeline or a machine-wide pool. Keep one writer per worktree.
Use only supported GPT-6 routes; never fall back to GPT-5.6. Model availability and
actual effort are verified at runtime, not inferred from a configuration file.
Do not switch provider/login/billing or enable Fast to work around usage limits.

Maintain one reusable global policy per native environment, using its effective
`CODEX_HOME` (default `~/.codex`). Coding projects inherit it without copied routing
configuration or global AGENTS blocks. Necessary project-specific instructions,
including those for non-code work, remain local to that project. Delegate by risk
and complexity rather than file count, and reuse existing in-scope authorization.
Keep these installation, inheritance and migration rules in this documentation;
the always-loaded global AGENTS files contain operational guidance. When changing
configuration, check effective overrides and newly loaded settings; editing a
file alone does not prove an existing session uses it.

`critical_reviewer` investigates a concrete high-risk correctness question. Its
role retains training, CUDA and reconstruction checks, selected only when relevant
to the changed behavior, and also covers other domains through their actual
contracts. A change to gradient accumulation, kernel synchronization or transform
composition can warrant deep review; a training log edit does not automatically
do so. Authorization, concurrent writes or data migrations in other applications
can warrant the same role. The primary chooses review depth from risk and missing
evidence, rather than running `reviewer` and `critical_reviewer` as a pipeline.
Project-specific frames, tolerances and acceptance criteria come from the task and
project contracts, not from defaults invented by the global role.

Scout covers deterministic source lookup and read-only supervision of authorized
training, preprocessing, reconstruction, fusion/alignment, dataset preparation,
evaluation, rendering/export, builds and tests. Give exact job identities, allowed
paths/commands, cadence and completion criteria. It reports timestamped progress,
freshness, metrics, checkpoints, resources, exit status and anomalies. It cannot
start/stop/retry/reconfigure jobs, alter data/code, or grant final acceptance.
An ended turn must hand off pending checks, not claim background monitoring.
Agree on heartbeat and maximum silence intervals. The primary checks for lost
coverage and resumes read-only monitoring when needed, without duplicate routine
polling while scout coverage is healthy.

Before publication, review both the task-baseline diff and everything the target
remote would receive, including earlier unpushed commits and the actual PR/MR diff.

## Prepare the environment

Use Python 3.11+ in the owning environment. From this directory:

```bash
export PYTHONPATH="$PWD/src"
export ROUTING_PYTHON=python3
export WSL_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
"$ROUTING_PYTHON" -m codex_routing check-source --source-root "$PWD"
```

For a Windows target, confirm its home in the Windows PowerShell environment
used to launch Codex:

```powershell
if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
```

If Codex uses a launcher-specific override, use that value instead. Back in WSL,
replace the example path below with the confirmed Windows path and convert it:

```bash
WINDOWS_CODEX_HOME="$(wslpath -u 'C:\Users\<user>\.codex')" && export WINDOWS_CODEX_HOME
```

Use this variable only with WSL Python; native Windows Python needs the original
Windows path. Windows native tooling and login stay separate. See
[SETUP.md](SETUP.md) for skills and environment boundaries.
Windows-native execution rejects WSL homes reached through `\\wsl$` or
`\\wsl.localhost`, including extended UNC paths; manage those homes inside WSL.

## Plan, apply and validate

Keep managed files, their parent directories, and transaction backup evidence
stable and free of other writers throughout installation, rollback, and conflict
preservation. Unrelated Codex session and cache activity may continue. Identity and digest
checks detect changes at checkpoints; they are not an atomic compare-and-swap with
the following replace or unlink, and the tool does not enforce an exclusive lock.
An edit in that final interval can still be overwritten or removed. Defer the
operation if exclusive access cannot be arranged.

```bash
"$ROUTING_PYTHON" -m codex_routing install-global \
  --target wsl --codex-home "$WSL_CODEX_HOME" --source-root "$PWD"
```

**STOP:** Review every planned path and digest before applying.

```bash
"$ROUTING_PYTHON" -m codex_routing install-global \
  --target wsl --codex-home "$WSL_CODEX_HOME" --source-root "$PWD" --apply
"$ROUTING_PYTHON" -m codex_routing validate-global \
  --target wsl --codex-home "$WSL_CODEX_HOME" --source-root "$PWD"
```

For Windows from WSL, use the same preview, apply and validation commands with
`--target windows --codex-home "$WINDOWS_CODEX_HOME"`.
`plan-global` is read-only; `install-global` without `--apply` is also a preview.
The installer validates exact approved source hashes and merges only routing-owned
keys plus its marked AGENTS block. It preserves unrelated MCP, plugins, hooks,
permissions, authentication and provider settings; it prints paths/digests, not
unrelated values. Same-name role files with different bytes are refused.

After a source update, first preserve and review each conflicting role file outside
the active agents directory, using explicit paths, no-overwrite copies/moves and
SHA-256 verification. This includes older managed role versions; the installer
does not assume every same-name file is safe to replace. Never copy a live account
config into this repository.

## Global-only migration

Project installation and validation commands are not provided. Unsupported
commands are rejected by the argument parser with exit code 2 before reading or
modifying project contents, even with `--apply`. Existing project overrides are **not** silently
removed. Inspect each relevant worktree and merge/remove only explicitly identified
routing keys after preserving original bytes. Keep domain AGENTS rules, hooks,
skills, state and all unrelated configuration.

Global configuration is below project and task-specific settings in the
[Codex configuration hierarchy](https://learn.chatgpt.com/docs/config-file/config-reference).
Start a fresh session after installation and verify actual model/effort and the
child cap. No API request or paid model probe is launched by this package.

## Recovery

An apply that changes files prints an exact transaction manifest path under the
selected Codex home's `backups/`. An unchanged apply rechecks the files and creates
no backup or manifest. Preview the relevant transaction before rollback:

```bash
"$ROUTING_PYTHON" -m codex_routing rollback --manifest /exact/manifest.json
```

**STOP:** Review and confirm the exact transaction before applying.

```bash
"$ROUTING_PYTHON" -m codex_routing rollback --manifest /exact/manifest.json --apply
```

Rollback accepts only a `files/<filename>` backup path within its transaction;
Windows separators, drive-qualified paths and alternate data streams are rejected
on every host. It checks installed digests before restoring prior bytes and refuses
edits detected by those checks. Historical project manifests remain supported by the generic
rollback engine, but must be reviewed before use because they can restore obsolete
project overrides. This package does not automatically clean backups or projects.

Replacement is atomic per file, not across the entire configuration directory.
If installation fails, the installer attempts guarded restoration. If restoration
is incomplete, it retains the original `manifest.pending.json` or published
`manifest.json` and backups, records `recovery-required.json` when storage permits,
and reports the transaction directory. Inspect the failure record and each file's
current/prior/installed digests before choosing a repair. The files may be in mixed
states; do not blindly rerun installation or rollback, or delete the evidence.
The failure record itself is not a rollback manifest.

## Resolve a same-name global agent conflict

The installer refuses to overwrite a foreign `scout`, `explorer`, `worker`,
`reviewer`, `routine_worker`, or `critical_reviewer` role. The preservation block
below is an intentional local mutation
that runs before the install preview: it moves one exact regular foreign file
outside `agents/` without overwriting an archive. Set the variables explicitly;
the example selects WSL and `scout`:

```bash
export TARGET_PLATFORM=wsl
export TARGET_CODEX_HOME="$WSL_CODEX_HOME"
export ROLE=scout
(
  set -euo pipefail
  case "$ROLE" in scout|explorer|worker|reviewer|routine_worker|critical_reviewer) ;; *)
    printf '%s\n' 'error: unsupported role' >&2
    exit 2
  ;; esac
  AGENTS_DIR="$TARGET_CODEX_HOME/agents"
  CONFLICT="$AGENTS_DIR/$ROLE.toml"
  ARCHIVE_DIR="$TARGET_CODEX_HOME/routing-conflicts"
  ARCHIVE="$ARCHIVE_DIR/$ROLE.toml.before-routing"

  if [ -L "$TARGET_CODEX_HOME" ] || [ ! -d "$TARGET_CODEX_HOME" ] ||
     [ -L "$AGENTS_DIR" ] || [ ! -d "$AGENTS_DIR" ]; then
    printf '%s\n' 'error: Codex home and agents must be non-linked directories' >&2
    exit 2
  fi
  if [ -L "$CONFLICT" ] || [ ! -f "$CONFLICT" ]; then
    printf '%s\n' 'error: conflict must be a non-linked regular file' >&2
    exit 2
  fi
  if [ -L "$ARCHIVE_DIR" ]; then
    printf '%s\n' 'error: archive directory must not be linked' >&2
    exit 2
  fi
  if [ -e "$ARCHIVE_DIR" ]; then
    if [ ! -d "$ARCHIVE_DIR" ]; then
      printf '%s\n' 'error: archive path is not a directory' >&2
      exit 2
    fi
  elif ! mkdir -- "$ARCHIVE_DIR"; then
    printf '%s\n' 'error: could not create archive directory' >&2
    exit 2
  fi
  if [ -L "$ARCHIVE_DIR" ] || [ ! -d "$ARCHIVE_DIR" ]; then
    printf '%s\n' 'error: archive directory changed during setup' >&2
    exit 2
  fi
  if [ -e "$ARCHIVE" ] || [ -L "$ARCHIVE" ]; then
    printf '%s\n' 'error: archive already exists' >&2
    exit 2
  fi

  FOREIGN_DIGEST="$(sha256sum -- "$CONFLICT" | awk '{print $1}')"
  if ! mv --no-clobber -- "$CONFLICT" "$ARCHIVE"; then
    printf '%s\n' 'error: could not preserve conflict' >&2
    exit 2
  fi
  if [ -e "$CONFLICT" ] || [ -L "$CONFLICT" ]; then
    printf '%s\n' 'error: archive collision preserved the conflict in place' >&2
    exit 2
  fi
  if [ -L "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
    printf '%s\n' 'error: preserved archive is not a regular file' >&2
    exit 2
  fi
  ARCHIVE_DIGEST="$(sha256sum -- "$ARCHIVE" | awk '{print $1}')"
  if [ "$ARCHIVE_DIGEST" != "$FOREIGN_DIGEST" ]; then
    printf '%s\n' 'error: preserved archive digest changed' >&2
    exit 2
  fi
)
```

The foreign bytes are now preserved outside `agents/`. Preview the matching
global install; this command does not apply the plan:

```bash
"$ROUTING_PYTHON" -m codex_routing install-global \
  --target "$TARGET_PLATFORM" --codex-home "$TARGET_CODEX_HOME" \
  --source-root "$PWD"
```

**STOP:** Review every planned path and digest. Run the apply only after
confirming that the preview contains the expected managed role and no foreign
path.

```bash
"$ROUTING_PYTHON" -m codex_routing install-global \
  --target "$TARGET_PLATFORM" --codex-home "$TARGET_CODEX_HOME" \
  --source-root "$PWD" --apply
```

For Windows, set `TARGET_PLATFORM=windows` and
`TARGET_CODEX_HOME="$WINDOWS_CODEX_HOME"`. If the plan reports any path beyond
the expected managed inventory, stop and investigate before applying.

## Source verification

Update pinned hashes in `global_install.py` and `validate.py` only after reviewing
the corresponding source-template change.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m codex_routing check-source --source-root "$PWD"
git diff --check
```

Also run the routing suite with native Windows Python from this directory:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -X utf8 -m unittest discover -s tests -v
```

Tests require Git on PATH. POSIX-only checks and the Bash preservation recipe run
inside WSL; the native Windows installation round-trip runs on Windows. Tests
requiring unavailable Windows symlink privileges report an explicit skip.

Exit codes: 0 success; 1 invalid installed global state; 2 argument/domain errors
(including unsupported commands). Unexpected errors propagate.

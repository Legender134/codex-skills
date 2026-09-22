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

Scout covers deterministic source lookup and read-only supervision of authorized
training, preprocessing, reconstruction, fusion/alignment, dataset preparation,
evaluation, rendering/export, builds and tests. Give exact job identities, allowed
paths/commands, cadence and completion criteria. It reports timestamped progress,
freshness, metrics, checkpoints, resources, exit status and anomalies. It cannot
start/stop/retry/reconfigure jobs, alter data/code, or grant final acceptance.
An ended turn must hand off pending checks, not claim background monitoring.

## Prepare the environment

Use Python 3.11+ in the owning environment. From this directory:

```bash
export PYTHONPATH="$PWD/src"
export ROUTING_PYTHON=python3
export WSL_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
"$ROUTING_PYTHON" -m codex_routing check-source --source-root "$PWD"
```

For a Windows target, resolve its exact Codex home explicitly; do not assume the
WSL home is shared. Windows native tooling and login stay separate. See
[SETUP.md](SETUP.md) for skills and environment boundaries.

## Plan, apply and validate

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

For Windows use `--target windows --codex-home <exact-Windows-Codex-home>`.
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

`install-egs` and `validate-egs` are retired and return exit code 2 without reading
or modifying project contents, even with `--apply`. The old project installer and
templates are no longer shipped. Existing project overrides are **not** silently
removed. Inspect each relevant worktree and merge/remove only explicitly identified
routing keys after preserving original bytes. Keep domain AGENTS rules, hooks,
skills, state and all unrelated configuration.

Global configuration is below project and task-specific settings in the
[Codex configuration hierarchy](https://learn.chatgpt.com/docs/config-file/config-reference).
Start a fresh session after installation and verify actual model/effort and the
child cap. No API request or paid model probe is launched by this package.

## Recovery

Each apply prints an exact transaction manifest path under the selected Codex
home's `backups/`. Preview it, then apply only the intended rollback:

```bash
"$ROUTING_PYTHON" -m codex_routing rollback --manifest /exact/manifest.json
```

**STOP:** Review and confirm the exact transaction before applying.

```bash
"$ROUTING_PYTHON" -m codex_routing rollback --manifest /exact/manifest.json --apply
```

Rollback checks installed digests before restoring prior bytes; subsequent edits
are not overwritten. Historical project manifests remain supported by the generic
rollback engine, but must be reviewed before use because they can restore obsolete
project overrides. This package does not automatically clean backups or projects.

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
  CONFLICT="$TARGET_CODEX_HOME/agents/$ROLE.toml"
  ARCHIVE_DIR="$TARGET_CODEX_HOME/routing-conflicts"
  ARCHIVE="$ARCHIVE_DIR/$ROLE.toml.before-routing"

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

Exit codes: 0 success; 1 invalid installed global state; 2 argument/domain errors
(including retired project commands). Unexpected errors propagate.

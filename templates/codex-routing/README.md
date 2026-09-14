# Codex Routing Configuration

This directory is the maintained source of truth for separate Windows and WSL Codex
routing configurations and local EGS overlays. Repositories that track their
complete routing configuration own those files; the manager validates their
machine-readable routing and preserves their governance text. It is intentionally
dependency-free: run the commands below from WSL with Python 3.11 or newer. Start with [SETUP.md](SETUP.md) for the complete
Windows/WSL setup, skill policy, and worktree guidance.

The management command validates the immutable source templates before any
operation that uses them. It prints only paths, SHA-256 digests, and table
names; it never prints unrelated configuration values.

## Prepare the environment

Run this in WSL. The Windows profile is resolved by PowerShell and converted
to a WSL path, so no user-specific Windows path is committed or copied.

```bash
cd /path/to/codex-skills/templates/codex-routing
export PYTHONPATH="$PWD/src"
export ROUTING_PYTHON="${ROUTING_PYTHON:-python3}"
export WSL_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
WINDOWS_PROFILE="$(powershell.exe -NoProfile -Command \
  '[Environment]::GetFolderPath("UserProfile")' | tr -d '\r')"
export WINDOWS_CODEX_HOME="$(wslpath "$WINDOWS_PROFILE")/.codex"
export EGS_WORKSPACE="${EGS_WORKSPACE:-$HOME/workspace}"
```

Verify the source package first. This reads only `$PWD/templates`; it does not
read either live Codex home or an EGS repository.

```bash
"$ROUTING_PYTHON" -m codex_routing check-source --source-root "$PWD"
```

## Plan without changing files

All mutating commands are dry-runs unless `--apply` is present. Start with the
plans below and review the listed paths and SHA-256 digests.

```bash
"$ROUTING_PYTHON" -m codex_routing plan-global \
  --target windows --codex-home "$WINDOWS_CODEX_HOME" --source-root "$PWD"
"$ROUTING_PYTHON" -m codex_routing install-global \
  --target windows --codex-home "$WINDOWS_CODEX_HOME" --source-root "$PWD"
"$ROUTING_PYTHON" -m codex_routing install-global \
  --target wsl --codex-home "$WSL_CODEX_HOME" --source-root "$PWD"
"$ROUTING_PYTHON" -m codex_routing install-egs \
  --workspace "$EGS_WORKSPACE" --source-root "$PWD"
```

`plan-global` is always a plan. The two `install-global` and `install-egs`
commands above are also plans because they omit `--apply`.

## Apply after review

Run only the targets you intend to change. Windows and WSL are separate
installations; do not point both commands at one directory and do not create a
cross-system symbolic link.

```bash
"$ROUTING_PYTHON" -m codex_routing install-global \
  --target windows --codex-home "$WINDOWS_CODEX_HOME" --source-root "$PWD" \
  --apply
"$ROUTING_PYTHON" -m codex_routing install-global \
  --target wsl --codex-home "$WSL_CODEX_HOME" --source-root "$PWD" \
  --apply
"$ROUTING_PYTHON" -m codex_routing install-egs \
  --workspace "$EGS_WORKSPACE" --source-root "$PWD" --apply
```

Each successful apply prints a manifest path. Keep that exact path: rollback
uses the manifest's installed digests to refuse restoring files that have been
changed since installation.

## Repository-owned EGS configuration

When Git tracks all three targets (`AGENTS.md`, `.codex/config.toml`, and
`.codex/agents/critical_reviewer.toml`), the repository owns its routing.
`validate-egs` checks inherited global model defaults, the project child limit,
enabled agents, and the critical reviewer's model, effort, read-only default,
and nonempty instructions. It does not certify the semantics of governance
prose; reviewers remain responsible for that contract. Project-owned prose
may differ from the base template and does not need to be ignored by Git.

`install-egs` validates those targets and reports `ownership=repository` with
zero updates. Even with `--apply`, it leaves them and their Git ignore rules
untouched. Partially tracked overlays remain protected conflicts. Local
overlays retain exact-template, inventory, ignore, and transactional checks.

## Validate installed state

Validation is read-only. A validation mismatch exits with code `1`; a malformed
or unsafe input exits with code `2` and a single `error:` line.

```bash
"$ROUTING_PYTHON" -m codex_routing validate-global \
  --target windows --codex-home "$WINDOWS_CODEX_HOME" --source-root "$PWD"
"$ROUTING_PYTHON" -m codex_routing validate-global \
  --target wsl --codex-home "$WSL_CODEX_HOME" --source-root "$PWD"
"$ROUTING_PYTHON" -m codex_routing validate-egs \
  --workspace "$EGS_WORKSPACE" --source-root "$PWD"
```

## Revalidate and reinstall idempotently

Run the source check and all three validators after a source update, Codex
upgrade, or machine migration. These commands are read-only:

```bash
"$ROUTING_PYTHON" -m codex_routing check-source --source-root "$PWD"
"$ROUTING_PYTHON" -m codex_routing validate-global \
  --target windows --codex-home "$WINDOWS_CODEX_HOME" --source-root "$PWD"
"$ROUTING_PYTHON" -m codex_routing validate-global \
  --target wsl --codex-home "$WSL_CODEX_HOME" --source-root "$PWD"
"$ROUTING_PYTHON" -m codex_routing validate-egs \
  --workspace "$EGS_WORKSPACE" --source-root "$PWD"
```

An already-current install is idempotent. Preview first; each plan should say
`updates=0`:

```bash
"$ROUTING_PYTHON" -m codex_routing install-global \
  --target windows --codex-home "$WINDOWS_CODEX_HOME" --source-root "$PWD"
"$ROUTING_PYTHON" -m codex_routing install-global \
  --target wsl --codex-home "$WSL_CODEX_HOME" --source-root "$PWD"
"$ROUTING_PYTHON" -m codex_routing install-egs \
  --workspace "$EGS_WORKSPACE" --source-root "$PWD"
```

**STOP:** Review every planned path and digest. Select only the targets you
intend to change; do not run an apply command until its preview is understood.

```bash
"$ROUTING_PYTHON" -m codex_routing install-global \
  --target windows --codex-home "$WINDOWS_CODEX_HOME" --source-root "$PWD" \
  --apply
"$ROUTING_PYTHON" -m codex_routing install-global \
  --target wsl --codex-home "$WSL_CODEX_HOME" --source-root "$PWD" \
  --apply
"$ROUTING_PYTHON" -m codex_routing install-egs \
  --workspace "$EGS_WORKSPACE" --source-root "$PWD" --apply
```

## Find and roll back one manifest

List preserved manifests without reading their contents. Windows, WSL, and
EGS transactions are separate; select the exact manifest printed by the apply
you intend to undo rather than assuming the newest file is the right one.

```bash
find "$WINDOWS_CODEX_HOME/backups" -mindepth 2 -maxdepth 2 \
  -type f -name manifest.json -print | sort
find "$WSL_CODEX_HOME/backups" -mindepth 2 -maxdepth 2 \
  -type f -name manifest.json -print | sort
find "$EGS_WORKSPACE/.codex-routing-backups" -mindepth 2 -maxdepth 2 \
  -type f -name manifest.json -print | sort
```

First preview the rollback; it parses the manifest but changes nothing.

```bash
export ROUTING_MANIFEST='/absolute/path/from-the-install-output/manifest.json'
test -f "$ROUTING_MANIFEST" && test ! -L "$ROUTING_MANIFEST"
"$ROUTING_PYTHON" -m codex_routing rollback \
  --manifest "$ROUTING_MANIFEST"
```

**STOP:** Review and confirm every destination printed by the preview. Apply
only if this is the exact transaction you intend to undo.

```bash
"$ROUTING_PYTHON" -m codex_routing rollback \
  --manifest "$ROUTING_MANIFEST" --apply
```

Use the manifest path printed by the relevant install command. Global manifests
are under `<codex-home>/backups/`; the all-repository EGS install uses
`$EGS_WORKSPACE/.codex-routing-backups/`. Rollback restores prior bytes or
removes only files still matching the manifest's installed digest. It may leave
an empty directory behind rather than deleting an unknown directory.

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

## Remove the local EGS overlays

Use the exact workspace manifest that installed the current overlays. The
rollback restores the prior local Git-exclude bytes as well as prior overlay
bytes; it removes a newly created overlay only while its digest is unchanged.

```bash
find "$EGS_WORKSPACE/.codex-routing-backups" -mindepth 2 -maxdepth 2 \
  -type f -name manifest.json -print | sort
export ROUTING_MANIFEST='/exact/EGS/manifest/path/from-install-output'
test -f "$ROUTING_MANIFEST" && test ! -L "$ROUTING_MANIFEST"
"$ROUTING_PYTHON" -m codex_routing rollback \
  --manifest "$ROUTING_MANIFEST"
```

**STOP:** Review and confirm that the preview names only the three intended EGS
overlays and their local Git-exclude files before removing them.

```bash
"$ROUTING_PYTHON" -m codex_routing rollback \
  --manifest "$ROUTING_MANIFEST" --apply
```

## Update approved source templates

Do not hand-edit installed global files or project overlays. Change the
checked-in file under `templates/`, review its digest, and update the matching
approved digest binding in `src/codex_routing/validate.py` plus
`src/codex_routing/global_install.py` or
`src/codex_routing/project_install.py`. Update the policy tests when routing
semantics change, then run the complete gate:

```bash
find templates -type f -print0 | sort -z | xargs -0 sha256sum
"$ROUTING_PYTHON" -m codex_routing check-source --source-root "$PWD"
PYTHONPATH=src "$ROUTING_PYTHON" -m unittest discover -s tests -v
PYTHONPATH=src "$ROUTING_PYTHON" -m compileall -q src tests
git diff --check
```

Only after review and a passing gate should the normal dry plans and selected
apply commands be run.

## Installed file inventory

For each selected global home (`$WINDOWS_CODEX_HOME` or `$WSL_CODEX_HOME`), the
tool manages only:

- `config.toml` — routing-owned TOML keys are merged; unrelated settings such
  as MCP, plugins, permissions, notifications, and authentication are retained.
- `AGENTS.md` — one `CODEX ROUTING` managed block is added or refreshed.
- `agents/scout.toml`, `agents/explorer.toml`, `agents/worker.toml`, and
  `agents/reviewer.toml`, `agents/routine_worker.toml`, and
  `agents/critical_reviewer.toml` — exact approved role templates.
- `backups/<transaction>/manifest.json` and its private transaction evidence.

For each locally managed EGS repository under `$EGS_WORKSPACE` (`preprocess-cli`, `3dgs-gen`,
and `egs-main`), the tool manages only local files:

- `AGENTS.md`
- `.codex/config.toml`
- `.codex/agents/critical_reviewer.toml`
- `.git/info/exclude` — a managed local ignore block for the three overlay
  paths; the shared `.gitignore` is never changed.

The EGS workspace-level backup transaction is stored at
`$EGS_WORKSPACE/.codex-routing-backups/`. The installer preserves complete repository-owned overlays as described above,
and refuses partial tracking, foreign, linked, or unsafe local targets.

## Project trust and session lifecycle

Use Codex CLI 0.154.0 or newer for this Astra routing policy. Older clients
can parse the configuration while the server rejects the model request. Verify
`codex --version` and an actual ephemeral model request after upgrading;
configuration parsing alone is not a compatibility check.

Installing an EGS overlay does **not** trust a project, grant access, or alter
any shared repository setting. Project trust remains an explicit decision by
the user in Codex for each repository. Review the repository and its local
instructions before trusting it.

After an apply or rollback, close affected Codex sessions and start a new
session before relying on the routing change. Existing sessions can retain the
configuration they started with.

Windows and WSL use Astra Low for the primary and Sol Medium for unspecified
children. Named roles use Luna High for scout, Terra Medium for explorer and
routine_worker, Sol Medium for worker, Astra Low for reviewer, and Astra High
for critical_reviewer. Both global child caps are 1; the EGS overlays retain
cap 2 and inherit global model defaults. Delegate only bounded independent
work; do not use a fixed role pipeline or default to Max/Ultra/Fast.

Existing locally customized EGS governance and role files may intentionally
differ from the source templates. The installer still refuses to overwrite
these files; review and preserve their non-routing changes during migration.

## Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | The requested plan, apply, source check, or validation succeeded. |
| `1` | A `validate-global` or `validate-egs` report is not valid. |
| `2` | A routing/domain error or command-line argument error occurred. |

Unexpected programming failures and control-flow exceptions are not converted
into routing errors; they propagate so that they remain diagnosable.

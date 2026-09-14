import tempfile
import unittest
from pathlib import Path

from codex_routing.errors import RoutingConfigError
from codex_routing.project_install import install_egs_workspace, install_project_overlay, validate_project_overlay
from tests.test_project_install import SOURCE_ROOT, git, init_repo, exclude_path, index_path, read_only_status, working_tree_snapshot


def adopt(repo):
    install_project_overlay(repo, repo.name, SOURCE_ROOT, apply=True)
    (repo / 'AGENTS.md').write_text('# Project governance\nPreserve input data and explicit job ownership.\n')
    path=repo / '.codex/agents/critical_reviewer.toml'
    path.write_text(path.read_text()+'\n# Project-specific review evidence\n')
    git('add','-f','AGENTS.md','.codex/config.toml','.codex/agents/critical_reviewer.toml',cwd=repo)
    git('-c','user.name=test','-c','user.email=test@example.invalid','commit','-m','repository owns routing',cwd=repo)


class RepositoryOwnedRoutingTests(unittest.TestCase):
    def test_repository_governance_is_valid_and_apply_preserves_all_state(self):
        with tempfile.TemporaryDirectory() as raw:
            repo=init_repo(Path(raw),'preprocess-cli');adopt(repo)
            (repo/'AGENTS.md').write_text((repo/'AGENTS.md').read_text()+'Uncommitted project rule.\n')
            before=(working_tree_snapshot(repo),index_path(repo).read_bytes(),exclude_path(repo).read_bytes(),read_only_status(repo))
            report=validate_project_overlay(repo,repo.name,SOURCE_ROOT)
            result=install_project_overlay(repo,repo.name,SOURCE_ROOT,apply=True)
            self.assertTrue(report.valid)
            self.assertEqual(report.ownership,'repository')
            self.assertEqual(result.updates,())
            self.assertEqual(result.ownership,'repository')
            self.assertIsNone(result.manifest_path)
            self.assertEqual(before,(working_tree_snapshot(repo),index_path(repo).read_bytes(),exclude_path(repo).read_bytes(),read_only_status(repo)))

    def test_repository_mode_rejects_stale_models_disabled_agents_and_write_reviewer(self):
        with tempfile.TemporaryDirectory() as raw:
            repo=init_repo(Path(raw),'preprocess-cli');adopt(repo)
            cfg=repo/'.codex/config.toml';reviewer=repo/'.codex/agents/critical_reviewer.toml'
            original=cfg.read_text();reviewer_original=reviewer.read_text()
            for candidate in ['model = "old-model"\n'+original,original.replace('[agents]', '[agents]\nenabled = false'),original.replace('= 2','= 8')]:
                with self.subTest(candidate=candidate):
                    cfg.write_text(candidate)
                    self.assertFalse(validate_project_overlay(repo,repo.name,SOURCE_ROOT).valid)
                    with self.assertRaises(RoutingConfigError):install_project_overlay(repo,repo.name,SOURCE_ROOT,apply=True)
                    self.assertEqual(cfg.read_text(),candidate)
            cfg.write_text(original)
            reviewer.write_text(reviewer_original.replace('sandbox_mode = "read-only"','sandbox_mode = "workspace-write"'))
            self.assertFalse(validate_project_overlay(repo,repo.name,SOURCE_ROOT).valid)

    def test_partial_tracking_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as raw:
            repo=init_repo(Path(raw),'preprocess-cli')
            install_project_overlay(repo,repo.name,SOURCE_ROOT,apply=True)
            git('add','-f','AGENTS.md',cwd=repo)
            before=working_tree_snapshot(repo)
            with self.assertRaisesRegex(RoutingConfigError,'tracked overlay target'):
                install_project_overlay(repo,repo.name,SOURCE_ROOT,apply=True)
            self.assertEqual(before,working_tree_snapshot(repo))

    def test_mixed_workspace_apply_only_writes_local_overlays(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace=Path(raw)
            repos={name:init_repo(workspace,name) for name in ('preprocess-cli','egs-main','3dgs-gen')}
            owned=repos['preprocess-cli'];adopt(owned)
            before=(working_tree_snapshot(owned),exclude_path(owned).read_bytes(),index_path(owned).read_bytes())
            plans=install_egs_workspace(workspace,SOURCE_ROOT,apply=True)
            self.assertEqual(before,(working_tree_snapshot(owned),exclude_path(owned).read_bytes(),index_path(owned).read_bytes()))
            self.assertEqual(next(p for p in plans if p.repo_name=='preprocess-cli').updates,())
            for name,repo in repos.items():self.assertTrue(validate_project_overlay(repo,name,SOURCE_ROOT).valid)

    def test_all_repository_owned_workspace_is_a_noop(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace=Path(raw)
            for name in ('preprocess-cli','egs-main','3dgs-gen'):
                adopt(init_repo(workspace,name))
            before=sorted(str(p) for p in workspace.rglob('*'))
            plans=install_egs_workspace(workspace,SOURCE_ROOT,apply=True)
            self.assertTrue(all(p.ownership=='repository' and not p.updates for p in plans))
            self.assertEqual(before,sorted(str(p) for p in workspace.rglob('*')))
            self.assertFalse((workspace/'.codex-routing-backups').exists())

    def test_symlinked_repository_instructions_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as raw:
            repo=init_repo(Path(raw),'preprocess-cli');adopt(repo)
            instructions=repo/'AGENTS.md';foreign=Path(raw)/'foreign.md';foreign.write_text('External instructions')
            instructions.unlink();instructions.symlink_to(foreign)
            self.assertFalse(validate_project_overlay(repo,repo.name,SOURCE_ROOT).valid)
            self.assertEqual(foreign.read_text(),'External instructions')


if __name__=='__main__':unittest.main()

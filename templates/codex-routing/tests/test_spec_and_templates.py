import tomllib
import os
import tempfile
import unittest
from pathlib import Path

from codex_routing.errors import RoutingConfigError
from codex_routing.spec import AGENT_POLICIES, GLOBAL_POLICIES
from codex_routing.templates import load_template


ROOT = Path(__file__).resolve().parents[1]


class PolicyTemplateTests(unittest.TestCase):
    def test_global_policies_share_routing_with_cap_two(self) -> None:
        self.assertEqual(GLOBAL_POLICIES["windows"].max_threads, 2)
        self.assertEqual(GLOBAL_POLICIES["wsl"].max_threads, 2)
        for policy in GLOBAL_POLICIES.values():
            self.assertEqual(policy.primary_model, "gpt-6.1-sol")
            self.assertEqual(
                policy.primary_effort, "xhigh"
            )
            self.assertEqual(policy.default_subagent_model, "gpt-6.1-sol")
            self.assertEqual(policy.default_subagent_effort, "high")

    def test_no_child_role_defaults_to_max(self) -> None:
        self.assertTrue(all(p.effort != "max" for p in AGENT_POLICIES.values()))

    def test_no_project_routing_templates(self) -> None:
        self.assertFalse(list((ROOT / "templates/projects").glob("*")))

    def test_agent_policies_have_exact_routes(self) -> None:
        self.assertEqual(
            {
                name: (policy.model, policy.effort, policy.sandbox_mode)
                for name, policy in AGENT_POLICIES.items()
            },
            {
                "scout": ("gpt-6-luna", "high", "read-only"),
                "explorer": ("gpt-6.1-sol", "high", "read-only"),
                "worker": ("gpt-6.1-sol", "high", "workspace-write"),
                "reviewer": ("gpt-6.1-sol", "high", "read-only"),
                "routine_worker": ("gpt-6.1-sol", "high", "workspace-write"),
                "critical_reviewer": ("gpt-6-astra", "high", "read-only"),
            },
        )

    def test_global_agents_share_platform_independent_rules(self) -> None:
        marker = "## Working principles"
        windows, wsl = (
            load_template(ROOT, f"global/{platform}-AGENTS.md").decode("utf-8")
            for platform in ("windows", "wsl")
        )
        self.assertEqual(windows.split(marker, 1)[1], wsl.split(marker, 1)[1])

    def test_role_templates_have_required_metadata(self) -> None:
        for name in AGENT_POLICIES:
            template_path = f"agents/{name}.toml"
            payload = tomllib.loads(
                load_template(ROOT, template_path).decode("utf-8")
            )
            self.assertEqual(payload["name"], name)
            self.assertTrue(payload["description"].strip())
            self.assertEqual(payload["model"], AGENT_POLICIES[name].model)
            self.assertEqual(
                payload["model_reasoning_effort"], AGENT_POLICIES[name].effort
            )
            self.assertEqual(payload["sandbox_mode"], AGENT_POLICIES[name].sandbox_mode)
            self.assertTrue(payload["developer_instructions"].strip())

    def test_template_loader_rejects_unsafe_paths_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source_root = Path(raw)
            templates = source_root / "templates"
            templates.mkdir()
            (templates / "safe.txt").write_bytes(b"exact bytes")

            self.assertEqual(load_template(source_root, "safe.txt"), b"exact bytes")
            for path in ("../safe.txt", "/etc/passwd", "C:\\safe.txt"):
                with self.assertRaises(RoutingConfigError):
                    load_template(source_root, path)
            try:
                (templates / "link.txt").symlink_to(templates / "safe.txt")
            except OSError as exc:
                if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Windows symlink privilege is unavailable")
                raise
            with self.assertRaises(RoutingConfigError):
                load_template(source_root, "link.txt")

import tomllib
import tempfile
import unittest
from pathlib import Path

from codex_routing.errors import RoutingConfigError
from codex_routing.spec import AGENT_POLICIES, GLOBAL_POLICIES, REPO_POLICIES
from codex_routing.templates import load_template


ROOT = Path(__file__).resolve().parents[1]


class PolicyTemplateTests(unittest.TestCase):
    def test_global_policies_share_routing_with_cap_one(self) -> None:
        self.assertEqual(GLOBAL_POLICIES["windows"].max_threads, 1)
        self.assertEqual(GLOBAL_POLICIES["wsl"].max_threads, 1)
        for policy in GLOBAL_POLICIES.values():
            self.assertEqual(policy.primary_model, "gpt-6-astra")
            self.assertEqual(policy.primary_effort, "low")
            self.assertEqual(policy.default_subagent_model, "gpt-5.6-sol")
            self.assertEqual(policy.default_subagent_effort, "medium")

    def test_default_roles_do_not_use_max(self) -> None:
        for name in ("scout", "explorer", "worker", "reviewer"):
            self.assertNotEqual(AGENT_POLICIES[name].effort, "max")

    def test_project_config_inherits_global_model_routing(self) -> None:
        payload = tomllib.loads(
            load_template(ROOT, "projects/common-config.toml").decode("utf-8")
        )
        self.assertNotIn("model", payload)
        self.assertNotIn("model_reasoning_effort", payload)
        self.assertEqual(payload["agents"]["max_concurrent_threads_per_session"], 2)
        self.assertNotIn("default_subagent_model", payload["agents"])
        self.assertNotIn("default_subagent_reasoning_effort", payload["agents"])

    def test_repo_policy_inventory_is_exact(self) -> None:
        self.assertEqual(
            tuple(REPO_POLICIES), ("preprocess-cli", "3dgs-gen", "egs-main")
        )

    def test_agent_policies_have_exact_routes(self) -> None:
        self.assertEqual(
            {
                name: (policy.model, policy.effort, policy.sandbox_mode)
                for name, policy in AGENT_POLICIES.items()
            },
            {
                "scout": ("gpt-5.6-luna", "high", "read-only"),
                "explorer": ("gpt-5.6-terra", "medium", "read-only"),
                "worker": ("gpt-5.6-sol", "medium", "workspace-write"),
                "reviewer": ("gpt-6-astra", "low", "read-only"),
                "routine_worker": ("gpt-5.6-terra", "medium", "workspace-write"),
                "critical_reviewer": ("gpt-6-astra", "high", "read-only"),
            },
        )

    def test_global_agents_templates_require_local_closeout(self) -> None:
        for platform in ("windows", "wsl"):
            instructions = load_template(
                ROOT, f"global/{platform}-AGENTS.md"
            ).decode("utf-8")
            self.assertIn(
                "## Development exploration and submission contract", instructions
            )
            self.assertIn("## Local closeout", instructions)
            self.assertIn("keep, archive, or cleanup candidate", instructions)
            self.assertIn("Report the classification inventory", instructions)
            self.assertIn("explicit authorization", instructions)

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
            (templates / "link.txt").symlink_to(templates / "safe.txt")

            self.assertEqual(load_template(source_root, "safe.txt"), b"exact bytes")
            for path in ("../safe.txt", "/etc/passwd", "C:\\safe.txt"):
                with self.assertRaises(RoutingConfigError):
                    load_template(source_root, path)
            with self.assertRaises(RoutingConfigError):
                load_template(source_root, "link.txt")

import tomllib
import unittest

from codex_routing.errors import RoutingConfigError
from codex_routing.spec import GLOBAL_POLICIES
from codex_routing.toml_merge import managed_config_values, merge_global_config


EXISTING = '''
# personal comment
model = "gpt-5.6-sol"
model_reasoning_effort = "xhigh"

[features]
multi_agent = true

[mcp_servers.internal]
command = "internal-mcp"

[agents]
interrupt_message = false
custom_future_key = "preserve-me"
'''.lstrip()


class TomlMergeTests(unittest.TestCase):
    def test_managed_values_come_from_the_policy(self) -> None:
        self.assertEqual(
            managed_config_values(GLOBAL_POLICIES["windows"]),
            {
                "model": "gpt-6-astra",
                "model_reasoning_effort": "low",
                "agents": {
                    "enabled": True,
                    "max_concurrent_threads_per_session": 1,
                    "default_subagent_model": "gpt-5.6-sol",
                    "default_subagent_reasoning_effort": "medium",
                    "interrupt_message": True,
                },
            },
        )

    def test_merge_changes_only_owned_values(self) -> None:
        merged = merge_global_config(EXISTING, GLOBAL_POLICIES["windows"])
        payload = tomllib.loads(merged)

        self.assertEqual(payload["model"], "gpt-6-astra")
        self.assertEqual(payload["model_reasoning_effort"], "low")
        self.assertTrue(payload["agents"]["enabled"])
        self.assertEqual(payload["agents"]["max_concurrent_threads_per_session"], 1)
        self.assertEqual(
            payload["agents"]["default_subagent_model"], "gpt-5.6-sol"
        )
        self.assertEqual(
            payload["agents"]["default_subagent_reasoning_effort"], "medium"
        )
        self.assertTrue(payload["agents"]["interrupt_message"])
        self.assertEqual(payload["agents"]["custom_future_key"], "preserve-me")
        self.assertEqual(payload["mcp_servers"]["internal"]["command"], "internal-mcp")
        self.assertIn("# personal comment", merged)

    def test_merge_is_idempotent(self) -> None:
        first = merge_global_config(EXISTING, GLOBAL_POLICIES["wsl"])
        second = merge_global_config(first, GLOBAL_POLICIES["wsl"])

        self.assertEqual(second, first)

    def test_merge_adds_all_owned_values_to_an_empty_file(self) -> None:
        merged = merge_global_config("", GLOBAL_POLICIES["wsl"])

        self.assertEqual(
            tomllib.loads(merged),
            {
                "model": "gpt-6-astra",
                "model_reasoning_effort": "low",
                "agents": {
                    "enabled": True,
                    "max_concurrent_threads_per_session": 1,
                    "default_subagent_model": "gpt-5.6-sol",
                    "default_subagent_reasoning_effort": "medium",
                    "interrupt_message": True,
                },
            },
        )
        self.assertTrue(merged.endswith("\n"))

    def test_merge_inserts_top_level_values_before_first_table_and_agents_at_end(
        self,
    ) -> None:
        existing = '# user setting\ncustom = "keep"\n\n[features]\nflag = true\n'

        merged = merge_global_config(existing, GLOBAL_POLICIES["windows"])

        self.assertLess(merged.index('model = "gpt-6-astra"'), merged.index("[features]"))
        self.assertLess(
            merged.index('model_reasoning_effort = "low"'), merged.index("[features]")
        )
        self.assertTrue(merged.rstrip().endswith("interrupt_message = true"))
        self.assertEqual(tomllib.loads(merged)["custom"], "keep")
        self.assertTrue(tomllib.loads(merged)["features"]["flag"])

    def test_merge_preserves_crlf_newlines(self) -> None:
        existing = (
            'model = "old" # keep\r\n'
            'model_reasoning_effort = "low"\r\n'
            '\r\n'
            '[agents]\r\n'
            'interrupt_message = false # keep\r\n'
            'custom_future_key = "preserve-me"\r\n'
        )

        merged = merge_global_config(existing, GLOBAL_POLICIES["wsl"])

        self.assertNotIn("\n", merged.replace("\r\n", ""))
        self.assertIn('model = "gpt-6-astra" # keep\r\n', merged)
        self.assertIn('interrupt_message = true # keep\r\n', merged)
        self.assertIn('custom_future_key = "preserve-me"\r\n', merged)

    def test_merge_preserves_comments_beside_owned_values(self) -> None:
        existing = (
            'model = "old" # primary comment\n'
            'model_reasoning_effort = "low" # effort comment\n'
            '\n'
            '[agents]\n'
            'max_concurrent_threads_per_session = 9 # cap comment\n'
        )

        merged = merge_global_config(existing, GLOBAL_POLICIES["windows"])

        self.assertIn('model = "gpt-6-astra" # primary comment\n', merged)
        self.assertIn('model_reasoning_effort = "low" # effort comment\n', merged)
        self.assertIn('max_concurrent_threads_per_session = 1 # cap comment\n', merged)

    def test_merge_preserves_unrelated_nested_agents_table(self) -> None:
        existing = (
            '[agents]\n'
            'custom_future_key = "preserve-me"\n'
            '\n'
            '[agents.custom]\n'
            'enabled = false\n'
            'notes = "do-not-touch"\n'
        )

        merged = merge_global_config(existing, GLOBAL_POLICIES["windows"])
        payload = tomllib.loads(merged)

        self.assertTrue(payload["agents"]["enabled"])
        self.assertEqual(payload["agents"]["custom_future_key"], "preserve-me")
        self.assertEqual(
            payload["agents"]["custom"],
            {"enabled": False, "notes": "do-not-touch"},
        )
        self.assertIn('[agents.custom]\nenabled = false\nnotes = "do-not-touch"\n', merged)

    def test_duplicate_owned_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(RoutingConfigError, "managed key"):
            merge_global_config('model = "a"\nmodel = "b"\n', GLOBAL_POLICIES["wsl"])

    def test_invalid_toml_is_rejected(self) -> None:
        with self.assertRaisesRegex(RoutingConfigError, "invalid TOML"):
            merge_global_config('model = "unterminated\n', GLOBAL_POLICIES["wsl"])

    def test_quoted_managed_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(RoutingConfigError, "managed key"):
            merge_global_config('\"model\" = "old"\n', GLOBAL_POLICIES["wsl"])

    def test_multiline_managed_value_is_rejected(self) -> None:
        with self.assertRaisesRegex(RoutingConfigError, "managed key"):
            merge_global_config(
                'model = """old\nvalue"""\n', GLOBAL_POLICIES["wsl"]
            )

    def test_unsupported_owned_assignment_forms_are_rejected(self) -> None:
        cases = {
            "dotted": 'agents.interrupt_message = false\n',
            "array": 'model = ["old"]\n',
            "inline table": 'model = { value = "old" }\n',
            "agent duplicate": (
                '[agents]\ninterrupt_message = false\ninterrupt_message = true\n'
            ),
        }

        for name, existing in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(RoutingConfigError, "managed key"):
                    merge_global_config(existing, GLOBAL_POLICIES["wsl"])


if __name__ == "__main__":
    unittest.main()

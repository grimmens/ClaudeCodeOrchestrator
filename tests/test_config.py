import json
import os
import tempfile
import unittest

from src.orchestrator.config import Config, DEFAULTS, load_config, save_config


class TestConfig(unittest.TestCase):
    def test_default_values(self):
        cfg = Config()
        self.assertEqual(cfg.max_budget_usd, 5.0)
        self.assertEqual(cfg.max_turns, 50)
        self.assertEqual(cfg.build_command, "dotnet build")
        self.assertTrue(cfg.include_context)
        self.assertTrue(cfg.auto_fix_build)
        self.assertEqual(cfg.db_path, "orchestrator.db")

    def test_defaults_dict_matches_dataclass(self):
        cfg = Config()
        for key, value in DEFAULTS.items():
            self.assertEqual(getattr(cfg, key), value)

    def test_load_config_missing_file(self):
        cfg = load_config("/nonexistent/path/config.json")
        self.assertEqual(cfg.max_budget_usd, 5.0)

    def test_load_config_partial_override(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"max_budget_usd": 10.0, "max_turns": 100}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg.max_budget_usd, 10.0)
            self.assertEqual(cfg.max_turns, 100)
            # Defaults preserved for unspecified keys
            self.assertEqual(cfg.build_command, "dotnet build")
            self.assertTrue(cfg.include_context)
        finally:
            os.unlink(path)

    def test_load_config_ignores_unknown_keys(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"max_budget_usd": 3.0, "unknown_key": "ignored"}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg.max_budget_usd, 3.0)
            self.assertFalse(hasattr(cfg, "unknown_key"))
        finally:
            os.unlink(path)

    def test_save_and_reload(self):
        cfg = Config(max_budget_usd=20.0, max_turns=10, build_command="make")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            save_config(cfg, path)
            loaded = load_config(path)
            self.assertEqual(loaded.max_budget_usd, 20.0)
            self.assertEqual(loaded.max_turns, 10)
            self.assertEqual(loaded.build_command, "make")
        finally:
            os.unlink(path)

    def test_save_writes_valid_json(self):
        cfg = Config()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            save_config(cfg, path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, dict)
            self.assertIn("max_budget_usd", data)
            self.assertIn("db_path", data)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()

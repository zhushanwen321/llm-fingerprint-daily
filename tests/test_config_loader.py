"""配置加载器测试"""

import pytest

from src.config.loader import load_config
from src.config.schema import AppConfig


class TestLoadConfigResolvesEnvVars:
    """YAML 中 ${ENV_VAR} 格式的环境变量解析"""

    def test_resolves_single_env_var(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TEST_API_KEY", "sk-123")
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            """
providers:
  test:
    base_url: "https://api.test.com"
    api_key: "${TEST_API_KEY}"
    concurrency: 2
models: []
evaluation:
  schedule: [0]
  probe_types: []
  max_llm_concurrent: 2
  targets: []
report:
  output_dir: "./reports"
"""
        )
        config = load_config(str(config_yaml))
        assert config.providers["test"].api_key == "sk-123"

    def test_missing_env_var_raises_error(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            """
providers:
  test:
    base_url: "https://api.test.com"
    api_key: "${NONEXISTENT_VAR_xyz}"
    concurrency: 1
models: []
evaluation:
  schedule: [0]
  targets: []
report: {}
"""
        )
        with pytest.raises(ValueError, match="NONEXISTENT_VAR_xyz"):
            load_config(str(config_yaml))

    def test_no_env_vars_passes_through(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            """
providers:
  test:
    base_url: "https://api.test.com"
    api_key: "plain-key"
    concurrency: 1
models: []
evaluation:
  schedule: [0]
  targets: []
report: {}
"""
        )
        config = load_config(str(config_yaml))
        assert config.providers["test"].api_key == "plain-key"

    def test_returns_app_config_instance(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            """
providers:
  test:
    base_url: "https://api.test.com"
    api_key: "key"
models: []
evaluation:
  schedule: [0]
  targets: []
report: {}
"""
        )
        config = load_config(str(config_yaml))
        assert isinstance(config, AppConfig)

    def test_file_not_found_raises_error(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")

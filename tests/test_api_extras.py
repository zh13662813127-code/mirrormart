"""场景/人设 API 和新人设加载测试。"""

from __future__ import annotations

import io
import random
from pathlib import Path

import pytest
import yaml

from mirrormart.agent import Agent
from mirrormart.platforms.xiaohongshu import XiaohongshuEnvironment
from mirrormart.platforms.taobao import TaobaoEnvironment


# ──────────────── 新人设加载测试 ────────────────

PROFILES_DIR = Path("profiles")
NEW_PROFILES = ["student", "mom", "male_casual"]


class TestNewProfiles:
    """测试新增人设文件的结构完整性。"""

    @pytest.mark.parametrize("profile_id", NEW_PROFILES)
    def test_profile_file_exists(self, profile_id: str) -> None:
        path = PROFILES_DIR / f"{profile_id}.yml"
        assert path.exists(), f"人设文件 {path} 不存在"

    @pytest.mark.parametrize("profile_id", NEW_PROFILES)
    def test_profile_has_required_fields(self, profile_id: str) -> None:
        path = PROFILES_DIR / f"{profile_id}.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["id"] == profile_id
        assert "name" in data
        assert "description" in data
        assert "consumer_traits" in data
        assert "decision_style" in data["consumer_traits"]
        assert "price_sensitivity" in data["consumer_traits"]
        assert "interest_tags" in data["consumer_traits"]
        assert "platform_behavior" in data
        assert "decision_triggers" in data

    @pytest.mark.parametrize("profile_id", NEW_PROFILES)
    def test_profile_has_four_platforms(self, profile_id: str) -> None:
        path = PROFILES_DIR / f"{profile_id}.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        pb = data["platform_behavior"]
        for platform in ["xiaohongshu", "taobao", "douyin", "weibo"]:
            assert platform in pb, f"人设 {profile_id} 缺少 {platform} 平台行为"

    @pytest.mark.parametrize("profile_id", NEW_PROFILES)
    def test_agent_creation_from_profile(self, profile_id: str) -> None:
        """测试从新人设创建 Agent 不报错。"""
        path = PROFILES_DIR / f"{profile_id}.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        agent = Agent(
            persona=data,
            agent_id=f"{profile_id}_01",
            llm_model="test-model",
            rng=random.Random(42),
        )
        assert agent.id == f"{profile_id}_01"
        assert agent.persona["name"] == data["name"]


# ──────────────── 新场景加载测试 ────────────────

SCENARIOS_DIR = Path("scenarios")
NEW_SCENARIOS = ["kol_seeding", "discount_promo"]


class TestNewScenarios:
    """测试新场景文件的结构完整性。"""

    @pytest.mark.parametrize("scenario_id", NEW_SCENARIOS)
    def test_scenario_file_exists(self, scenario_id: str) -> None:
        path = SCENARIOS_DIR / f"{scenario_id}.yml"
        assert path.exists(), f"场景文件 {path} 不存在"

    @pytest.mark.parametrize("scenario_id", NEW_SCENARIOS)
    def test_scenario_has_required_sections(self, scenario_id: str) -> None:
        path = SCENARIOS_DIR / f"{scenario_id}.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["id"] == scenario_id
        assert "product" in data
        assert "platforms" in data
        assert "agents" in data
        assert "simulation" in data

    @pytest.mark.parametrize("scenario_id", NEW_SCENARIOS)
    def test_scenario_has_four_platforms(self, scenario_id: str) -> None:
        path = SCENARIOS_DIR / f"{scenario_id}.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        platform_types = {p["type"] for p in data["platforms"]}
        for pt in ["xiaohongshu", "taobao", "douyin", "weibo"]:
            assert pt in platform_types, f"场景 {scenario_id} 缺少平台 {pt}"

    @pytest.mark.parametrize("scenario_id", NEW_SCENARIOS)
    def test_scenario_agents_reference_valid_profiles(self, scenario_id: str) -> None:
        path = SCENARIOS_DIR / f"{scenario_id}.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        available_profiles = {
            p.stem for p in PROFILES_DIR.glob("*.yml")
        }
        for agent_cfg in data["agents"]["profiles"]:
            assert agent_cfg["type"] in available_profiles, \
                f"场景 {scenario_id} 引用了不存在的人设: {agent_cfg['type']}"


# ──────────────── API 端点测试 ────────────────

class TestAPIEndpoints:
    """测试场景和人设 API 端点。"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from mirrormart.api.app import app
        return TestClient(app)

    def test_list_scenarios(self, client) -> None:
        resp = client.get("/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 4  # 至少 4 个场景
        names = {s["id"] for s in data}
        assert "kol_seeding" in names
        assert "discount_promo" in names

    def test_list_profiles(self, client) -> None:
        resp = client.get("/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 9  # 6 原有 + 3 新增
        ids = {p["id"] for p in data}
        assert "student" in ids
        assert "mom" in ids
        assert "male_casual" in ids

    def test_upload_scenario_valid(self, client, tmp_path) -> None:
        scenario = {
            "id": "test_upload",
            "name": "测试上传场景",
            "platforms": [{"type": "xiaohongshu", "initial_content": []}],
            "agents": {"profiles": [{"type": "lurker", "count": 1}]},
            "simulation": {"num_steps": 3, "num_branches": 2},
        }
        content = yaml.dump(scenario, allow_unicode=True)
        resp = client.post(
            "/scenarios/upload",
            files={"file": ("test_upload.yml", content.encode(), "application/x-yaml")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "test_upload"
        # 清理
        uploaded = Path("scenarios/test_upload.yml")
        if uploaded.exists():
            uploaded.unlink()

    def test_upload_scenario_invalid_extension(self, client) -> None:
        resp = client.post(
            "/scenarios/upload",
            files={"file": ("bad.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400

    def test_upload_scenario_invalid_yaml(self, client) -> None:
        resp = client.post(
            "/scenarios/upload",
            files={"file": ("bad.yml", b": invalid: yaml: [", "application/x-yaml")},
        )
        assert resp.status_code == 400

    def test_upload_scenario_missing_fields(self, client) -> None:
        content = yaml.dump({"id": "incomplete", "name": "test"})
        resp = client.post(
            "/scenarios/upload",
            files={"file": ("incomplete.yml", content.encode(), "application/x-yaml")},
        )
        assert resp.status_code == 400

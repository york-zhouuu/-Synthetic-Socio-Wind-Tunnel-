"""Agent 的静态身份和性格定义。模拟期间不变。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentProfile(BaseModel):
    """Agent 的静态身份和性格定义。模拟期间不变。"""

    # === 身份 ===
    agent_id: str
    name: str
    age: int
    occupation: str
    household: str  # "single" / "couple" / "family_with_kids"

    # === 居住 ===
    home_location: str  # 家的 location_id (初始值，可被 Life Pattern 更新)

    # === 性格特征 ===
    # 具体维度和数据来源由外部调研文档定义
    personality_traits: dict[str, float] = Field(default_factory=dict)
    personality_description: str = ""

    # === 社交偏好 ===
    preferred_social_size: int = 2  # 1=独处, 5=派对
    interests: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=lambda: ["mandarin"])

    # === 日常习惯 ===
    wake_time: str = "7:00"
    sleep_time: str = "23:00"

    # === LLM 配置 ===
    is_protagonist: bool = False
    base_model: str = "claude-haiku-4-5-20251001"

    model_config = {"frozen": True}

    # --- 便捷访问 personality_traits ---

    def trait(self, name: str, default: float = 0.5) -> float:
        """获取某个性格维度的值，不存在则返回 default。"""
        return self.personality_traits.get(name, default)

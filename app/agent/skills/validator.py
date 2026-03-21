"""
Skill 验证器模块
"""

from typing import Dict, Any, Optional, Set
from app.agent.skills.base import BaseSkill


class SkillValidator:
    """
    Skill 参数验证器

    验证 Skill 参数是否符合定义规范。
    """

    def __init__(self):
        self._param_validators: Dict[str, Any] = {}

    def register_validator(self, param_type: str, validator: Any) -> None:
        """
        注册自定义参数验证器

        Args:
            param_type: 参数类型 (如 "url", "email", "file_path")
            validator: 验证函数
        """
        self._param_validators[param_type] = validator

    def validate(self, skill: BaseSkill, params: Dict[str, Any]):
        """
        验证参数

        Args:
            skill: Skill 实例
            params: 待验证的参数

        Returns:
            tuple[bool, Optional[str]]: (is_valid, error_message)
        """
        required_params = [p for p in skill.parameters if p.get("required", False)]

        for param in required_params:
            param_name = param.get("name")
            if param_name not in params:
                return False, f"缺少必需参数: {param_name}"

        for param_name, param_value in params.items():
            param_def = self._get_param_def(skill, param_name)
            if param_def:
                valid, error = self._validate_param(param_name, param_value, param_def)
                if not valid:
                    return False, error

        return True, None

    def _get_param_def(self, skill: BaseSkill, param_name: str):
        """获取参数定义"""
        for param in skill.parameters:
            if param.get("name") == param_name:
                return param
        return None

    def _validate_param(
        self,
        name: str,
        value: Any,
        param_def: Dict[str, Any],
    ):
        """验证单个参数"""
        expected_type = param_def.get("type", "string")

        if expected_type == "string":
            if not isinstance(value, str):
                return False, f"参数 {name} 应为字符串"
            if "min_length" in param_def:
                if len(value) < param_def["min_length"]:
                    return False, f"参数 {name} 长度不足"
            if "max_length" in param_def:
                if len(value) > param_def["max_length"]:
                    return False, f"参数 {name} 长度超出限制"

        elif expected_type == "number":
            if not isinstance(value, (int, float)):
                return False, f"参数 {name} 应为数字"

            if "min" in param_def and value < param_def["min"]:
                return False, f"参数 {name} 低于最小值 {param_def['min']}"
            if "max" in param_def and value > param_def["max"]:
                return False, f"参数 {name} 超出最大值 {param_def['max']}"

        elif expected_type == "boolean":
            if not isinstance(value, bool):
                return False, f"参数 {name} 应为布尔值"

        elif expected_type == "object":
            if not isinstance(value, dict):
                return False, f"参数 {name} 应为对象"

        elif expected_type == "array":
            if not isinstance(value, list):
                return False, f"参数 {name} 应为数组"

        custom_validator = self._param_validators.get(expected_type)
        if custom_validator:
            valid, error = custom_validator(value, param_def)
            if not valid:
                return False, f"参数 {name} {error}"

        return True, None

    def validate_skill_name(self, name: str, allowed_skills: Set[str]) -> bool:
        """验证 Skill 名称是否在允许列表中"""
        return name in allowed_skills

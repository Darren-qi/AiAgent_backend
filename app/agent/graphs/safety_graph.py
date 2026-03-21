"""安全子图"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import re


@dataclass
class SafetyCheckResult:
    """安全检查结果"""
    passed: bool
    violations: List[str]
    warnings: List[str]


class SafetyGraph:
    """
    安全子图

    在任务执行前进行全面的安全检查，
    包括输入验证、权限检查、风险评估等。
    """

    def __init__(self):
        self.dangerous_patterns = [
            r"rm\s+-rf\s+/",
            r"shutdown\s+-h\s+now",
            r"reboot",
            r"mkfs",
            r"drop\s+database",
            r"delete\s+from\s+\w+\s*;",
            r"<script[^>]*>.*?</script>",
            r"javascript:",
        ]
        self.max_file_size = 10 * 1024 * 1024
        self.max_execution_time = 300

    async def check(
        self,
        task: str,
        params: Optional[Dict[str, Any]] = None,
        planned_skills: Optional[List[str]] = None
    ) -> SafetyCheckResult:
        """
        执行全面安全检查

        Args:
            task: 用户任务描述
            params: 执行参数
            planned_skills: 计划执行的 Skill 列表

        Returns:
            安全检查结果
        """
        violations = []
        warnings = []

        input_result = self._check_input(task)
        violations.extend(input_result.get("violations", []))
        warnings.extend(input_result.get("warnings", []))

        if params:
            params_result = self._check_params(params)
            violations.extend(params_result.get("violations", []))
            warnings.extend(params_result.get("warnings", []))

        if planned_skills:
            skills_result = self._check_skills(planned_skills)
            violations.extend(skills_result.get("violations", []))
            warnings.extend(skills_result.get("warnings", []))

        return SafetyCheckResult(
            passed=len(violations) == 0,
            violations=violations,
            warnings=warnings,
        )

    def _check_input(self, task: str) -> Dict[str, Any]:
        """检查输入内容"""
        violations = []
        warnings = []

        if len(task) > 100000:
            violations.append("输入内容过长")

        for pattern in self.dangerous_patterns:
            if re.search(pattern, task, re.IGNORECASE):
                violations.append(f"检测到危险模式: {pattern}")

        injection_patterns = [
            "ignore previous instructions",
            "disregard all previous",
            "new system prompt:",
            "你现在是",
            "你是一个",
            "forget all instructions",
        ]
        for pattern in injection_patterns:
            if pattern.lower() in task.lower():
                warnings.append(f"检测到可能的 Prompt 注入: {pattern}")

        return {"violations": violations, "warnings": warnings}

    def _check_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """检查执行参数"""
        violations = []
        warnings = []

        for key, value in params.items():
            if key in ["password", "secret", "token"] and isinstance(value, str):
                if len(value) > 0:
                    warnings.append(f"参数 {key} 可能包含敏感信息")

            if key == "file_size" and isinstance(value, (int, float)):
                if value > self.max_file_size:
                    violations.append(f"文件大小超过限制: {value} > {self.max_file_size}")

            if key == "timeout" and isinstance(value, (int, float)):
                if value > self.max_execution_time:
                    violations.append(f"超时时间超过限制: {value} > {self.max_execution_time}")

        return {"violations": violations, "warnings": warnings}

    def _check_skills(self, skills: List[str]) -> Dict[str, Any]:
        """检查 Skill 调用"""
        violations = []
        warnings = []

        forbidden_skills = {"shell_exec", "system_exec", "eval", "exec"}
        high_risk_skills = {"send_email", "delete_file", "drop_table"}

        for skill in skills:
            if skill in forbidden_skills:
                violations.append(f"禁止使用 Skill: {skill}")
            if skill in high_risk_skills:
                warnings.append(f"高风险 Skill: {skill}，建议人工确认")

        return {"violations": violations, "warnings": warnings}

    def get_risk_level(self, result: SafetyCheckResult) -> str:
        """评估风险等级"""
        if not result.passed:
            return "BLOCKED"
        if len(result.warnings) >= 3:
            return "HIGH"
        if len(result.warnings) >= 1:
            return "MEDIUM"
        return "LOW"

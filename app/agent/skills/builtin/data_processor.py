"""内置 Skill - 数据处理"""

import json
import logging
from typing import Dict, Any

from app.agent.skills.base import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


class DataProcessorSkill(BaseSkill):
    """数据处理 Skill"""

    def __init__(self):
        super().__init__()
        self.name = "data_processor"
        self.description = "数据处理、转换、统计分析"
        self.parameters = [
            {"name": "operation", "type": "string", "required": True, "description": "操作类型: parse_json/filter/sort/aggregate/transform"},
            {"name": "input_data", "type": "string", "required": True, "description": "输入数据"},
            {"name": "options", "type": "object", "required": False, "description": "操作选项"},
        ]

    async def execute(self, **kwargs) -> SkillResult:
        operation = kwargs.get("operation", "transform")
        input_data = kwargs.get("input_data", "")
        options = kwargs.get("options", {})

        if not input_data:
            return SkillResult(success=False, error="缺少 input_data 参数")

        try:
            # 解析输入数据
            data = self._parse_data(input_data)

            # 根据操作类型处理
            if operation == "parse_json":
                result = data
            elif operation == "filter":
                result = self._filter_data(data, options)
            elif operation == "sort":
                result = self._sort_data(data, options)
            elif operation == "aggregate":
                result = self._aggregate_data(data, options)
            elif operation == "transform":
                result = self._transform_data(data, options)
            else:
                result = data

            return SkillResult(
                success=True,
                data={"result": result, "operation": operation},
                metadata={"items_processed": len(data) if isinstance(data, (list, dict)) else 0}
            )
        except Exception as e:
            logger.error(f"[DataProcessor] 处理数据失败: {e}")
            return SkillResult(success=False, error=str(e))

    def _parse_data(self, input_data: Any) -> Any:
        """解析输入数据"""
        if isinstance(input_data, (list, dict)):
            return input_data
        try:
            return json.loads(input_data)
        except (json.JSONDecodeError, TypeError):
            return {"raw": str(input_data)}

    def _filter_data(self, data: Any, options: Dict) -> Any:
        """过滤数据"""
        if not isinstance(data, list):
            return data

        field = options.get("field")
        value = options.get("value")
        operator = options.get("operator", "eq")

        if not field:
            return data

        filtered = []
        for item in data:
            if isinstance(item, dict) and field in item:
                item_value = item[field]
                if operator == "eq" and item_value == value:
                    filtered.append(item)
                elif operator == "contains" and value in str(item_value):
                    filtered.append(item)
                elif operator == "gt" and item_value > value:
                    filtered.append(item)
                elif operator == "lt" and item_value < value:
                    filtered.append(item)
            else:
                if operator == "contains" and value in str(item):
                    filtered.append(item)

        return filtered

    def _sort_data(self, data: Any, options: Dict) -> Any:
        """排序数据"""
        if not isinstance(data, list):
            return data

        field = options.get("field", None)
        reverse = options.get("reverse", False)

        if field:
            return sorted(data, key=lambda x: x.get(field, "") if isinstance(x, dict) else x, reverse=reverse)
        return sorted(data, key=str, reverse=reverse)

    def _aggregate_data(self, data: Any, options: Dict) -> Any:
        """聚合数据"""
        if not isinstance(data, list):
            return data

        field = options.get("field")
        agg_type = options.get("type", "count")

        if not field:
            return {"count": len(data)}

        values = [item.get(field) for item in data if isinstance(item, dict) and field in item]

        if agg_type == "count":
            return {"count": len(values)}
        elif agg_type == "sum":
            return {"sum": sum(v for v in values if isinstance(v, (int, float)))}
        elif agg_type == "avg":
            numeric = [v for v in values if isinstance(v, (int, float))]
            return {"avg": sum(numeric) / len(numeric) if numeric else 0}
        elif agg_type == "min":
            numeric = [v for v in values if isinstance(v, (int, float))]
            return {"min": min(numeric) if numeric else None}
        elif agg_type == "max":
            numeric = [v for v in values if isinstance(v, (int, float))]
            return {"max": max(numeric) if numeric else None}

        return {"count": len(values)}

    def _transform_data(self, data: Any, options: Dict) -> Any:
        """转换数据"""
        transform_type = options.get("type", "to_list")

        if transform_type == "to_dict":
            if isinstance(data, list):
                key_field = options.get("key_field", "id")
                return {item.get(key_field, i): item for i, item in enumerate(data)}
        elif transform_type == "to_list":
            if isinstance(data, dict):
                return [{"key": k, "value": v} for k, v in data.items()]

        return data

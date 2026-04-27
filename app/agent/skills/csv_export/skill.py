"""CSV Export Skill - CSV导出技能"""

import csv
import io
import logging
from typing import Dict, Any, List, Optional

from app.agent.skills.core.base_skill import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


class CSVExportSkill(BaseSkill):
    """CSV导出 Skill - 将数据导出为CSV文件"""

    DEFAULT_PARAMETERS = [
        {"name": "operation", "type": "string", "required": True, "description": "操作类型: export(导出CSV), read(读取CSV), parse(解析CSV内容)"},
        {"name": "data", "type": "string", "required": False, "description": "导出的数据，可以是JSON数组或表格数据"},
        {"name": "filename", "type": "string", "required": False, "description": "文件名（不含.csv扩展名）"},
        {"name": "headers", "type": "string", "required": False, "description": "CSV表头，用逗号分隔，如: name,age,email"},
        {"name": "encoding", "type": "string", "required": False, "description": "文件编码", "default": "utf-8-sig"},
    ]

    def __init__(self):
        super().__init__()
        self.name = "csv_export"
        self.description = "将数据导出为CSV文件，或读取/解析CSV文件"
        self.parameters = self.DEFAULT_PARAMETERS

    async def execute(self, **kwargs) -> SkillResult:
        operation = kwargs.get("operation", "export")
        data = kwargs.get("data", "")
        filename = kwargs.get("filename", "export")
        headers = kwargs.get("headers", "")
        encoding = kwargs.get("encoding", "utf-8-sig")

        try:
            if operation == "export":
                return await self._export_csv(data, filename, headers, encoding)
            elif operation == "read":
                return await self._read_csv(data, encoding)
            elif operation == "parse":
                return await self._parse_csv(data, encoding)
            else:
                return SkillResult(success=False, error=f"不支持的操作: {operation}")
        except Exception as e:
            logger.error(f"[CSVExport] 操作失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _export_csv(self, data: str, filename: str, headers: str, encoding: str) -> SkillResult:
        """导出数据为CSV"""
        import json

        # 解析数据
        try:
            parsed_data = json.loads(data) if data else []
        except json.JSONDecodeError:
            # 尝试解析为表格格式
            lines = [line.strip() for line in data.strip().split("\n") if line.strip()]
            parsed_data = []
            for i, line in enumerate(lines):
                if i == 0 and not headers:
                    headers = line
                    continue
                values = [v.strip() for v in line.split(",")]
                if values != ['']:
                    parsed_data.append(values)

        if not parsed_data:
            return SkillResult(success=False, error="没有可导出的数据")

        # 解析表头
        header_list = []
        if headers:
            header_list = [h.strip() for h in headers.split(",")]

        # 生成CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # 写入表头
        if header_list:
            writer.writerow(header_list)

        # 写入数据
        for row in parsed_data:
            if isinstance(row, dict):
                if header_list:
                    writer.writerow([row.get(h, "") for h in header_list])
                else:
                    writer.writerow(list(row.values()))
            elif isinstance(row, (list, tuple)):
                writer.writerow(row)
            elif isinstance(row, str):
                writer.writerow([row])

        csv_content = output.getvalue()

        # 确定文件名
        if not filename.endswith(".csv"):
            filename = f"{filename}.csv"

        return SkillResult(
            success=True,
            data={
                "filename": filename,
                "content": csv_content,
                "rows": len(parsed_data),
                "encoding": encoding,
            },
            metadata={
                "operation": "export",
                "rows_exported": len(parsed_data),
            }
        )

    async def _read_csv(self, data: str, encoding: str) -> SkillResult:
        """读取CSV内容"""
        import csv
        import io as csv_io

        try:
            # 尝试解析CSV
            reader = csv.reader(csv_io.StringIO(data))
            rows = list(reader)

            if not rows:
                return SkillResult(success=False, error="CSV内容为空")

            return SkillResult(
                success=True,
                data={
                    "rows": rows,
                    "headers": rows[0] if rows else [],
                    "data_rows": rows[1:] if len(rows) > 1 else [],
                    "total_rows": len(rows),
                },
                metadata={"operation": "read"}
            )
        except Exception as e:
            return SkillResult(success=False, error=f"解析CSV失败: {str(e)}")

    async def _parse_csv(self, data: str, encoding: str) -> SkillResult:
        """解析CSV为JSON数组"""
        return await self._read_csv(data, encoding)


# 导出执行入口
skill = CSVExportSkill()


async def execute(**kwargs) -> SkillResult:
    """Skill 执行入口"""
    return await skill.execute(**kwargs)
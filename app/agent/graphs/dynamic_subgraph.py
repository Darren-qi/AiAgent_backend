"""动态子图 - 支持并行执行、依赖解析、超时控制"""

import asyncio
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class DynamicSubgraph:
    """
    动态子图

    根据主图规划，动态创建并执行子任务图。
    支持并行和串行两种执行模式。
    新增特性:
    - 步骤依赖解析
    - 超时控制
    - 优雅降级
    """

    # 超时配置 (单位: 秒)
    DEFAULT_STEP_TIMEOUT = 300      # 默认单步超时: 5分钟
    MAX_STEP_TIMEOUT = 600           # 最大超时: 10分钟
    HTTP_STEP_TIMEOUT = 600         # HTTP类步骤超时: 10分钟

    def __init__(self):
        self.nodes = {}

    async def execute(
        self,
        steps: List[Dict[str, Any]],
        mode: str = "sequential",
        context: Optional[Dict[str, Any]] = None,
        enable_timeout: bool = True,
    ) -> Dict[str, Any]:
        """
        执行子图

        Args:
            steps: 子步骤列表
            mode: 执行模式，sequential(串行) 或 parallel(并行)
            context: 执行上下文
            enable_timeout: 是否启用超时控制

        Returns:
            包含 results 和 error 的字典
        """
        if not steps:
            return {"results": [], "error": None}

        if mode == "parallel":
            return await self._execute_with_dependencies(steps, context, enable_timeout)
        else:
            return await self._execute_sequential(steps, context, enable_timeout)

    async def _execute_sequential(
        self,
        steps: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]],
        enable_timeout: bool = True,
    ) -> Dict[str, Any]:
        """串行执行，支持超时控制"""
        results = []

        for step in steps:
            timeout = self._get_timeout_for_step(step) if enable_timeout else None

            if timeout:
                result = await self._execute_single_step_with_timeout(step, context, timeout)
            else:
                result = await self._execute_single_step(step, context)

            results.append(result)

            # 遇到错误停止
            if isinstance(result, dict) and not result.get("success", True):
                return {"results": results, "error": result.get("error")}

        return {"results": results, "error": None}

    async def _execute_with_dependencies(
        self,
        steps: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]],
        enable_timeout: bool = True,
    ) -> Dict[str, Any]:
        """
        执行计划，支持步骤依赖

        使用拓扑排序分层执行：
        - 每层内部并行
        - 层间串行
        """
        if not steps:
            return {"results": [], "error": None}

        # 1. 构建执行层次
        layers = self._build_execution_layers(steps)

        all_results = []
        errors = []

        for layer_idx, layer in enumerate(layers):
            logger.debug(f"[DynamicSubgraph] 执行第 {layer_idx + 1} 层，共 {len(layer)} 个步骤")

            # 2. 并行执行当前层
            tasks = []
            for step in layer:
                timeout = self._get_timeout_for_step(step) if enable_timeout else None
                if timeout:
                    tasks.append(
                        self._execute_single_step_with_timeout(step, context, timeout)
                    )
                else:
                    tasks.append(
                        self._execute_single_step(step, context)
                    )

            layer_results = await asyncio.gather(*tasks, return_exceptions=True)

            # 3. 处理结果
            processed_results = []
            for i, result in enumerate(layer_results):
                if isinstance(result, Exception):
                    error_result = {
                        "success": False,
                        "error": str(result),
                        "action": layer[i].get("action"),
                        "step": layer[i].get("step", i + 1),
                    }
                    processed_results.append(error_result)
                    errors.append(str(result))
                    logger.warning(f"[DynamicSubgraph] 步骤 {i + 1} 异常: {result}")
                else:
                    processed_results.append(result)
                    if isinstance(result, dict) and not result.get("success", True):
                        errors.append(result.get("error", "未知错误"))

            all_results.extend(processed_results)

            # 4. 如果当前层有失败，记录但继续执行
            layer_errors = [r.get("error") for r in processed_results if isinstance(r, dict) and not r.get("success", True)]
            if layer_errors:
                logger.warning(f"[DynamicSubgraph] 第 {layer_idx + 1} 层有 {len(layer_errors)} 个步骤失败")

        return {
            "results": all_results,
            "error": "; ".join(errors) if errors else None,
            "layers": len(layers),
        }

    def _build_execution_layers(
        self,
        steps: List[Dict[str, Any]],
    ) -> List[List[Dict[str, Any]]]:
        """
        构建执行层次

        根据 depends_on 字段进行拓扑排序，分层执行。
        没有依赖的步骤在同一层并行执行。
        """
        if not steps:
            return []

        # 为每个步骤分配索引
        indexed_plan = []
        for i, step in enumerate(steps):
            step_copy = step.copy()
            step_copy["_original_index"] = i
            if "step" not in step_copy:
                step_copy["step"] = i + 1
            indexed_plan.append(step_copy)

        # 构建入度表和依赖图
        n = len(indexed_plan)
        in_degree = {i: 0 for i in range(n)}
        dependents = {i: [] for i in range(n)}  # 谁依赖我

        for i, step in enumerate(indexed_plan):
            depends_on = step.get("depends_on", [])
            if isinstance(depends_on, int):
                depends_on = [depends_on]

            for dep_idx in depends_on:
                if 0 <= dep_idx < n:
                    in_degree[i] += 1
                    dependents[dep_idx].append(i)

        # Kahn算法拓扑排序并分层
        layers = []
        remaining = set(range(n))

        while remaining:
            # 找到入度为0的节点（当前层）
            current_layer = [i for i in remaining if in_degree[i] == 0]

            if not current_layer:
                # 存在依赖循环，将剩余节点作为一层（可以正常执行）
                current_layer = list(remaining)
                # 降低日志级别，因为这在某些场景下是正常的（如多次调用同一skill生成不同文件）
                logger.info(
                    f"[DynamicSubgraph] 存在依赖循环，已合并执行: "
                    f"{[indexed_plan[i].get('action') for i in current_layer]}"
                )

            # 添加当前层
            layers.append([indexed_plan[i] for i in current_layer])

            # 更新入度
            for i in current_layer:
                remaining.remove(i)
                for dependent in dependents[i]:
                    in_degree[dependent] -= 1

        return layers

    async def _execute_single_step_with_timeout(
        self,
        step: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        timeout: float,
    ) -> Dict[str, Any]:
        """带超时的步骤执行"""
        try:
            return await asyncio.wait_for(
                self._execute_single_step(step, context),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"步骤执行超时: {timeout}秒",
                "action": step.get("action"),
                "step": step.get("step"),
                "timeout": True,
            }

    async def _execute_single_step(
        self,
        step: Dict[str, Any],
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """执行单个步骤"""
        action = step.get("action", "unknown")
        params = step.get("params", {}).copy()

        # 传递 context 中的 task_path
        if context and context.get("task_path"):
            params["task_path"] = context.get("task_path")

        try:
            from app.agent.skills.core.progressive_loader import get_loader
            loader = get_loader()
            result = await loader.execute(action, params)
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error,
                "action": action,
                "step": step.get("step"),
            }
        except Exception as e:
            # 备用：尝试从旧 registry 执行
            try:
                from app.agent.skills.registry import registry
                skill = registry.get(action)
                if skill:
                    result = await skill.execute(**params)
                    return {
                        "success": result.success,
                        "data": result.data,
                        "error": result.error,
                        "action": action,
                        "step": step.get("step"),
                    }
            except:
                pass

            logger.exception(f"[DynamicSubgraph] 步骤执行异常: {action}")
            return {
                "success": False,
                "error": str(e),
                "action": action,
                "step": step.get("step"),
            }

    def _get_timeout_for_step(self, step: Dict[str, Any]) -> float:
        """根据步骤类型获取超时时间"""
        action = step.get("action", "").lower()

        # HTTP 相关步骤使用更长超时
        if action in ("http_client", "crawler", "search", "web"):
            return self.HTTP_STEP_TIMEOUT

        # 检查 params 中是否指定了超时
        params = step.get("params", {})
        if "timeout" in params:
            return min(float(params["timeout"]), self.MAX_STEP_TIMEOUT)

        return self.DEFAULT_STEP_TIMEOUT

    def add_node(self, name: str, handler) -> None:
        """添加子图节点"""
        self.nodes[name] = handler

    def get_node(self, name: str):
        """获取子图节点"""
        return self.nodes.get(name)

    def configure_timeouts(
        self,
        default: Optional[int] = None,
        max_timeout: Optional[int] = None,
        http_timeout: Optional[int] = None,
    ) -> None:
        """配置超时参数"""
        if default is not None:
            self.DEFAULT_STEP_TIMEOUT = default
        if max_timeout is not None:
            self.MAX_STEP_TIMEOUT = max_timeout
        if http_timeout is not None:
            self.HTTP_STEP_TIMEOUT = http_timeout

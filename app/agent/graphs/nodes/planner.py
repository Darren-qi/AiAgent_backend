"""规划器节点 - LLM 动态规划"""

import asyncio
import json
import re
import logging
from typing import Dict, Any, List, Optional

from app.agent.llm.factory import LLMFactory
from app.agent.skills.core.progressive_loader import (
    get_loader, ProgressiveSkillLoader, validate_params_structure,
)

logger = logging.getLogger(__name__)

# 快速待办生成 Prompt - 简洁输出，每行 checkbox
QUICK_TODOS_PROMPT = """你是一个任务规划专家。请将用户任务分解为简洁的待办事项。

## 用户任务
{task}

## 初步判断（先做这一步）
先判断任务复杂度，决定拆解方式：
- **简单任务**：多轮对话中的小改动——新增或修改单个文件、改一处配置/文案/逻辑、
  加一个文件或对某个文件进行调整等，一两步即可完成，无需拆解设计。
- **复杂任务**：涉及多文件/多模块/需要分阶段设计与交付的任务。

## 输出要求
1. 简单任务：只输出 1 条待办（把任务本身作为一条直接执行的动作），
   且该行末尾必须附加标记 ` [SIMPLE]`，不再输出其他待办。
2. 复杂任务：只输出 2-5 个待办事项，不要太多；每行一个，格式: `- [ ] 事项描述`
3. 事项描述要简洁，一行说完；不要详细展开每个步骤的实现细节
4. 每个待办负责 1-3 个文件的产出；纯骨架/配置类互不依赖的新建文件可合并为一条待办批量产出（执行时一次并发建完）；有逻辑关联的 4 个以上文件仍拆多条待办（如"搭建项目骨架"和"创建组件"分开写）
5. 待办必须指向用户要求的**最终状态**，不是过程动作：
   只读的"扫描/梳理/分析/规划"不能作为唯一待办，必须与实际改动合并在同一条待办里
   （如"扫描根目录并将文件移入对应子目录"）；
   要求"只保留/全部移入/清理掉"这类状态型任务，最后一条必须是校验最终状态的待办
6. 涉及移动、删除、整理多个文件或改变目录结构的任务，一律按复杂任务拆解，不得标 [SIMPLE]

## 示例
输入: "为用户模块添加 JWT 认证功能"
输出（复杂）:
- [ ] 创建 JWT 认证工具类
- [ ] 实现登录接口
- [ ] 添加 Token 验证中间件

输入: "在 main.py 里加一行日志打印"
输出（简单）:
- [ ] 在 main.py 中添加日志打印 [SIMPLE]

输入: "爬取某网站新闻并保存"
输出（复杂）:
- [ ] 获取网页内容
- [ ] 解析新闻数据
- [ ] 保存到文件

请为以下任务生成待办："""

# 计划分析 Prompt - 对每个计划项进行深入分析
PLAN_ANALYSIS_PROMPT = """你是一个任务执行分析专家。请对以下执行计划中的每个步骤进行深入分析。

## 用户任务
{task}

## 执行计划
{plan}

## 分析要求
对每个步骤，分析以下内容：
1. **步骤目的**：这个步骤要达成什么目标
2. **执行策略**：如何正确执行这个步骤
3. **可能的问题**：执行中可能遇到什么困难
4. **预期结果**：成功执行后的预期产出

## 输出格式
按以下格式输出每个步骤的分析（不需要完整JSON，用简洁的描述性文字）：

**步骤 1: [动作名称]**
- 目的：[分析目的]
- 策略：[执行策略]
- 注意：[需要注意的问题]
- 预期：[预期结果]

请开始分析："""

# Thought 阶段 Prompt - 分析当前状态
THOUGHT_PROMPT = """你正在执行用户任务中的某个待办事项。

## 用户任务
{task}

## 当前待办
todo_id: {todo_id}
title: {title}

## 历史上下文
{context}

## 思考要求
1. 分析当前待办的目标
2. 考虑需要的资源和步骤
3. 预判可能的困难
4. 简明输出你的思考
5. 待办涉及多个文件时：**互不依赖的新建文件用一次 write 的 files 数组批量并发落盘**（`{{"operation":"write","files":[{{"path":"a.py","content":"..."}},{{"path":"b.py","content":"..."}}]}}`，一次写完缺失清单里的全部文件，子目录自动创建）；只有文件间存在依赖（需先读/先建才能写）或需逐个核对内容时才逐轮推进。禁止重复生成已存在的文件；批量单次≤4文件、总内容≤6000字，超出拆多次调用——把超长内容塞进单个参数会被输出上限截断成残缺 JSON
6. 改动已有文件前先在思考里做前置判断：这处改动是局部（增删改个别几处）还是重写级？局部 → 用 edit（old_text→new_text 只替换改动处，其余内容零风险）；重写级/大幅重构或新建文件 → 才用 write 全量覆盖（必须基于完整内容，长文件先读完所有分页再覆盖）。判断幅度由你根据需求权衡，把结论写进思考再动手
7. 梳理/定位代码先用 search_files 关键词搜索（拿到 文件:行号），再用 read 的 offset/limit 精读命中点附近；禁止整读大文件、禁止反复 list 目录漫游
8. 信息足够就立即推进产出；当历史上下文出现"最后一轮/强制交付"或观察提示该产出交付物时，本轮必须产出，不要再收集信息
9. 移动/归类/整理/迁移类待办用 file_operations 的 operation=move，支持批量 files=[{{path,dest}}]（或 from/to、src/dst 键，一次搬多个；模板转义故写双括号）；单个用 path=源, dest=目标。**禁止在目标位置用 write 重新生成一份冒充移动**——移动完成后原位置必须不再有该文件。批量清理用 delete 的 files=[{{path}}] 或 paths=[...]（delete 也支持批量）。**归类时禁止在任务根新建 legacy/archive/old 等归档目录**——旧文件移进需求点名的子目录或直接删除，根目录不得因归类多出任何新条目
10. 所有 path 参数必须与【任务目录现有文件】清单里的相对路径逐字一致：文件在子目录就必须带前缀（清单里是 app/extensions.py 就读 app/extensions.py，不许写裸的 extensions.py）；清单是本轮开始时的快照，移动/新建后会过期——对清单没有或没把握的路径，本轮先用 operation=list 看一次真实目录树再访问，禁止凭待办文字臆测目录（如想当然的 backend/）
11. 观察结果是"工具执行失败"时：下一轮必须修正参数后**重试同一个动作**（缺参数就补参数、路径错就改正路径），最多连续重试 2 次；连续失败才允许换替代路径。禁止用连续的只读动作绕开失败——只读不产生进展，会耗尽轮次预算导致待办判失败
12. 带结构要求的待办（如"只显示两个子目录""文件全部归类"）收尾前必须 operation=list 看一次真实根目录逐条核对，真实结构与要求一致才允许写完成结论；根目录条目**含隐藏文件**（.gitignore/.env.example 等）也算数——要求"根目录只剩两个子目录"时隐藏文件同样是残留，删除或移入子目录；禁止凭记忆里的计划宣布达成——移动类任务要确认原位置没有漏搬的残留文件
13. write **新建**文件成功后不要读回确认——你刚生成的内容就在上下文里，直接看观察里的缺件清单推进下一批（缺什么写什么，写完看完成判定），"读一遍刚写的文件确认结构"是浪费轮次。只允许三种读：①写依赖方前读被依赖文件（如写 routes.py 前读 models.py 拿字段）②覆盖/重写已有文件前读全其内容 ③观察报该文件写入异常需排障

请输出你的思考："""

# Planning 阶段 Prompt - 生成执行计划
PLANNING_PROMPT = """基于你的思考，制定具体的执行动作。

## 用户任务
{task}

## 当前待办
todo_id: {todo_id}
title: {title}

## 你的思考
{thought}

## 可用工具
{skill_list}

## 输出要求
1. 选择最合适的工具/动作
2. 给出具体的参数
3. 简洁明了

## 重要：技能选择和参数格式

### 代码生成任务 → 使用 code_generator（首选！）
**生成代码文件时必须用 code_generator，不要用 file_operations！**
code_generator 会自动写入文件，参数格式：
动作: code_generator
参数: {"language": "python", "framework": "flask", "requirements": "创建 Flask 博客项目，包含 models.py, routes.py, templates/"}
原因: 生成完整的 Flask 博客代码

### 代码定位 → 使用 search_files（先搜后读）
**在任务目录里找代码/文件时优先 search_files，不要靠 read 整读或 list 逐层翻：**
参数: {"pattern": "delete|remove", "target": "content", "output_mode": "content"}
- target=content 按正则搜内容（返回 文件:行号: 匹配行）；target=files 按文件名 glob 找文件
- output_mode: content（明细）/ files_only（仅文件）/ count（每文件命中数，先探分布）
- 拿到行号后用 file_operations read 精读：offset=行号-10, limit=80（content 带行号仅用于定位，写回文件时不要带行号）

### 简单文件操作 → 使用 file_operations
**读取、列出、删除、移动/归类、局部修改已有文件时使用 file_operations！**
参数必须是 JSON 格式：
- `operation`: create/write/read/list/delete/edit/move
- `path`: 文件路径（必须用 path！不是 filename）
- `content`: 文件内容（write 时需要）
- `files`: 批量写入数组（write 时可替代 path+content）：[{"path": "a.py", "content": "..."}, {"path": "b.py", "content": "..."}]——互不依赖的新建文件一次并发写完，骨架类禁止逐文件多轮；单次≤4文件、总内容≤6000字，超出拆多次调用（防输出截断成残缺 JSON）
- `dest`: move 的目标路径（move 时需要；移动类任务禁止用 write 在目标处重建副本）
- `old_text`/`new_text`/`replace_all`: edit 局部替换（old_text 必须与文件逐字一致且唯一；命中多处才传 replace_all=true）
- `offset`/`limit`: read 分页（默认读前 200 行；大文件按需指定 offset 续读）

### 示例

**写入简单文件：**
动作: file_operations
参数: {"operation": "write", "path": "requirements.txt", "content": "Flask>=3.0"}
原因: 创建依赖文件

**批量创建多个互不关联的文件（项目骨架，一次并发建完）：**
动作: file_operations
参数: {"operation": "write", "files": [{"path": "config.py", "content": "..."}, {"path": "app/__init__.py", "content": "..."}, {"path": "requirements.txt", "content": "Flask>=3.0"}]}
原因: 三个文件互不依赖，批量并发落盘，避免逐文件多轮等待

**读取文件：**
动作: file_operations
参数: {"operation": "read", "path": "app.py"}
原因: 检查文件内容

**局部修改已有文件（改动幅度判断为局部时优先）：**
动作: file_operations
参数: {"operation": "edit", "path": "app.py", "old_text": "要改的原文片段", "new_text": "替换后的新文本"}
原因: 只替换这一处，文件其余部分不动

**移动/归类文件（"统一放到xx目录"类任务专用）：**
动作: file_operations
参数: {"operation": "move", "path": "main.py", "dest": "backend/main.py"}
原因: 把根目录 main.py 搬进 backend，移动后原位置不再保留

## 错误示例（绝对不要这样写）
❌ 用 file_operations 写复杂的代码文件（应该用 code_generator）
❌ 参数: {"filename": "app.py", "content": "..."}（参数名错误，应该用 path）
❌ 参数: operation: write, path: app.py, content: ...（不是 JSON 格式）

## 目标文件（必须输出）
- 列出**本轮**动作会创建或修改的文件（相对任务目录的路径，含扩展名），逗号分隔，最多3个
- 只列本待办标题范围内的产出；整个项目的文件清单分摊到各待办/各轮次，不要一次列全
- 本待办不产出任何文件时写: 目标文件: 无
- 修改已有文件算目标文件（列出被改的文件）；改动是局部还是重写级由你在计划里判断：局部改用 edit、重写级才全量覆盖
- 新功能必须生成新文件；只有待办标题就是修改某个已有文件时才允许改它

请输出（四行，缺一不可）：
动作: <action_name>
参数: {"key": "value"}
原因: <为什么选择这个动作>
目标文件: <file1.py, file2.py；无则写"无">
"""

# Observation 阶段 Prompt - 验证结果
OBSERVATION_PROMPT = """观察执行结果，判断待办是否完成。

## 用户任务
{task}

## 当前待办
todo_id: {todo_id}
title: {title}

## 执行动作
action: {action}
参数: {params}

## 执行结果
{result}

## 过程记录（本待办的思考与计划，用于提取文件清单）
{extra_context}

## 判断要求
1. 结果是否成功？
2. 是否达到预期效果？文件是否齐全**以输入中【任务目录现有文件】为准核实**，不要因思考里复述了计划清单就判未完成或已完成
3. 是否需要继续或调整？
4. 文件清单（files）只列"计划要产出但【任务目录现有文件】中没有"的缺失文件（相对路径，含扩展名）
   - 已在【任务目录现有文件】中的不要列；reason 里点名"缺失/仍需补全"的文件必须同时列入 files（两者保持一致）
   - 禁止把类别或需求描述（如"src、public、配置文件、组件、样式"）展开补全成具体文件清单
   - 禁止罗列"一个完整项目应有的文件"；其他待办负责的文件不列
   - 目录、工具名、概念不算文件；没有则写"无"
5. **【完成判据】** 完成 =【任务目录现有文件】齐全 + 内容正确 + 与需求一致。
   **环境能力边界**：沙箱只支持 Python（code/file 参数），服务器未安装 node/npm/docker，
   npm install、npm run build、pytest、浏览器渲染这类运行验证**不可能在沙箱完成**，
   **不得因此判未完成**。JS/前端/构建类任务以文件齐全 + 代码逻辑正确为完成依据；
   仅当已实际运行的验证（Python 执行）报错时才判未完成，并附具体报错。
   **反例（禁止）**：文件已写完且正确，却因"没跑过 npm build/没看到 stdout"判未完成——会让任务无限循环。
   **正例**："5个文件齐全、代码正确，构建类任务无法在沙箱运行验证，判完成"；
   "Python 实际运行抛 NameError: x 未定义，判未完成"。
6. **移动/归类/整理/迁移类待办**（按待办标题语义判断）：完成 = 目标位置已有该文件，
   **且【任务目录现有文件】中原位置已不再有它**。只在目标位置新建了副本、
   原文件仍留在原处 = 未完成，reason 点名仍留在原位置的文件。
7. **状态必须与原因自洽**：本轮某个动作成功执行 ≠ 待办完成。判"已完成"前对照当前待办
   标题的全部目标逐项核对；只要原因里写明还有任何未达成的内容，完成状态就不得标"已完成"。
8. **reason 只写本步结果与问题**：说明本轮动作的结果与具体缺口/报错（做了什么、还缺
   什么文件、报错原文），不要以"待办未完成"这类状态断言开头——状态由完成状态行
   单独表达，reason 重复状态会让读者误以为本步操作失败。

输出格式：
完成状态: [已完成 / 部分完成 / 未完成]
原因: <判断理由>
建议: <下一步建议>
文件: <逗号分隔的文件路径列表，或"无">
"""

# Skill 清单（用于规划参考）
AVAILABLE_SKILLS = {
    "http_client": {
        "description": "发起 HTTP/HTTPS 请求，获取网页内容或 API 数据",
        "params": ["url", "method", "headers", "timeout"],
        "use_for": ["爬取网页", "调用API", "获取数据"]
    },
    "code_generator": {
        "description": "生成代码，支持多种编程语言",
        "params": ["language", "requirements", "framework", "task_path"],
        "use_for": ["写代码", "生成代码", "编程"]
    },
    "sandbox": {
        "description": "在隔离沙箱中运行 Python 代码或任务目录下的脚本（运行测试/验证）",
        "params": ["code", "file", "timeout"],
        "use_for": ["运行测试", "执行脚本", "验证代码", "跑用例"]
    },
    "data_processor": {
        "description": "数据处理、转换、统计分析",
        "params": ["operation", "input_data", "options"],
        "use_for": ["数据处理", "统计分析", "数据转换"]
    },
    # 文件操作（细粒度）
    "init_project": {
        "description": "初始化项目结构 - 创建项目根目录和基础文件框架",
        "params": ["path", "content"],
        "use_for": ["创建项目", "初始化项目", "创建项目结构", "新建项目目录"]
    },
    "write_file": {
        "description": "写入文件 - 创建新文件或覆盖已有文件内容",
        "params": ["path", "content", "task_path"],
        "use_for": ["写文件", "创建文件", "保存文件", "写入代码", "生成模型文件"]
    },
    "read_file": {
        "description": "读取文件 - 查看文件内容",
        "params": ["path"],
        "use_for": ["读取文件", "查看文件", "读取代码"]
    },
    "edit_file": {
        "description": "编辑文件 - 修改已有文件内容（支持增量修改）",
        "params": ["path", "content", "operation"],
        "use_for": ["编辑文件", "修改代码", "更新文件"]
    },
    "delete_file": {
        "description": "删除文件或目录",
        "params": ["path"],
        "use_for": ["删除文件", "删除目录"]
    },
    "list_dir": {
        "description": "列出目录内容",
        "params": ["path"],
        "use_for": ["列出目录", "查看目录"]
    },
    # 兼容旧名称
    "file_operations": {
        "description": "文件操作（通用）- 支持 init_project/write_file/read_file/edit_file/delete_file 等操作",
        "params": ["operation", "path", "content", "task_path"],
        "use_for": ["文件操作", "读写文件"]
    },
    "notification": {
        "description": "发送通知（邮件、社交平台）",
        "params": ["channel", "recipient", "content"],
        "use_for": ["发送通知", "提醒"]
    },
    "search": {
        "description": "信息搜索",
        "params": ["query", "engine", "limit"],
        "use_for": ["搜索信息", "查找资料"]
    },
    "general_response": {
        "description": "通用对话响应",
        "params": [],
        "use_for": ["问答", "对话", "解释"]
    }
}


class Planner:
    """任务规划器 - LLM 动态规划"""

    # 任务规划 Prompt
    PLANNING_PROMPT = """你是一个专业的任务规划专家。请将用户任务分解为可执行的步骤。

## 可用 Skill（工具/动作）：
{skill_list}

## 输出要求：
请以 JSON 数组格式返回执行计划，每个步骤包含：
- **step**: 步骤序号（从1开始）
- **action**: 调用的 Skill 名称（必须在上述列表中）
- **params**: Skill 参数（根据 skill 定义填写）
- **description**: 步骤描述
- **parallel**: 是否可以与后续步骤并行执行
- **depends_on**: 依赖的前置步骤序号列表（默认为空）

## 规则：
1. 独立步骤设置 parallel: true，可并行执行
2. 有依赖的步骤在 depends_on 中指定前置步骤
3. 简单任务 1-3 步，复杂任务 5-10 步
4. 每个步骤必须有实际意义，不能是空步骤
5. 参数必须符合 Skill 定义，不需要的参数可省略
6. 确保步骤之间有明确的数据流动

## 示例：
输入: "爬取某网站新闻并保存到文件"
输出:
[
  {{
    "step": 1,
    "action": "http_client",
    "params": {{"url": "目标URL", "method": "GET"}},
    "description": "获取网页内容",
    "parallel": false,
    "depends_on": []
  }},
  {{
    "step": 2,
    "action": "data_processor",
    "params": {{"operation": "parse_html", "input": "步骤1的结果"}},
    "description": "解析HTML提取新闻标题",
    "parallel": false,
    "depends_on": [1]
  }},
  {{
    "step": 3,
    "action": "file_operations",
    "params": {{"operation": "write", "path": "news.txt", "content": "步骤2的结果"}},
    "description": "保存到文件",
    "parallel": false,
    "depends_on": [2]
  }}
]

请为以下任务制定执行计划："""

    # 计划优化 Prompt（用于 refine）
    REFINE_PROMPT = """你是一个任务规划优化专家。请根据反馈优化执行计划。

## 当前计划：
{current_plan}

## 用户反馈/错误：
{feedback}

## 输出要求：
返回优化后的 JSON 执行计划，格式同上。

请优化计划："""

    def __init__(self):
        self._llm_factory: Optional[LLMFactory] = None
        self._use_llm = True
        self._task_id: Optional[str] = None
        self._fallback_intents = {
            "crawler": ["http_client", "data_processor"],
            "code": ["code_generator"],
            "analysis": ["data_processor", "general_response"],
            "search": ["search"],
            "notification": ["notification"],
            "file_ops": ["file_operations"],
            "data": ["data_processor"],
            "general": ["general_response"],
        }

    def set_task_id(self, task_id: str) -> None:
        """设置任务 ID，用于可取消的 LLM 调用"""
        self._task_id = task_id

    @property
    def llm_factory(self) -> LLMFactory:
        """延迟初始化 LLM 工厂"""
        if self._llm_factory is None:
            self._llm_factory = LLMFactory.get_instance()
        return self._llm_factory

    def _get_skill_list_str(self, stage: Optional[str] = None) -> str:
        """生成 Skill 列表字符串（从渐进式加载器获取）。

        阶段四：stage=None 全量（默认不回归）；stage="plan" 规划早期只读集；
        stage="execute" 执行期全量。tool_deny_risks 黑名单在 loader 内叠加。
        """
        try:
            loader = get_loader()
            return loader.get_skill_list_str(stage=stage)
        except Exception as e:
            logger.warning(f"[Planner] 获取 Skill 列表失败: {e}，使用备用方案")
            # 备用：使用 AVAILABLE_SKILLS
            lines = []
            for name, info in AVAILABLE_SKILLS.items():
                params = ", ".join(info["params"]) if info["params"] else "无"
                use_for = ", ".join(info["use_for"])
                lines.append(f"- **{name}**: {info['description']} | 参数: {params} | 适用: {use_for}")
            return "\n".join(lines)

    async def _llm_chat(self, messages: list, **kwargs):
        """
        统一 LLM 调用方法，自动传递 task_id 以支持取消

        Args:
            messages: 消息列表
            **kwargs: 其他参数（如 strategy, temperature 等）

        Returns:
            LLM 响应
        """
        # 如果有 task_id，传递它以支持可取消的 LLM 调用
        if self._task_id:
            kwargs["task_id"] = self._task_id
        return await self.llm_factory.chat(messages, **kwargs)

    async def create_plan(self, task: str, intent: str) -> List[Dict[str, Any]]:
        """
        创建执行计划

        Args:
            task: 用户任务描述
            intent: 检测到的意图

        Returns:
            执行计划列表
        """
        logger.info(f"[Planner] 为任务创建计划: {task[:80]}... | 意图: {intent}")

        # 1. 尝试 LLM 动态规划
        if self._use_llm:
            try:
                plan = await self._create_plan_with_llm(task, intent)
                if plan:
                    logger.info(f"[Planner] LLM 生成计划，包含 {len(plan)} 个步骤")
                    return plan
            except Exception as e:
                logger.warning(f"[Planner] LLM 规划失败: {e}")

        # 2. 降级到基于意图的启发式规划
        plan = self._create_heuristic_plan(task, intent)
        logger.info(f"[Planner] 使用启发式规划，包含 {len(plan)} 个步骤")
        return plan

    async def create_quick_todos(self, task: str) -> List[Dict[str, Any]]:
        """
        快速生成简洁的待办列表

        用于规划阶段快速输出，每行 checkbox 格式。

        Args:
            task: 用户任务描述

        Returns:
            待办列表，每项包含 id, title, action (可选), params (可选)
        """
        logger.info(f"[Planner] 快速生成待办: {task[:80]}...")

        prompt = QUICK_TODOS_PROMPT.format(task=task)

        try:
            response = await self._llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="fast",  # 使用快速策略
                temperature=0.3,
                max_tokens=1000,  # 待办可能较多，500 会截断列表
            )

            content = response.content.strip()
            todos = self._parse_quick_todos(content)

            if todos:
                logger.info(f"[Planner] 生成 {len(todos)} 个待办事项")
                return todos

        except Exception as e:
            logger.warning(f"[Planner] 快速待办生成失败: {e}")

        # 降级：返回简单待办
        return self._create_fallback_todos(task)

    def _parse_quick_todos(self, content: str) -> List[Dict[str, Any]]:
        """解析快速待办输出；识别 [SIMPLE] 标记（简单任务初判，只保留 1 条直接执行）"""
        todos = []
        lines = content.split('\n')

        for i, line in enumerate(lines):
            line = line.strip()
            # 匹配 - [ ] 或 - [x] 格式
            match = re.match(r'^[-*]\s*\[\s*[xX]?\s*\]\s*(.+)', line)
            if match:
                title = match.group(1).strip()
                if title:
                    # 简单任务标记：去掉标记文本，标记到 todo 上，只保留这一条
                    if "[SIMPLE]" in title.upper():
                        title = re.sub(r'\s*\[SIMPLE\]', '', title, flags=re.IGNORECASE).strip()
                        todos = [{
                            "id": 1,
                            "title": title,
                            "action": None,
                            "params": {},
                            "status": "pending",
                            "simple": True,
                        }]
                        break
                    todos.append({
                        "id": len(todos) + 1,
                        "title": title,
                        "action": None,
                        "params": {},
                        "status": "pending"
                    })

        # 简单任务兜底：只有 1 条待办也视为简单（前端据此不摆计划框）
        if len(todos) == 1 and "simple" not in todos[0]:
            todos[0]["simple"] = True

        return todos

    def _create_fallback_todos(self, task: str) -> List[Dict[str, Any]]:
        """创建降级待办"""
        return [{
            "id": 1,
            "title": f"执行任务: {task[:50]}",
            "action": "general_response",
            "params": {"input": task},
            "status": "pending"
        }]

    async def think(self, task: str, todo: Dict[str, Any], context: str = "") -> str:
        """
        Thought 阶段：分析当前状态

        Args:
            task: 用户任务
            todo: 当前待办项
            context: 历史上下文

        Returns:
            思考结果
        """
        prompt = THOUGHT_PROMPT.format(
            task=task,
            todo_id=todo.get("id", 0),
            title=todo.get("title", ""),
            context=context or "（无历史记录）"
        )

        try:
            response = await self._llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="quality",
                temperature=0.5,
                max_tokens=800,
            )
            return response.content.strip()
        except asyncio.CancelledError:
            logger.warning(f"[Planner] think LLM 调用被取消")
            raise  # 传播取消信号，不吞掉
        except Exception as e:
            logger.warning(f"[Planner] Thought 阶段失败: {e}")
            return f"思考中...（LLM 调用失败: {e}）"

    async def plan_action(
        self,
        task: str,
        todo: Dict[str, Any],
        thought: str
    ) -> Dict[str, Any]:
        """
        Planning 阶段：生成执行动作

        Args:
            task: 用户任务
            todo: 当前待办项
            thought: 思考结果

        Returns:
            动作配置 {action, params, reason}
        """
        skill_list = self._get_skill_list_str(stage="execute")

        prompt = PLANNING_PROMPT.format(
            task=task,
            todo_id=todo.get("id", 0),
            title=todo.get("title", ""),
            thought=thought,
            skill_list=skill_list
        )

        try:
            response = await self._llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="quality",
                temperature=0.3,
                # write 场景 content 会带整段代码，500 token 截断后 JSON 解析失败
                max_tokens=4096,
            )

            content = response.content.strip()
            plan_result = self._parse_planning_response(content, todo)

            # 验证并补充必要参数；补后重算 params_invalid（补默认键可能改变结构）
            plan_result["params"] = self._ensure_required_params(
                plan_result["action"],
                plan_result["params"],
                todo
            )
            self._refresh_params_invalid(plan_result)

            return plan_result

        except Exception as e:
            logger.warning(f"[Planner] Planning 阶段失败: {e}")
            return {
                "action": "general_response",
                "params": {"input": f"执行待办: {todo.get('title', '')}"},
                "reason": f"降级执行（LLM 调用失败: {e}）"
            }

    def _skill_schema_hint(self, skill_name: str) -> str:
        """JIT（方案 §3-12）：平时 prompt 只带"名称+一句话"技能清单；
        只在选中技能出错重试时，取其全量参数 schema 注入反馈。"""
        if not skill_name:
            return ""
        try:
            for s in get_loader().get_schemas():
                if s.get("name") != skill_name:
                    continue
                params = s.get("parameters") or {}
                props = params.get("properties") or {}
                required = set(params.get("required") or [])
                if not props:
                    return f"\n\n**{skill_name} 参数要求**: 无参数"
                lines = [
                    f"- {k}（{'必填' if k in required else '可选'}）: "
                    f"{(v or {}).get('description', '')}".rstrip(": ")
                    for k, v in props.items()
                ]
                hint = (f"\n\n**{skill_name} 全量参数 schema**"
                        f"（按此修正，必填项一个都不能少）:\n" + "\n".join(lines))
                usage = str(s.get("usage") or "").strip()
                if usage:
                    # 渐进第三级：选定工具出错时随 schema 注入具体使用方法
                    hint += f"\n\n**{skill_name} 调用须知**:\n{usage}"
                return hint
        except Exception as e:  # noqa: BLE001 - schema 获取失败不阻塞规划
            logger.warning(f"[Planner] 获取 skill schema 失败: {e}")
        return ""

    def _render_skill_params(self, skill_name: str) -> str:
        """阶段四试点：从 frontmatter 渲染技能参数说明段（唯一权威）。

        避免 prompt 硬编码参数列表与 SKILL.md frontmatter 漂移——
        file_operations 试点，其余技能随后续阶段跟进。
        """
        try:
            meta = get_loader().get_metadata(skill_name)
            if not meta:
                return f"   - {skill_name}: （未注册）"
            props = ((meta.parameters or {}).get("properties")) or {}
            lines = [
                f"   - {skill_name}（参数必须是 JSON 对象，键名用下面列出的）:"
            ]
            for key, spec in props.items():
                spec = spec or {}
                req = "必填" if spec.get("required") else "可选"
                desc = str(spec.get("description") or "").strip()
                enum = spec.get("enum")
                extra = (
                    f"，可选值: {', '.join(str(x) for x in enum)}"
                    if enum else ""
                )
                lines.append(f"     - {key}（{req}）: {desc}{extra}")
            if meta.usage:
                lines.append(f"     - 调用须知: {meta.usage}")
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001 - 渲染失败不阻塞规划
            logger.warning("[Planner] 渲染 %s 参数段失败: %s", skill_name, e)
            return ""

    async def plan_action_with_feedback(
        self,
        task: str,
        todo: Dict[str, Any],
        thought: str,
        last_error: str = None,
        last_result: str = None,
        last_action: str = None,
        last_error_code: str = None,
    ) -> Dict[str, Any]:
        """
        Planning 阶段：生成执行动作（带错误反馈）

        如果上一步执行失败，会分析错误原因并调整参数。

        Args:
            task: 用户任务
            todo: 当前待办项
            thought: 思考结果
            last_error: 上一步的错误信息
            last_result: 上一步的执行结果
            last_action: 上一步选中的技能名（JIT：出错才注入其全量 schema）
            last_error_code: 上一步结构化错误码（TOOL_ERROR_CODES，优先按 code 分支）

        Returns:
            动作配置 {action, params, reason}
        """
        # todos 已建 → 执行期（阶段四：执行期全量注入）
        skill_list = self._get_skill_list_str(stage="execute")

        # 如果有错误，在 prompt 中添加错误反馈
        feedback_section = ""
        if last_error:
            correction_hints = self._build_correction_hints(
                last_error, last_error_code)
            # 缺参类错误（按 code 或文案判定）→ JIT 注入全量 schema+调用须知
            _need_schema = (
                last_error_code == "MISSING_PARAM"
                or ("缺少" in last_error and "参数" in last_error)
            )
            _code_line = (
                f"错误代码: {last_error_code}\n" if last_error_code else "")
            feedback_section = f"""
## 上一步执行失败
{_code_line}错误信息: {last_error}
执行结果: {last_result}
{correction_hints}
请分析失败原因，并给出修正后的动作和参数。

**重要**: 必须修正上一步缺失的参数，特别是 `path` 参数必须明确指定值。
""" + (self._skill_schema_hint(last_action) if _need_schema else "")

        # 阶段四试点：file_operations 参数段从 frontmatter 渲染（唯一权威）
        file_ops_doc = self._render_skill_params("file_operations")
        prompt = f"""基于你的思考，制定具体的执行动作。

## 用户任务
{task}

## 当前待办
todo_id: {todo.get("id", 0)}
title: {todo.get("title", "")}

## 你的思考
{thought}
{feedback_section}

## 可用工具
{skill_list}

## 输出要求（必须遵守）
1. 动作名称必须是上面列表中的有效名称
2. **参数必须完整且具体**:
{file_ops_doc}
   - http_client: 必须包含 url
   - code_generator: 必须包含 requirements/language
3. 如果上一步失败，必须修正对应的参数
4. **目标文件必须列出**：本轮动作会创建或修改的文件路径（相对任务目录，含扩展名），最多3个；本待办其余文件在后续轮次计划中列出；不产出文件写"无"。新功能=新文件，禁止为"新增功能"覆盖已有文件
5. **测试/脚本必须实跑**：待办涉及测试或可执行脚本时，写完后必须规划 sandbox 动作（file=脚本相对路径）运行它；测试不通过就把错误带回下一步修复，不能只写不跑

## 文件路径示例（正确 vs 错误）
✅ 正确: {{"operation": "write", "path": "app.py", "content": "from flask import Flask..."}}
✅ 正确: {{"operation": "write", "path": "routes/__init__.py", "content": ""}}
✅ 正确: {{"operation": "write", "path": "templates/index.html", "content": "<!DOCTYPE html>..."}}
✅ 正确（互不依赖的多个文件批量并发建完，替代逐文件多轮）: {{"operation": "write", "files": [{{"path": "config.py", "content": "..."}}, {{"path": "app/__init__.py", "content": "..."}}]}}
❌ 错误: {{"operation": "write", "path": "@app.route('/')", "content": "..."}}
❌ 错误: {{"operation": "write", "path": "def index()", "content": "..."}}

## 输出格式（严格按此格式）
```
动作: <action_name>
参数: {{"key": "value", "key2": "value2"}}
原因: <为什么选择这个动作>
目标文件: <file1.py, file2.py；不产出文件写"无">
```"""

        try:
            response = await self._llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="quality",
                temperature=0.3,
                # content 里要放整段代码，500 token 会硬截断导致 JSON 解析失败
                max_tokens=4096,
            )

            content = response.content.strip()
            plan_result = self._parse_planning_response(content, todo)

            # 验证并补充必要参数；补后重算 params_invalid（补默认键可能改变结构）
            plan_result["params"] = self._ensure_required_params(
                plan_result["action"],
                plan_result["params"],
                todo
            )
            self._refresh_params_invalid(plan_result)

            return plan_result

        except asyncio.CancelledError:
            raise  # 传播取消信号，不吞掉
        except Exception as e:
            logger.warning(f"[Planner] Planning 阶段失败: {e}")
            return {
                "action": "general_response",
                "params": {"input": f"执行待办: {todo.get('title', '')}"},
                "reason": f"降级执行（LLM 调用失败: {e}）"
            }

    def _refresh_params_invalid(self, plan_result: Dict[str, Any]) -> None:
        """_ensure_required_params 之后重算 params_invalid 标记。

        补默认键可能修复/恶化结构，以最终 params 为准（阶段一：
        该标记将被 main_graph 消费——为真时不进执行直接走 correction）。
        """
        _prob = validate_params_structure(
            plan_result.get("action"), plan_result.get("params"))
        if _prob:
            plan_result["params_invalid"] = True
            plan_result["params_invalid_reason"] = _prob
        else:
            plan_result.pop("params_invalid", None)
            plan_result.pop("params_invalid_reason", None)

    def _build_correction_hints(
        self,
        last_error: str,
        last_error_code: str = None,
    ) -> str:
        """按 error_code 优先给修正策略（阶段一协议），字符串匹配兜底。

        code 分支是稳定契约（不依赖文案）；字符串分支兼容期保留，
        覆盖未分类错误（如"文件不存在"）的更具体策略。
        """
        code_hints = {
            "MISSING_PARAM": """
**错误分析**: 缺少必要参数（error_code=MISSING_PARAM）。
**修正策略**: 对照该 Skill 的参数要求补齐所有必填参数；file_operations 必须明确 path（或批量 files[]/edits[]）。
""",
            "INVALID_TYPE": """
**错误分析**: 参数结构类型错误（error_code=INVALID_TYPE），params 必须是 JSON 对象。
**修正策略**: 重新输出规范 JSON：参数行只放 {"key": "value"} 对象，不要混入代码或说明文字。
""",
            "UNKNOWN_KEY": """
**错误分析**: 参数含未知键（error_code=UNKNOWN_KEY）。
**修正策略**: 只保留 Skill 参数表中列出的键，删除多余键后重发。
""",
            "TRUNCATED_JSON": """
**错误分析**: 输出被截断导致 JSON 残缺（error_code=TRUNCATED_JSON）。
**修正策略**: 缩小单次参数体积（批量 ≤4 文件、总内容 ≤6000 字），超出拆成多次调用。
""",
            "PATH_ESCAPE": """
**错误分析**: 路径逃逸出任务目录（error_code=PATH_ESCAPE）。
**修正策略**: path 只写任务目录内的相对路径（如 src/App.vue），禁止绝对路径或 ../ 上跳。
""",
            "TIMEOUT": """
**错误分析**: 上一步执行超时（error_code=TIMEOUT）。
**修正策略**: 缩小操作范围或拆分为更小步骤重试；避免单次处理过大文件/过多文件。
""",
            "UNKNOWN_SKILL": """
**错误分析**: 技能未注册（error_code=UNKNOWN_SKILL）。
**修正策略**: 只能使用"可用工具"列表中的动作名，改选有效技能。
""",
            "CONSECUTIVE_FAILURE": """
**错误分析**: 工具连续失败已被熔断（error_code=CONSECUTIVE_FAILURE）。
**修正策略**: 不要原样重试——换一种达成方式（不同工具/不同参数形态）；
仍无法推进时向用户报告障碍并说明已尝试的方案。
""",
            "RISK_DENIED": """
**错误分析**: 当前审批模式禁止该风险级工具（error_code=RISK_DENIED）。
**修正策略**: 换用只读/低风险方式完成；确需写/执行/联网时向用户说明并请求授权。
""",
            "AMBIGUOUS_SIDE_EFFECT": """
**错误分析**: 该操作在上次崩溃前已发起，是否生效无法确认（error_code=AMBIGUOUS_SIDE_EFFECT）。
**修正策略**: 禁止原样重发——先核验：用 read/search_files 查文件是否已变、查接口/命令产出；
确认已生效就直接推进下一步，确认未生效再重做。
""",
        }
        if last_error_code in code_hints:
            return code_hints[last_error_code]

        # 字符串兜底（兼容期保留；优先于通用 EXEC_FAILED 分支）
        if "文件不存在" in last_error:
            return """
**错误分析**: 文件不存在，说明需要先创建文件。
**修正策略**: 使用 file_operations 的 operation='write' 创建文件（会自动创建父目录），然后再读取或编辑。
"""
        if "缺少 path 参数" in last_error:
            return """
**错误分析**: 缺少必要的 path 参数。
**修正策略**: 必须在 params 中明确指定 path 参数，例如: {"path": "app.py", "content": "..."}
"""
        if "缺少" in last_error and "参数" in last_error:
            return """
**错误分析**: 缺少必要参数。
**修正策略**: 检查 Skill 的参数要求，确保所有必需参数都已提供。
"""
        if last_error_code == "EXEC_FAILED":
            return """
**错误分析**: 上一步执行异常（error_code=EXEC_FAILED）。
**修正策略**: 分析错误信息调整参数或更换技能重试；连续失败请换一种达成方式。
"""
        return ""

    def _ensure_required_params(
        self,
        action: str,
        params: Dict[str, Any],
        todo: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        确保必要参数存在，必要时从 session 查询或设置默认值

        注意：
        - 不生成带时间戳的临时 project_name，避免与 file_operations skill 中的
          命名规范不一致
        - task_path 由 main_graph._ensure_task_path 统一处理
        """
        params = params.copy() if params else {}

        if action == "file_operations":
            if "operation" not in params:
                params["operation"] = "write"

        elif action == "http_client":
            if "url" not in params:
                params["url"] = ""
            if "method" not in params:
                params["method"] = "GET"

        elif action == "code_generator":
            if "requirements" not in params and "language" not in params:
                params["requirements"] = todo.get("title", "生成代码")

        elif action == "general_response":
            # 兼容历史 message 别名：技能只认 input，缺了必报"缺少 input 参数"
            # （降级路径与模型惯用 message 键），有 message 时桥接过去
            if "input" not in params and params.get("message"):
                params["input"] = params["message"]

        return params

    def _parse_planning_response(self, content: str, todo: Dict[str, Any]) -> Dict[str, Any]:
        """解析 Planning 阶段的响应"""
        result = {
            "action": todo.get("action") or "general_response",
            "params": todo.get("params", {}),
            "reason": ""
        }

        # 解析动作
        action_match = re.search(r'动作[:：]\s*(\w+)', content)
        if action_match:
            result["action"] = action_match.group(1)

        # 解析参数
        # 使用非贪心匹配，只取到第一个代码块结束或行尾，防止 JSON 后的 content 混入
        params_match = re.search(r'参数[:：]\s*(.+?)(?:\n```|\n原因:|$)', content, re.DOTALL)
        if params_match:
            params_str = params_match.group(1).strip()

            # 1. 尝试解析为 JSON（支持 {"key": "value"} 格式）
            parsed = self._extract_json(params_str)
            if parsed is not None:
                if isinstance(parsed, dict):
                    result["params"] = parsed
                else:
                    result["params"] = {"value": parsed}
            else:
                # 2. 尝试解析为 key-value 格式 (key: value 或 key=value)
                parsed_params = self._parse_key_value_params(params_str)
                if parsed_params:
                    result["params"] = parsed_params
                else:
                    # 3. 降级：保留原始字符串（仅在无法解析时）
                    result["params"] = {"raw": params_str}

        # 解析原因
        reason_match = re.search(r'原因[:：]\s*(.+)', content)
        if reason_match:
            result["reason"] = reason_match.group(1).strip()

        # 解析目标文件（本待办应产出/修改的文件清单，供"文件未生成=禁止完成"核对）
        result["target_files"] = []
        tf_match = re.search(r'目标文件[:：]\s*(.+)', content)
        if tf_match:
            raw = tf_match.group(1).strip()
            if raw and not re.match(r'^(无|none|None|-)$', raw, re.I):
                result["target_files"] = [
                    p.strip().strip('`"\'')
                    for p in re.split(r'[,，、;；\s]+', raw)
                    if p.strip()
                ]

        # 参数结构崩坏防线（TC-S16-04）：缺目标参数的计划标记不放行，
        # 执行层 loader.execute 同样拦截并回注全量 schema+调用须知
        _prob = validate_params_structure(result["action"], result["params"])
        if _prob:
            result["params_invalid"] = True
            result["params_invalid_reason"] = _prob

        return result

    def _extract_json(self, text: str) -> Optional[Any]:
        """
        从文本中提取 JSON 对象/数组，支持不规范的 LLM 输出。

        处理以下常见问题：
        - JSON 后紧跟换行、原因说明等非 JSON 内容
        - JSON 末尾有多余逗号
        - JSON 包含尾随注释
        """
        if not text:
            return None

        text = text.strip()

        # 找到 JSON 开始位置
        json_start = text.find('{')
        if json_start < 0:
            json_start = text.find('[')
            if json_start < 0:
                return None

        json_candidate = text[json_start:]

        # 尝试直接解析
        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError:
            pass

        # 策略1：截取到第一个有效的 JSON 结束位置（处理尾部混入内容）
        depth = 0
        in_string = False
        escape_next = False
        end_pos = -1

        for i, ch in enumerate(json_candidate):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue

            if ch == '{' or ch == '[':
                depth += 1
            elif ch == '}' or ch == ']':
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break

        if end_pos > 0:
            json_str = json_candidate[:end_pos]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # 策略2：移除多余逗号（如 "key": "value", } 或 "key": "value", ]）
        cleaned = re.sub(r',\s*([}\]])', r'\1', json_candidate)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 策略3：移除尾随注释（// 或 /* ... */）
        cleaned = re.sub(r'//.*', '', cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        return None

    def _parse_key_value_params(self, params_str: str) -> Dict[str, Any]:
        """
        解析 key-value 格式的参数

        支持格式:
        - path: ./flask_blog
        - path=./flask_blog
        - url: xxx, method: GET
        """
        result = {}

        # 匹配 key: value 或 key=value 格式
        # 支持逗号分隔的多个参数
        pairs = re.split(r'[,\n]', params_str)
        for pair in pairs:
            pair = pair.strip()
            if not pair:
                continue

            # 尝试 key: value 格式
            match = re.match(r'^(\w+)\s*[:=]\s*(.+)$', pair)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip()
                result[key] = value

        # 检测异常情况：如果值中包含换行符或 Python 代码特征，说明解析错误
        for key, value in list(result.items()):
            if '\n' in str(value) or 'def ' in str(value) or 'class ' in str(value) or 'db.Column' in str(value):
                logger.warning(f"[Planner] 检测到异常的参数解析结果: {key}={str(value)[:100]}...")
                # 这种情况下，整个 params_str 可能是被错误解析的 content
                # 返回空 dict 让调用方重试
                return {}

        return result

    async def missing_required_files(self, task: str, existing_files: list) -> list:
        """任务级 LLM 核对：已生成文件是否覆盖任务必需的产出（用户硬规则 2026-11-09）。

        只列"缺失会导致任务无法完成/无法运行"的必需文件；
        建议性文件（README、注释、额外功能）一律不列。
        返回相对路径列表，无缺失返回空表。
        """
        existing = "\n".join(existing_files) if existing_files else "（空）"
        prompt = f"""任务原文：
{task}

已生成文件：
{existing}

判断：上面的文件是否覆盖了任务要求的必需产出？只列"缺失会导致任务无法完成或无法运行"的文件路径（相对路径，含扩展名）。
- 不要列建议性/锦上添花的文件（如 README.md、注释文件、额外功能文件）
- 不要列目录
- 已生成的文件不要重复列
- 只输出真实文件的相对路径（文件名必须带扩展名）；模块名、类名、变量名、函数名、配置键不是文件，即使带点号也不是文件路径
没有缺失则只输出：无"""
        try:
            content = await self._llm_chat(messages=[{"role": "user", "content": prompt}], max_tokens=500)
        except Exception as e:
            logger.warning(f"[Planner] 必需文件核对 LLM 失败(忽略): {e}")
            return []
        if not content:
            return []
        out = []
        for line in str(content).splitlines():
            line = line.strip().strip("-*·`").strip()
            if not line or line in ("无", "none", "None", "没有", "无缺失", "没有缺失"):
                continue
            # 扩展名必须小写且 1-4 位：否则 "datetime.datetime" 这类导入路径会被当成文件
            m = re.search(r"([A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-]+)*\.[a-z][a-z0-9]{0,3})(?![A-Za-z0-9])", line)
            if m:
                out.append(m.group(1))
        return out[:10]

    async def observe(
        self,
        task: str,
        todo: Dict[str, Any],
        action: str,
        params: Dict[str, Any],
        result: Dict[str, Any],
        extra_context: str = "",
    ) -> Dict[str, Any]:
        """
        Observation 阶段：验证执行结果

        Args:
            task: 用户任务
            todo: 当前待办项
            action: 执行的动作
            params: 执行参数
            result: 执行结果
            extra_context: 本待办的思考与计划文本（用于提取"提到的文件"清单）

        Returns:
            观察结果 {completed, reason, suggestion, success, files_mentioned}
        """
        # 如果工具执行本身失败了，直接返回未完成，不依赖 LLM 判断
        if not result.get("success", False):
            error_msg = result.get("error", "未知错误")
            logger.warning(f"[Planner] 工具执行失败，跳过 LLM 观察: {error_msg}")
            return {
                "completed": False,
                "reason": f"工具执行失败: {error_msg}",
                "suggestion": "调整参数重试",
                "success": False,
                "files_mentioned": [],
            }

        prompt = OBSERVATION_PROMPT.format(
            task=task,
            todo_id=todo.get("id", 0),
            title=todo.get("title", ""),
            action=action,
            params=str(params),
            result=str(result),
            extra_context=(extra_context or "（无）")[:3000],
        )

        try:
            response = await self._llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="quality",
                temperature=0.3,
                max_tokens=700,
            )

            content = response.content.strip()
            llm_result = self._parse_observation_response(content)
            # 即使 LLM 说"已完成"，如果工具返回了数据为空，也要降级
            return llm_result

        except asyncio.CancelledError:
            raise  # 传播取消信号，不吞掉
        except Exception as e:
            logger.warning(f"[Planner] Observation 阶段失败: {e}")
            # 降级：根据成功状态判断
            return {
                "completed": result.get("success", False),
                "reason": f"观察完成（LLM 调用失败: {e}）",
                "suggestion": "继续" if result.get("success") else "调整",
                "success": result.get("success", False),
                "files_mentioned": [],
            }

    def _parse_observation_response(self, content: str) -> Dict[str, Any]:
        """解析 Observation 阶段的响应"""
        result = {
            "completed": False,
            "reason": "无法判断",
            "suggestion": "继续",
            "success": False,
            "files_mentioned": [],
        }

        # 解析完成状态（只认"完成状态:"所在行——原因文本里常出现"已完成/未完成"
        # 字样，按全文子串判定会把"未完成 + 原因含已完成"误判成完成，生产实测假完成根因之一）
        status_match = re.search(r'^完成状态[:：]\s*(.+)$', content, re.MULTILINE)
        status_text = status_match.group(1) if status_match else content
        if "未完成" in status_text:
            result["completed"] = False
            result["success"] = False
        elif "部分完成" in status_text:
            result["completed"] = True  # 部分完成也视为完成，避免过度严格
            result["success"] = True
        elif "已完成" in status_text:
            result["completed"] = True
            result["success"] = True

        # 解析原因
        reason_match = re.search(r'原因[:：]\s*(.+)', content)
        if reason_match:
            result["reason"] = reason_match.group(1).strip()

        # 解析建议
        suggestion_match = re.search(r'建议[:：]\s*(.+)', content)
        if suggestion_match:
            result["suggestion"] = suggestion_match.group(1).strip()

        # 解析"提到的文件"清单（本待办过程中提到、应当存在的文件）
        files_match = re.search(r'^文件[:：]\s*(.+)$', content, re.MULTILINE)
        if files_match:
            raw = files_match.group(1).strip()
            if raw and raw not in ("无", "none", "None", "-"):
                result["files_mentioned"] = [
                    f.strip().strip('`"\'') for f in re.split(r'[,，、;；\s]+', raw) if f.strip()
                ]

        return result

    async def analyze_plan(self, task: str, plan: List[Dict[str, Any]]) -> str:
        """
        对执行计划中的每个步骤进行深入分析

        Args:
            task: 用户任务描述
            plan: 执行计划列表

        Returns:
            每个步骤的分析描述
        """
        if not plan:
            return ""

        logger.info(f"[Planner] 分析计划，包含 {len(plan)} 个步骤")

        # 将计划转为可读格式
        plan_str = "\n".join([
            f"  步骤 {p.get('step', i+1)}: [{p.get('action')}] {p.get('description', '')}"
            for i, p in enumerate(plan)
        ])

        prompt = PLAN_ANALYSIS_PROMPT.format(
            task=task,
            plan=plan_str
        )

        try:
            response = await self._llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="quality",
                temperature=0.3,
                max_tokens=1500,
            )
            return response.content.strip()
        except asyncio.CancelledError:
            raise  # 传播取消信号，不吞掉
        except Exception as e:
            logger.warning(f"[Planner] 计划分析失败: {e}")
            # 降级：返回简单描述
            return self._generate_simple_analysis(plan)

    async def _create_plan_with_llm(self, task: str, intent: str) -> Optional[List[Dict[str, Any]]]:
        """使用 LLM 生成执行计划"""
        # 规划早期（todos 未建）→ 只读集（阶段四白名单）
        skill_list = self._get_skill_list_str(stage="plan")

        # 尝试检索相似经验（如果有经验库）
        similar_experiences = await self._retrieve_similar_experiences(task)
        experience_context = ""
        if similar_experiences:
            experience_context = f"\n\n## 参考经验（可借鉴）：\n{similar_experiences}"

        prompt = f"{self.PLANNING_PROMPT.format(skill_list=skill_list)}\n\n用户任务: {task}\n检测到的意图: {intent}{experience_context}"

        response = await self._llm_chat(
            messages=[{"role": "user", "content": prompt}],
            model=None,
            strategy="quality",  # 规划需要高质量
            temperature=0.3,
            max_tokens=1500,
        )

        content = response.content.strip()
        return self._parse_plan(content, task, intent)

    def _create_heuristic_plan(self, task: str, intent: str) -> List[Dict[str, Any]]:
        """基于意图的启发式规划（降级方案）"""
        base_actions = self._fallback_intents.get(intent, ["general_response"])

        plan = []
        for i, action in enumerate(base_actions):
            plan.append({
                "step": i + 1,
                "action": action,
                "params": self._generate_params_for_action(action, task),
                "description": self._get_action_description(action),
                "parallel": False,
                "depends_on": [i] if i > 0 else [],
            })

        return plan

    def _generate_params_for_action(self, action: str, task: str) -> Dict[str, Any]:
        """为 Skill 生成参数"""
        if action == "http_client":
            # 尝试从任务中提取 URL
            url_match = re.search(r'https?://[^\s]+', task)
            return {
                "url": url_match.group() if url_match else "",
                "method": "GET",
            }
        elif action == "code_generator":
            # 尝试从任务中提取语言信息
            lang_map = {
                "python": ["python", "Python", ".py"],
                "javascript": ["javascript", "js", "JavaScript", "JS"],
                "typescript": ["typescript", "ts", "TypeScript"],
                "go": ["golang", "go ", "Go "],
                "rust": ["rust", "Rust"],
            }
            for lang, keywords in lang_map.items():
                if any(k in task for k in keywords):
                    return {"language": lang, "requirements": task}
            return {"requirements": task}
        elif action == "notification":
            return {"content": task}
        elif action == "search":
            # 提取搜索关键词
            query = re.sub(r'搜索|查找|找一下', '', task)
            return {"query": query.strip(), "limit": 10}
        else:
            return {"input": task}

    def _get_action_description(self, action: str) -> str:
        """获取 Skill 描述"""
        descriptions = {
            "http_client": "发起 HTTP 请求获取数据",
            "code_generator": "生成代码",
            "data_processor": "处理和转换数据",
            "file_operations": "执行文件操作",
            "notification": "发送通知消息",
            "search": "搜索相关信息",
            "general_response": "生成通用响应",
        }
        return descriptions.get(action, "执行操作")

    async def _retrieve_similar_experiences(self, task: str) -> Optional[str]:
        """从经验库检索相似经验（预留接口）"""
        # TODO: 后续集成经验库
        # from app.agent.experience.retriever import ExperienceRetriever
        # retriever = ExperienceRetriever()
        # experiences = await retriever.retrieve(task, top_k=2)
        # ...
        return None

    def _parse_plan(self, content: str, task: str, intent: str) -> Optional[List[Dict[str, Any]]]:
        """解析 LLM 返回的计划"""
        # 尝试直接解析 JSON
        try:
            plan = json.loads(content)
            if isinstance(plan, list) and len(plan) > 0:
                return self._validate_and_normalize_plan(plan)
        except json.JSONDecodeError:
            pass

        # 尝试从文本中提取 JSON
        json_match = re.search(r'\[[\s\S]*\]', content)
        if json_match:
            try:
                plan = json.loads(json_match.group())
                if isinstance(plan, list) and len(plan) > 0:
                    return self._validate_and_normalize_plan(plan)
            except json.JSONDecodeError:
                pass

        # 解析失败，返回 None 触发降级
        logger.warning(f"[Planner] 无法解析 LLM 计划，触发降级")
        return None

    def _validate_and_normalize_plan(self, plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """验证并标准化计划"""
        valid_actions = set(AVAILABLE_SKILLS.keys())
        validated_plan = []

        for item in plan:
            # 验证 action 是否有效
            action = item.get("action")
            if action not in valid_actions:
                logger.warning(f"[Planner] 跳过无效 action: {action}")
                continue

            validated_plan.append({
                "step": len(validated_plan) + 1,
                "action": action,
                "params": item.get("params", {}),
                "description": item.get("description", ""),
                "parallel": bool(item.get("parallel", False)),
                "depends_on": [int(d) for d in item.get("depends_on", []) if isinstance(d, int)],
            })

        return validated_plan

    async def refine_plan(
        self,
        plan: List[Dict[str, Any]],
        feedback: str
    ) -> List[Dict[str, Any]]:
        """
        根据反馈优化计划

        Args:
            plan: 当前执行计划
            feedback: 用户反馈或错误信息

        Returns:
            优化后的计划
        """
        logger.info(f"[Planner] 根据反馈优化计划: {feedback[:100]}...")

        if self._use_llm:
            try:
                # 将计划转为字符串
                plan_str = json.dumps(plan, ensure_ascii=False, indent=2)

                prompt = self.REFINE_PROMPT.format(
                    current_plan=plan_str,
                    feedback=feedback
                )

                response = await self._llm_chat(
                    messages=[{"role": "user", "content": prompt}],
                    model=None,
                    strategy="quality",
                    temperature=0.3,
                    max_tokens=1500,
                )

                optimized = self._parse_plan(response.content, "", "")
                if optimized:
                    logger.info(f"[Planner] LLM 优化计划完成，包含 {len(optimized)} 个步骤")
                    return optimized
            except Exception as e:
                logger.warning(f"[Planner] LLM 优化失败: {e}")

        # 降级：简单调整计划
        return self._simple_plan_adjustment(plan, feedback)

    def _simple_plan_adjustment(
        self,
        plan: List[Dict[str, Any]],
        feedback: str
    ) -> List[Dict[str, Any]]:
        """简单的计划调整（降级方案）"""
        feedback_lower = feedback.lower()

        # 如果是超时错误，增加超时参数
        if "timeout" in feedback_lower or "超时" in feedback_lower:
            for step in plan:
                if step.get("action") == "http_client":
                    step["params"]["timeout"] = 60

        # 如果是参数错误，简化参数
        if "参数" in feedback_lower or "param" in feedback_lower:
            for step in plan:
                step["params"] = {}

        return plan

    def _generate_simple_analysis(self, plan: List[Dict[str, Any]]) -> str:
        """生成简单的计划分析（降级方案）"""
        analyses = []
        for i, step in enumerate(plan):
            action = step.get("action", "unknown")
            desc = step.get("description", "")
            analyses.append(
                f"**步骤 {i+1}: [{action}]**\n"
                f"- 目的：{desc or '执行指定操作'}\n"
                f"- 策略：调用 {action} 完成此步骤\n"
                f"- 注意：确保参数正确传递"
            )
        return "\n\n".join(analyses)

    def get_available_skills(self) -> Dict[str, Dict[str, Any]]:
        """获取所有可用 Skill"""
        try:
            loader = get_loader()
            schemas = loader.get_schemas()
            return {s["name"]: s for s in schemas}
        except Exception as e:
            logger.warning(f"[Planner] 获取 Skill 列表失败: {e}，使用备用方案")
            return AVAILABLE_SKILLS.copy()

    def get_skill_info(self, action: str) -> Optional[Dict[str, Any]]:
        """获取指定 Skill 的信息"""
        try:
            loader = get_loader()
            metadata = loader.get_metadata(action)
            if metadata:
                return metadata.to_dict()
        except Exception as e:
            logger.warning(f"[Planner] 获取 Skill {action} 信息失败: {e}")
        return AVAILABLE_SKILLS.get(action)

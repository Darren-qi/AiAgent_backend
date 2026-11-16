"""缺失清单同名兜底测试：承诺裸名但文件在子目录时不得误报缺失。

背景（2026-11-13 生产 session_1794546906875）：
read extensions.py（错误路径）失败 → path 进候选 → 精确匹配 app/extensions.py 失败
→ 误报缺失 → 逼模型在根目录写出重复文件。同名文件已在子目录 = 已存在。
"""

from pathlib import Path

from app.agent.graphs.main_graph import _check_promised_files


def test_basename_in_subdir_not_missing(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "extensions.py").write_text("db = None")
    missing = _check_promised_files(["extensions.py"], None, None, tmp_path)
    assert missing == [], f"同名文件在 app/ 下不应报缺失: {missing}"


def test_bare_promised_path_resolves_in_subdir(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "extensions.py").write_text("")
    missing = _check_promised_files(["__init__.py"], {"path": "extensions.py"}, None, tmp_path)
    assert missing == []


def test_truly_missing_still_reported(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "extensions.py").write_text("")
    missing = _check_promised_files(["ghost.py", "app/extensions.py"], None, None, tmp_path)
    assert missing == ["ghost.py"], f"真缺失必须仍报: {missing}"


def test_exact_subdir_path_still_checked(tmp_path: Path):
    """同名文件已在任务目录任何位置即算存在（2026-11-13 新契约）。

    旧契约要求 app/x.py 精确匹配、根下同名 x.py 不算——任务93重构生产
    取证推翻：move 归类后旧路径 app/extensions.py 实际已在 backend/app/，
    精确匹配连续三轮误报"不存在"逼模型重找。用户规则=文件出现在任务目录
    文件结构区即算存在，误报缺失比放过更伤（重复创建+烧轮次）。
    """
    (tmp_path / "x.py").write_text("")
    missing = _check_promised_files(["app/x.py"], None, None, tmp_path)
    assert missing == [], f"同名文件已在结构里不应报缺失: {missing}"


def test_miss_message_puts_task_dir_first():
    """观察缺件文案（2026-11-14 第三次迭代）：句首说本步状态 + 缺件问题，
    不得以待办状态断言开头（用户：过程里总写"待办未完成"易被误读成本步失败）；
    仍带任务目录查找根（2026-11-13：相对路径易被误读成"没带任务目录"）。"""
    from pathlib import Path as _P
    src = (_P(__file__).parent.parent.parent / "app" / "agent" / "graphs" / "main_graph.py").read_text(encoding="utf-8")
    assert "本步操作已成功，但" in src and "对照任务目录 {_tp} 按相对路径检查，以下承诺产出文件尚未创建: " in src, \
        "缺件文案句首必须是本步状态+缺件问题，且带任务目录查找根"
    assert "本待办未完成" not in src, "缺件文案不得再写待办状态断言（2026-11-14：歧义）"
    assert "以下文件在本待办过程中提到但任务目录中不存在" not in src, "旧文案应移除"


def test_slashed_path_found_after_move(tmp_path: Path):
    """归类移动后：旧路径提及（app/extensions.py）在子目录找到 → 不报缺失。"""
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "extensions.py").write_text("")
    missing = _check_promised_files(["app/extensions.py"], None, None, tmp_path)
    assert missing == [], f"已归类到 backend/app/ 不应报缺失: {missing}"

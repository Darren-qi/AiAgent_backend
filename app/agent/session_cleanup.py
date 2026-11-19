"""会话删除级联清理：子表数据 + 磁盘任务目录（tasks/<项目_时间戳>/）。

背景：会话列表删除只删了 sessions 一行，子表（session_files / execution_nodes /
working_memory ...）和磁盘任务目录全部留存 → 越积越多的垃圾。
本模块把「删会话」变成真正的级联删除：

1. 收集该会话的磁盘目录名（删除子表之前必须先收集，否则映射就没了）
   - session_contexts.context_key='task_path'  → "auto_project_xxx"
   - session_files.absolute_path 的 /tasks/ 段 → 兜底（老数据可能没有 context 行）
2. 删子表：动态发现所有带 session_id 列的表（schema 驱动，新表自动覆盖）
3. 删磁盘目录：只允许删 tasks/ 直下子目录，逐条路径校验，防路径穿越

全部 best-effort：任何一步失败只记日志，不影响会话本身的删除。
"""
import json
import logging
import re
import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

# information_schema 查出来的表名只接受这种形状（防拼接注入）
_TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# 会话本身最后删
_PARENT_TABLE = "sessions"


def tasks_base_dir() -> Path:
    """磁盘任务根目录（与 file_operations 写文件同一套路径语义）。"""
    from app.agent.tools.storage.providers.local import LocalStorageProvider

    return LocalStorageProvider().base_path


def _dir_names_from_context_values(values: Iterable) -> set[str]:
    names: set[str] = set()
    for v in values:
        if v is None:
            continue
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except (ValueError, TypeError):
                v = v.strip()
        if isinstance(v, str) and v.strip():
            names.add(v.strip().strip("/").split("/")[-1])
    return names


def _dir_names_from_absolute_paths(paths: Iterable[str | None]) -> set[str]:
    """从 /a/b/tasks/<项目目录>/<文件> 里取 <项目目录>。

    结构规则：tasks/ 后必须还有「目录/文件」两段才算有项目目录——
    `/no/tasks/here.py` 这种直接躺在 tasks 根下的文件没有项目目录，跳过。
    """
    names: set[str] = set()
    for ap in paths:
        if not ap or "/tasks/" not in ap:
            continue
        parts = ap.split("/tasks/", 1)[1].split("/")
        if len(parts) >= 2 and parts[0]:
            names.add(parts[0])
    return {n for n in names if n and n not in (".", "..") and "/" not in n}


def _candidates(dir_names: set[str], recorded_paths: Sequence[str | None]) -> list[Path]:
    """每个目录名 → 候选绝对路径。

    默认用当前 tasks 根；老数据的 absolute_path 可能指向另一个 tasks 目录
    （历史上路径变过），把记录路径里 /tasks/ 的前缀也作为候选，两者都校验。
    """
    base = tasks_base_dir()
    bases = {base}
    for ap in recorded_paths:
        if ap and "/tasks/" in ap:
            prefix = ap.split("/tasks/", 1)[0]
            if prefix:
                bases.add(Path(prefix) / "tasks")
    out: list[Path] = []
    for b in bases:
        for name in dir_names:
            out.append(b / name)
    return out


def safe_task_dir(path: Path) -> bool:
    """只允许删「名字合法、且是某个 tasks/ 目录直下子目录」的路径。"""
    name = path.name
    if not name or name in (".", "..") or "/" in name:
        return False
    try:
        real = path.resolve()
    except OSError:  # pragma: no cover - 极端文件系统错误
        return False
    parent = real.parent
    if parent.name != "tasks":
        return False
    # 目录名必须与传入一致（resolve 之后没有被 symlink 带到别处改名）
    if real.name != name:
        return False
    return True


def remove_task_dirs(dir_names: Iterable[str],
                     recorded_paths: Sequence[str | None] = ()) -> list[str]:
    """删除磁盘任务目录，返回真正删掉的路径字符串（失败只记日志）。"""
    names = {n for n in dir_names if n}
    if not names:
        return []
    removed: list[str] = []
    seen: set[str] = set()
    for cand in _candidates(names, recorded_paths):
        key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        if not safe_task_dir(cand):
            logger.info("[session_cleanup] 跳过非法路径: %s", key)
            continue
        if not cand.is_dir():
            continue
        try:
            shutil.rmtree(cand)
            removed.append(key)
        except OSError as e:  # 权限/被占用
            logger.warning("[session_cleanup] 删除目录失败 %s: %s", key, e)
    return removed


async def collect_session_task_dirs(db, session_id: str) -> tuple[set[str], list[str | None]]:
    """收集会话对应的磁盘目录名与原始 absolute_path（删除子表前调用）。"""
    from sqlalchemy import select

    from app.models.experience import SessionContext, SessionFile

    dir_names: set[str] = set()
    recorded: list[str | None] = []
    try:
        rows = (await db.execute(
            select(SessionContext.context_value).where(
                SessionContext.session_id == session_id,
                SessionContext.context_key == "task_path"))).scalars().all()
        dir_names |= _dir_names_from_context_values(rows)
    except Exception as e:  # noqa: BLE001 - 读不到就走兜底，不影响删除
        logger.warning("[session_cleanup] 读 task_path 失败 %s: %s", session_id, e)
    try:
        paths = (await db.execute(
            select(SessionFile.absolute_path).where(
                SessionFile.session_id == session_id))).scalars().all()
        recorded = list(paths)
        dir_names |= _dir_names_from_absolute_paths(paths)
    except Exception as e:  # noqa: BLE001
        logger.warning("[session_cleanup] 读 session_files 失败 %s: %s", session_id, e)
    return dir_names, recorded


async def delete_session_child_rows(db, session_id: str) -> dict:
    """删掉所有带 session_id 列的表里属于该会话的行（不含 sessions 本身）。

    表清单从 information_schema 动态取（schema 驱动），将来新增的子表自动覆盖。
    """
    from sqlalchemy import text

    result: dict = {}
    rows = (await db.execute(text(
        "select table_name from information_schema.columns "
        "where table_schema = 'public' and column_name = 'session_id'"))).all()
    tables = sorted({r[0] for r in rows if r and _TABLE_NAME_RE.match(str(r[0]))})
    for table in tables:
        if table == _PARENT_TABLE:
            continue
        try:
            res = await db.execute(
                text(f"delete from public.{table} where session_id = :sid"),
                {"sid": session_id})
            if res.rowcount:
                result[table] = res.rowcount
        except Exception as e:  # noqa: BLE001 - 单表失败不阻断会话删除
            logger.warning("[session_cleanup] 删子表 %s 失败: %s", table, e)
    return result


async def _dirs_used_by_other_sessions(db, session_id: str, names: set[str]) -> set[str]:
    """候选目录里有没有被**别的会话**引用的（task_path 是按会话建的，正常不会撞）。

    撞上就跳过：删会话不能把别人还在用的目录删了。
    """
    if not names:
        return set()
    from sqlalchemy import select

    from app.models.experience import SessionContext

    try:
        rows = (await db.execute(
            select(SessionContext.context_value).where(
                SessionContext.context_key == "task_path",
                SessionContext.session_id != session_id))).scalars().all()
    except Exception as e:  # noqa: BLE001 - 读不到就按不共享处理（目录按会话建）
        logger.warning("[session_cleanup] 读其它会话 task_path 失败: %s", e)
        return set()
    others = _dir_names_from_context_values(rows)
    shared = names & others
    if shared:
        logger.info("[session_cleanup] %s 的目录同时被其它会话引用，跳过: %s",
                    session_id, sorted(shared))
    return shared


async def cleanup_session(db, session_id: str, *, delete_parent: bool = False) -> dict:
    """删会话级联清理。返回 {dirs: [...], tables: {表: 行数}, parent: bool}。

    顺序：先收集目录名（映射在子表里）→ 删子表 → （可选）删 sessions 行 → 删磁盘目录。
    磁盘删除放在 DB 之后：DB 失败可回滚重试，磁盘删了就没了。
    """
    dir_names, recorded = await collect_session_task_dirs(db, session_id)
    shared = await _dirs_used_by_other_sessions(db, session_id, dir_names)
    dir_names -= shared
    tables = await delete_session_child_rows(db, session_id)
    parent = False
    if delete_parent:
        from sqlalchemy import text

        res = await db.execute(
            text("delete from public.sessions where session_id = :sid"),
            {"sid": session_id})
        parent = bool(res.rowcount)
    await db.commit()
    dirs = remove_task_dirs(dir_names, recorded)
    if dir_names and not dirs:
        logger.info("[session_cleanup] %s 映射到 %d 个目录但无可删项: %s",
                    session_id, len(dir_names), sorted(dir_names))
    return {"dirs": dirs, "tables": tables, "parent": parent}

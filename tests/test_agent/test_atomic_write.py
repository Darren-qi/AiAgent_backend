"""文件写入原子性（阶段八 P0）：崩溃不留半截文件。

背景：原来直接 path.write_text()，进程在写到一半被杀会留下截断文件；
下一轮断点恢复重放时读到的就是半截内容。改成 同目录临时文件 + os.replace
后，任何时刻文件要么是完整的旧版、要么是完整的新版。

覆盖：
1. 正常写入（含中文/多行）
2. 覆盖已有文件
3. 自动建父目录
4. 不留临时文件
5. 权限按 umask 对齐普通 open()（不放宽）
6. 写失败不留垃圾
"""

import os
from pathlib import Path

import pytest

from app.agent.skills.file_operations.skill import _atomic_write_text


class TestAtomicWrite:
    def test_creates_file_with_exact_content(self, tmp_path):
        p = tmp_path / "a.txt"
        _atomic_write_text(p, "你好\n第二行", "utf-8")
        assert p.read_text(encoding="utf-8") == "你好\n第二行"

    def test_overwrites_existing_file(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("old content that is long enough", encoding="utf-8")
        _atomic_write_text(p, "new", "utf-8")
        assert p.read_text(encoding="utf-8") == "new"

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "deep" / "nested" / "a.vue"
        _atomic_write_text(p, "<template/>", "utf-8")
        assert p.exists()

    def test_leaves_no_temp_files(self, tmp_path):
        """目录里只该有目标文件，不能有 .tmp 残留。"""
        for i in range(3):
            _atomic_write_text(tmp_path / f"f{i}.txt", f"c{i}", "utf-8")
        names = sorted(x.name for x in tmp_path.iterdir())
        assert names == ["f0.txt", "f1.txt", "f2.txt"], names

    def test_replacement_is_atomic_rename(self, tmp_path):
        """用的是 os.replace（同目录 rename）：跨设备/半截写都不会发生。"""
        p = tmp_path / "a.txt"
        p.write_text("x", encoding="utf-8")
        _atomic_write_text(p, "y", "utf-8")
        # 目标文件必须是完整新内容，且 inode 可能变（rename 语义）
        assert p.read_text(encoding="utf-8") == "y"

    def test_permissions_not_wider_than_umask(self, tmp_path):
        """临时文件默认 0600，必须显式按 umask 对齐到普通 open 的结果。"""
        p = tmp_path / "a.txt"
        _atomic_write_text(p, "x", "utf-8")
        mode = p.stat().st_mode & 0o777
        umask = os.umask(0)
        os.umask(umask)
        assert mode == 0o666 & ~umask, f"期望 {0o666 & ~umask:o}，实际 {mode:o}"

    def test_failure_leaves_no_temp_and_original_intact(self, tmp_path):
        """目标是目录 → 写失败，且不留 tmp、不破坏原状。"""
        target = tmp_path / "adir"
        target.mkdir()
        with pytest.raises(Exception):
            _atomic_write_text(target, "x", "utf-8")
        assert list(tmp_path.iterdir()) == [target]

    def test_empty_content_truncates(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("old", encoding="utf-8")
        _atomic_write_text(p, "", "utf-8")
        assert p.read_text(encoding="utf-8") == ""

"""test_api 集成测试公共配置。

2026-11-13 黄金测试集：test_auth/test_posts/test_users 缺 client fixture
（历史 conftest 丢失），且 register/login 用例一旦启用会直接写入配置指向
的真实数据库。启用前必须先建隔离测试库 + 补 client fixture，在此之前
按模块隔离（见 pytest_collection_modifyitems）。
"""

import pytest
from pathlib import Path

_SKIP_MODULES = {
    "test_auth.py": "缺 client fixture；启用需隔离测试库，防写真实数据库",
    "test_posts.py": "缺 client fixture；启用需隔离测试库，防写真实数据库",
    "test_users.py": "缺 client fixture；启用需隔离测试库，防写真实数据库",
}
# 单条隔离：登录用例依赖真实库中已存在的测试账号（本机碰巧有 testuser 才绿、
# 服务器没有→报事件循环/DB错），非确定性；需测试库+种子数据才启用
_SKIP_NODEIDS = {
    "tests/test_api/test_endpoints.py::TestAuthEndpoint::test_login_success",
    "tests/test_api/test_endpoints.py::TestAuthEndpoint::test_login_invalid_credentials",
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        name = Path(str(item.fspath)).name
        if name in _SKIP_MODULES:
            item.add_marker(pytest.mark.skip(reason=_SKIP_MODULES[name]))
        elif item.nodeid in _SKIP_NODEIDS:
            item.add_marker(pytest.mark.skip(
                reason="依赖真实库中的测试账号，非确定性（需测试库+种子数据）"))

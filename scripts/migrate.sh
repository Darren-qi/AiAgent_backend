#!/bin/bash
# =============================================
# 数据库迁移脚本
# 使用 Alembic 进行数据库迁移管理
# =============================================

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查环境变量
check_env() {
    if [ ! -f .env ]; then
        echo_warn ".env 文件不存在，复制 .env.example 作为模板"
        if [ -f .env.example ]; then
            cp .env.example .env
            echo_info "请编辑 .env 文件配置数据库连接"
        else
            echo_error ".env.example 也不存在"
            exit 1
        fi
    fi
}

# 创建初始迁移
create_migration() {
    echo_info "创建数据库迁移..."
    alembic revision --autogenerate -m "$1"
}

# 运行迁移
run_migrations() {
    echo_info "运行数据库迁移..."
    alembic upgrade head
}

# 回滚迁移
rollback_migration() {
    echo_info "回滚数据库迁移..."
    alembic downgrade "$1"
}

# 创建数据库
create_db() {
    echo_info "创建数据库..."
    # 从 DATABASE_URL_SYNC 提取数据库名
    DB_NAME=$(echo $DATABASE_URL_SYNC | sed -E 's/.*\/(.+)$/\1/' | sed 's/\?.*//')
    psql "$DATABASE_URL_SYNC" -c "CREATE DATABASE $DB_NAME;" 2>/dev/null || true
}

# 主菜单
show_menu() {
    echo ""
    echo "========================================"
    echo "  数据库迁移管理脚本"
    echo "========================================"
    echo "  1. 检查环境"
    echo "  2. 创建数据库"
    echo "  3. 创建新迁移"
    echo "  4. 运行所有迁移"
    echo "  5. 回滚最近一次迁移"
    echo "  6. 回滚到指定版本"
    echo "  7. 显示迁移状态"
    echo "  0. 退出"
    echo "========================================"
    echo ""
}

# 主程序
main() {
    # 加载环境变量
    if [ -f .env ]; then
        set -a
        source .env
        set +a
    fi

    show_menu

    while true; do
        read -p "请选择操作 [0-7]: " choice
        case $choice in
            1)
                check_env
                ;;
            2)
                create_db
                ;;
            3)
                read -p "请输入迁移说明: " message
                create_migration "$message"
                ;;
            4)
                run_migrations
                ;;
            5)
                rollback_migration "-1"
                ;;
            6)
                read -p "请输入目标版本 (如: abc123): " version
                rollback_migration "$version"
                ;;
            7)
                alembic current
                alembic history
                ;;
            0)
                echo_info "再见!"
                exit 0
                ;;
            *)
                echo_error "无效的选择"
                ;;
        esac
    done
}

main

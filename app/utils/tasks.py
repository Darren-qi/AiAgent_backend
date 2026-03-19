"""
Celery 任务模块

定义后台异步任务，支持：
- 发送邮件
- 数据处理
- 定时任务

需要安装 Celery 和 Redis: pip install celery
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings


# 获取配置
settings = get_settings()

# 创建 Celery 应用
celery_app = Celery(
    "ai_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.utils.tasks"],
)

# Celery 配置
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # 任务结果过期时间
    result_expires=3600,
    # 任务重试配置
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # 限流配置
    task_annotations={
        "app.utils.tasks.send_email_task": {"rate_limit": "100/m"},
    },
)

# =============================================
# Beat 调度器配置（定时任务）
# =============================================

celery_app.conf.beat_schedule = {
    # 每天凌晨清理过期数据
    "cleanup-expired-data-daily": {
        "task": "app.utils.tasks.cleanup_expired_data",
        "schedule": crontab(hour=3, minute=0),  # 每天 3:00 执行
    },
    # 每周一生成报告
    "generate-weekly-report": {
        "task": "app.utils.tasks.generate_weekly_report",
        "schedule": crontab(day_of_week=1, hour=9, minute=0),  # 每周一 9:00 执行
    },
}


# =============================================
# 任务定义
# =============================================

@celery_app.task(bind=True, max_retries=3)
def send_email_task(
    self,
    to_email: str,
    subject: str,
    body: str,
    html: str = None,
) -> dict:
    """
    发送邮件任务

    Args:
        to_email: 收件人邮箱
        subject: 邮件主题
        body: 邮件正文（纯文本）
        html: 邮件正文（HTML，可选）

    Returns:
        发送结果
    """
    # TODO: 实现实际的邮件发送逻辑
    # 推荐使用 aiosmtplib 或邮件服务 API（如 SendGrid、Mailgun）
    pass


@celery_app.task(bind=True)
def process_uploaded_file(
    self,
    file_id: str,
    file_path: str,
    user_id: int,
) -> dict:
    """
    处理上传的文件

    Args:
        file_id: 文件 ID
        file_path: 文件路径
        user_id: 用户 ID

    Returns:
        处理结果
    """
    # TODO: 实现文件处理逻辑
    # - 验证文件格式
    # - 转换格式
    # - 生成缩略图
    # - 存储到云存储
    pass


@celery_app.task(bind=True)
def cleanup_expired_data(self) -> dict:
    """
    清理过期数据

    定期执行，清理：
    - 过期的验证码
    - 未验证的账户
    - 临时文件
    """
    # TODO: 实现清理逻辑
    pass


@celery_app.task(bind=True)
def generate_weekly_report(self) -> dict:
    """
    生成周报

    统计：
    - 新增用户数
    - 活跃用户数
    - 文章发布数
    - 系统健康状态
    """
    # TODO: 实现报告生成逻辑
    pass


@celery_app.task(bind=True, rate_limit="10/m")
def sync_external_data(
    self,
    source: str,
    data_type: str,
) -> dict:
    """
    同步外部数据

    Args:
        source: 数据源标识
        data_type: 数据类型

    Returns:
        同步结果
    """
    # TODO: 实现外部数据同步逻辑
    pass


@celery_app.task(bind=True)
def batch_process_items(
    self,
    items: list,
    operation: str,
) -> dict:
    """
    批量处理项目

    Args:
        items: 项目列表
        operation: 操作类型

    Returns:
        处理结果统计
    """
    # TODO: 实现批量处理逻辑
    # - 支持分批处理
    # - 错误处理和重试
    # - 进度回调
    pass


# =============================================
# 任务调用便捷函数
# =============================================

def schedule_email(
    to_email: str,
    subject: str,
    body: str,
    delay: int = 0,
    html: str = None,
) -> celery_app.AsyncResult:
    """
    调度邮件发送任务

    Args:
        to_email: 收件人邮箱
        subject: 邮件主题
        body: 邮件正文
        delay: 延迟秒数
        html: HTML 正文

    Returns:
        异步结果对象
    """
    return send_email_task.apply_async(
        args=[to_email, subject, body],
        kwargs={"html": html},
        countdown=delay,
    )


def schedule_cleanup() -> celery_app.AsyncResult:
    """立即调度清理任务"""
    return cleanup_expired_data.apply_async()


def schedule_report() -> celery_app.AsyncResult:
    """立即调度报告生成任务"""
    return generate_weekly_report.apply_async()

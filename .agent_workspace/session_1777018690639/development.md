### 第一批：创建项目目录和配置文件

```
project_create("a_stock_data_fetcher")
file_write(path="requirements.txt", content="fastapi==0.104.1\nuvicorn==0.24.0\nakshare==1.11.7\nopenpyxl==3.1.2\npandas==2.1.3\nhttpx==0.25.2")
file_write(path="README.md", content="# A股实时行情数据获取工具\n\n## 功能\n- 获取上证指数、深证成指、创业板指三大指数实时行情\n- 获取沪深300指数成分股实时行情\n- 输出为格式化的Excel文件并提供下载\n\n## 启动方式\n```bash\npip install -r requirements.txt\npython main.py\n```\n启动后访问 http://localhost:8000/docs 查看Swagger文档\n\n## API接口\n- `GET /api/stock-data` - 获取行情数据并下载Excel文件\n\n## 依赖\n- Python 3.10+\n- FastAPI + Uvicorn\n- akshare (开源A股数据接口)\n- openpyxl (Excel生成)\n- pandas (数据处理)")
file_write(path="main.py", content='''"""
A股实时行情数据获取工具
- 获取上证指数、深证成指、创业板指三大指数实时行情
- 获取沪深300成分股实时行情
- 输出为格式化的Excel文件并提供下载

启动方式: uvicorn main:app --reload --host 0.0.0.0 --port 8000
或直接运行: python main.py
"""

import asyncio
import io
import logging
import os
import tempfile
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import akshare as ak
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side, numbers
from openpyxl.utils import get_column_letter

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="A股实时行情数据获取",
    description="获取上证指数、深证成指、创业板指和沪深300成分股实时行情，输出Excel并提供下载",
    version="1.0.0",
)


def get_index_real_time() -> List[Dict]:
    """获取三大指数实时行情
    
    Returns:
        list: 包含指数代码、名称、最新价、涨跌幅、涨跌额、成交量等信息的字典列表
    """
    try:
        # 使用akshare获取实时指数行情
        df = ak.stock_zh_index_spot_em()
        # 筛选三大指数
        index_codes = {
            "上证指数": "sh000001",
            "深证成指": "sz399001",
            "创业板指": "sz399006",
        }
        result = []
        for name, code in index_codes.items():
            row = df[df["代码"] == code]
            if not row.empty:
                row = row.iloc[0]
                result.append({
                    "指数名称": name,
                    "指数代码": code,
                    "最新价": float(row.get("最新价", 0)),
                    "涨跌幅(%)": float(row.get("涨跌幅", 0)),
                    "涨跌额": float(row.get("涨跌额", 0)),
                    "成交量(手)": int(row.get("成交量", 0)),
                    "成交额(元)": float(row.get("成交额", 0)),
                    "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
            else:
                logger.warning(f"未找到指数数据: {name} ({code})")
        return result
    except Exception as e:
        logger.error(f"获取指数行情失败: {e}")
        raise


def get_hs300_components() -> List[Dict]:
    """获取沪深300成分股实时行情
    
    Returns:
        list: 包含股票代码、名称、最新价、涨跌幅等信息的字典列表
    """
    try:
        # 获取沪深300成分股实时行情
        df = ak.stock_zh_spot_em(symbol="沪深300")
        if df.empty:
            logger.warning("沪深300成分股数据为空")
            return []
        
        # 选择需要的列并重命名
        columns_map = {
            "代码": "股票代码",
            "名称": "股票名称",
            "最新价": "最新价",
            "涨跌幅": "涨跌幅(%)",
            "涨跌额": "涨跌额",
            "成交量": "成交量(手)",
            "成交额": "成交额(元)",
            "振幅": "振幅(%)",
            "最高": "最高价",
            "最低": "最低价",
            "今开": "今开",
            "昨收": "昨收",
            "量比": "量比",
            "换手率": "换手率(%)",
            "市盈率-动态": "市盈率(动态)",
            "市净率": "市净率",
        }
        
        result = []
        for _, row in df.iterrows():
            item = {}
            for col, new_col in columns_map.items():
                if col in row:
                    val = row[col]
                    # 处理NaN值
                    if pd.isna(val):
                        val = None
                    elif isinstance(val, (float, int)):
                        val = float(val)
                    item[new_col] = val
                else:
                    item[new_col] = None
            item["更新时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result.append(item)
        
        return result
    except Exception as e:
        logger.error(f"获取沪深300成分股行情失败: {e}")
        raise


def create_excel(
    index_data: List[Dict], hs300_data: List[Dict]
) -> bytes:
    """生成格式化的Excel文件
    
    Args:
        index_data: 指数行情数据
        hs300_data: 沪深300成分股行情数据
        
    Returns:
        bytes: Excel文件字节流
    """
    wb = Workbook()
    
    # ========== 样式定义 ==========
    # 标题样式
    title_font = Font(name="微软雅黑", size=16, bold=True, color="FFFFFF")
    title_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    title_alignment = Alignment(horizontal="center", vertical="center")
    
    # 表头样式
    header_font = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    
    # 数据样式
    data_font = Font(name="微软雅黑", size=10)
    data_alignment = Alignment(horizontal="center", vertical="center")
    
    # 涨跌颜色
    up_font = Font(name="微软雅黑", size=10, color="FF0000")  # 红色
    down_font = Font(name="微软雅黑", size=10, color="00B050")  # 绿色
    
    # 边框样式
    thin_border = Border(
        left=Side(style="thin", color="D9E2F3"),
        right=Side(style="thin", color="D9E2F3"),
        top=Side(style="thin", color="D9E2F3"),
        bottom=Side(style="thin", color="D9E2F3"),
    )
    
    # 交替行颜色
    even_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    odd_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    
    # ========== Sheet1: 三大指数 ==========
    ws1 = wb.active
    ws1.title = "三大指数实时行情"
    
    # 标题行
    ws1.merge_cells("A1:G1")
    ws1["A1"] = "A股三大指数实时行情"
    ws1["A1"].font = title_font
    ws1["A1"].fill = title_fill
    ws1["A1"].alignment = title_alignment
    ws1.row_dimensions[1].height = 40
    
    # 表头
    index_headers = ["指数名称", "指数代码", "最新价", "涨跌幅(%)", "涨跌额", "成交量(手)", "成交额(元)"]
    for col, header in enumerate(index_headers, 1):
        cell = ws1.cell(row=2, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
    ws1.row_dimensions[2].height = 30
    
    # 数据行
    for row_idx, item in enumerate(index_data, 3):
        values = [
            item.get("指数名称", ""),
            item.get("指数代码", ""),
            item.get("最新价", 0),
            item.get("涨跌幅(%)", 0),
            item.get("涨跌额", 0),
            item.get("成交量(手)", 0),
            item.get("成交额(元)", 0),
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws1.cell(row=row_idx, column=col_idx, value=val)
            cell.font = data_font
            cell.alignment = data_alignment
            cell.border = thin_border
            # 交替行背景
            if row_idx % 2 == 0:
                cell.fill = even_fill
            else:
                cell.fill = odd_fill
            # 涨跌幅特殊颜色
            if col_idx == 4:  # 涨跌幅列
                if val is not None and val > 0:
                    cell.font = up_font
                elif val is not None and val < 0:
                    cell.font = down_font
            # 涨跌额特殊颜色
            if col_idx == 5:
                if val is not None and val > 0:
                    cell.font = up_font
                elif val is not None and val < 0:
                    cell.font = down_font
            # 数字格式
            if col_idx in [3, 4, 5]:  # 最新价、涨跌幅、涨跌额
                cell.number_format = "#,##0.00"
            elif col_idx in [6, 7]:  # 成交量、成交额
                cell.number_format = "#,##0"
        
        ws1.row_dimensions[row_idx].height = 25
    
    # 设置列宽
    col_widths = [15, 15, 12, 12, 12, 18, 20]
    for i, width in enumerate(col_widths, 1):
        ws1.column_dimensions[get_column_letter(i)].width = width
    
    # ========== Sheet2: 沪深300成分股 ==========
    ws2 = wb.create_sheet("沪深300成分股行情")
    
    # 标题行
    ws2.merge_cells("A1:P1")
    ws2["A1"] = "沪深300指数成分股实时行情"
    ws2["A1"].font = title_font
    ws2["A1"].fill = title_fill
    ws2["A1"].alignment = title_alignment
    ws2.row_dimensions[1].height = 40
    
    # 表头
    hs300_headers = [
        "股票代码", "股票名称", "最新价", "涨跌幅(%)", "涨跌额",
        "成交量(手)", "成交额(元)", "振幅(%)", "最高价", "最低价",
        "今开", "昨收", "量比", "换手率(%)", "市盈率(动态)", "市净率"
    ]
    for col, header in enumerate(hs300_headers, 1):
        cell = ws2.cell(row=2, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
    ws2.row_dimensions[2].height = 30
    
    # 数据行
    for row_idx, item in enumerate(hs300_data, 3):
        values = [
            item.get("股票代码", ""),
            item.get("股票名称", ""),
            item.get("最新价", 0),
            item.get("涨跌幅(%)", 0),
            item.get("涨跌额", 0),
            item.get("成交量(手)", 0),
            item.get("成交额(元)", 0),
            item.get("振幅(%)", 0),
            item.get("最高价", 0),
            item.get("最低价", 0),
            item.get("今开", 0),
            item.get("昨收", 0),
            item.get("量比", 0),
            item.get("换手率(%)", 0),
            item.get("市盈率(动态)", 0),
            item.get("市净率", 0),
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws2.cell(row=row_idx, column=col_idx, value=val)
            cell.font = data_font
            cell.alignment = data_alignment
            cell.border = thin_border
            # 交替行背景
            if row_idx % 2 == 0:
                cell.fill = even_fill
            else:
                cell.fill = odd_fill
            # 涨跌幅特殊颜色（第4列）
            if col_idx == 4:
                if val is not None and val > 0:
                    cell.font = up_font
                elif val is not None and val < 0:
                    cell.font = down_font
            # 涨跌额特殊颜色（第5列）
            if col_idx == 5:
                if val is not None and val > 0:
                    cell.font = up_font
                elif val is not None and val < 0:
                    cell.font = down_font
            # 数字格式
            if col_idx in [3, 4, 5, 8, 9, 10, 11, 12, 13, 14, 15, 16]:
                cell.number_format = "#,##0.00"
            elif col_idx in [6, 7]:
                cell.number_format = "#,##0"
        
        ws2.row_dimensions[row_idx].height = 22
    
    # 设置列宽
    hs300_col_widths = [12, 14, 10, 10, 10, 14, 16, 10, 10, 10, 10, 10, 8, 10, 12, 10]
    for i, width in enumerate(hs300_col_widths, 1):
        ws2.column_dimensions[get_column_letter(i)].width = width
    
    # 冻结首行
    ws1.freeze_panes = "A3"
    ws2.freeze_panes = "A3"
    
    # 保存到内存字节流
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    return output.getvalue()


@app.get("/api/stock-data", summary="获取A股实时行情Excel")
async def get_stock_data():
    """获取A股三大指数和沪深300成分股实时行情，返回Excel文件下载"""
    try:
        logger.info("开始获取A股实时行情数据...")
        start_time = time.time()
        
        # 并行获取指数和成分股数据
        index_task = asyncio.to_thread(get_index_real_time)
        hs300_task = asyncio.to_thread(get_hs300_components)
        
        index_data, hs300_data = await asyncio.gather(index_task, hs300_task)
        
        if not index_data and not hs300_data:
            raise HTTPException(status_code=500, detail="获取数据失败，所有数据源均返回空")
        
        logger.info(f"指数数据获取完成: {len(index_data)}条")
        logger.info(f"沪深300成分股数据获取完成: {len(hs300_data)}条")
        
        # 生成Excel
        excel_bytes = create_excel(index_data, hs300_data)
        
        # 写入临时文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"A股实时行情_{timestamp}.xlsx"
        
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".xlsx", prefix="a_stock_"
        ) as tmp:
            tmp.write(excel_bytes)
            tmp_path = tmp.name
        
        elapsed = time.time() - start_time
        logger.info(f"数据获取完成，耗时: {elapsed:.2f}秒，文件: {filename}")
        
        return FileResponse(
            path=tmp_path,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取数据失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取数据失败: {str(e)}")


@app.get("/", summary="服务状态")
async def root():
    """检查服务是否正常运行"""
    return {
        "service": "A股实时行情数据获取工具",
        "status": "running",
        "version": "1.0.0",
        "endpoints": {
            "获取行情Excel": "/api/stock-data",
            "Swagger文档": "/docs",
        },
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.on_event("startup")
async def startup_event():
    """服务启动时的初始化"""
    logger.info("=" * 50)
    logger.info("A股实时行情数据获取服务启动")
    logger.info("访问 http://localhost:8000 查看服务状态")
    logger.info("访问 http://localhost:8000/docs 查看API文档")
    logger.info("访问 http://localhost:8000/api/stock-data 下载Excel")
    logger.info("=" * 50)


@app.on_event("shutdown")
async def shutdown_event():
    """服务关闭时的清理"""
    logger.info("A股实时行情数据获取服务关闭")


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
''')
```

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'a_stock_data_fetcher'
📄 创建文件 'requirements.txt'
📄 创建文件 'README.md'
📄 创建文件 'main.py'
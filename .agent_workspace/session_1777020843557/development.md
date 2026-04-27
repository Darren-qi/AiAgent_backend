### 第一批：创建项目目录和核心脚本

```
project_create("stock_exporter")
```
```
file_write(
    path="stock_exporter.py",
    content="""
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
今日股市数据导出工具
从公开数据源获取A股行情数据，导出为Excel文件

依赖安装：
pip install akshare openpyxl pandas
"""

import os
import sys
import datetime
from typing import Optional

# 尝试导入依赖
try:
    import pandas as pd
except ImportError:
    print("错误：缺少 pandas 库，请执行: pip install pandas")
    sys.exit(1)

try:
    import openpyxl
except ImportError:
    print("错误：缺少 openpyxl 库，请执行: pip install openpyxl")
    sys.exit(1)

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("警告：缺少 akshare 库，将使用模拟数据。请执行: pip install akshare")


def get_today_date() -> str:
    """返回今日日期字符串 YYYY-MM-DD"""
    return datetime.date.today().strftime("%Y-%m-%d")


def fetch_stock_data_from_akshare() -> Optional[pd.DataFrame]:
    """
    使用 akshare 获取A股实时行情数据
    返回 DataFrame，包含：股票代码、名称、最新价、涨跌幅、成交额等
    """
    if not AKSHARE_AVAILABLE:
        return None
    
    try:
        print("正在从 akshare 获取实时股市数据...")
        # 获取A股实时行情（包含沪深两市所有股票）
        df = ak.stock_zh_a_spot_em()
        
        # 选择并重命名关键列
        required_columns = {
            '代码': '股票代码',
            '名称': '股票名称',
            '最新价': '最新价',
            '涨跌幅': '涨跌幅(%)',
            '涨跌额': '涨跌额',
            '成交量': '成交量(手)',
            '成交额': '成交额(元)',
            '振幅': '振幅(%)',
            '最高': '最高价',
            '最低': '最低价',
            '今开': '开盘价',
            '昨收': '昨收价'
        }
        
        # 只保留需要的列
        available_cols = [col for col in required_columns if col in df.columns]
        df = df[available_cols].copy()
        df.rename(columns={col: required_columns[col] for col in available_cols}, inplace=True)
        
        # 格式化数值（保留两位小数）
        numeric_cols = ['最新价', '涨跌幅(%)', '涨跌额', '振幅(%)', '最高价', '最低价', '开盘价', '昨收价']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].round(2)
        
        # 成交额转为亿元显示更友好
        if '成交额(元)' in df.columns:
            df['成交额(亿)'] = (df['成交额(元)'] / 1e8).round(2)
            df.drop(columns=['成交额(元)'], inplace=True)
        
        # 成交量转为万手显示
        if '成交量(手)' in df.columns:
            df['成交量(万手)'] = (df['成交量(手)'] / 1e4).round(2)
            df.drop(columns=['成交量(手)'], inplace=True)
        
        print(f"成功获取 {len(df)} 只股票数据")
        return df
        
    except Exception as e:
        print(f"akshare 数据获取失败: {e}")
        return None


def generate_fake_stock_data() -> pd.DataFrame:
    """
    生成模拟股市数据（当真实数据源不可用时）
    用于演示功能
    """
    print("使用模拟数据演示...")
    
    fake_data = {
        '股票代码': [
            '000001', '000002', '000333', '000651', '000858',
            '600519', '600036', '601318', '600900', '601166',
            '002415', '300750', '000568', '002594', '300059'
        ],
        '股票名称': [
            '平安银行', '万科A', '美的集团', '格力电器', '五粮液',
            '贵州茅台', '招商银行', '中国平安', '长江电力', '兴业银行',
            '海康威视', '宁德时代', '泸州老窖', '比亚迪', '东方财富'
        ],
        '最新价': [
            11.23, 8.56, 65.40, 39.88, 135.20,
            1780.50, 36.78, 45.60, 25.88, 17.45,
            32.10, 198.50, 145.60, 256.80, 13.56
        ],
        '涨跌幅(%)': [
            2.15, -1.23, 0.85, -0.45, 1.56,
            0.32, -0.78, 1.89, 0.12, -0.56,
            2.33, -1.45, 0.67, 3.21, -0.89
        ],
        '涨跌额': [
            0.24, -0.11, 0.55, -0.18, 2.08,
            5.68, -0.29, 0.85, 0.03, -0.10,
            0.73, -2.90, 0.97, 8.00, -0.12
        ],
        '成交量(万手)': [
            45.23, 78.56, 12.34, 56.78, 23.45,
            8.90, 67.12, 34.56, 89.01, 112.34,
            45.67, 23.89, 34.12, 56.78, 78.90
        ],
        '成交额(亿)': [
            5.08, 6.72, 8.07, 22.64, 31.71,
            158.47, 24.68, 15.76, 23.03, 19.60,
            14.66, 47.42, 4.96, 145.81, 10.70
        ],
        '振幅(%)': [
            3.45, 2.89, 1.56, 2.34, 2.78,
            1.12, 2.01, 3.22, 1.45, 1.89,
            3.67, 2.45, 2.12, 4.56, 2.78
        ],
        '最高价': [
            11.45, 8.78, 65.80, 40.12, 136.50,
            1790.00, 37.20, 46.50, 26.10, 17.60,
            32.80, 200.50, 146.80, 260.00, 13.80
        ],
        '最低价': [
            11.05, 8.45, 64.90, 39.50, 133.80,
            1772.00, 36.40, 45.00, 25.60, 17.20,
            31.50, 197.00, 144.50, 252.00, 13.30
        ],
        '开盘价': [
            11.30, 8.60, 65.10, 39.95, 134.50,
            1775.00, 36.90, 45.20, 25.90, 17.50,
            31.80, 199.00, 145.00, 255.00, 13.45
        ],
        '昨收价': [
            10.99, 8.79, 64.85, 40.33, 133.12,
            1774.82, 37.07, 44.71, 25.85, 18.01,
            31.37, 201.40, 144.63, 248.59, 14.45
        ]
    }
    
    return pd.DataFrame(fake_data)


def export_to_excel(df: pd.DataFrame, filename: str) -> bool:
    """
    将DataFrame导出为格式化的Excel文件
    """
    try:
        print(f"正在导出到 {filename} ...")
        
        # 使用 openpyxl 引擎写入Excel
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='今日股市数据', index=False)
            
            # 获取工作表
            workbook = writer.book
            worksheet = writer.sheets['今日股市数据']
            
            # 设置列宽
            column_widths = {
                'A': 12,  # 股票代码
                'B': 14,  # 股票名称
                'C': 10,  # 最新价
                'D': 10,  # 涨跌幅
                'E': 10,  # 涨跌额
                'F': 14,  # 成交量
                'G': 12,  # 成交额
                'H': 10,  # 振幅
                'I': 10,  # 最高价
                'J': 10,  # 最低价
                'K': 10,  # 开盘价
                'L': 10,  # 昨收价
            }
            for col_letter, width in column_widths.items():
                if col_letter in worksheet.column_dimensions:
                    worksheet.column_dimensions[col_letter].width = width
            
            # 设置表头样式（加粗、居中、浅蓝色背景）
            from openpyxl.styles import Font, PatternFill, Alignment
            header_font = Font(bold=True, size=11)
            header_fill = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")
            header_alignment = Alignment(horizontal='center', vertical='center')
            
            for cell in worksheet[1]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment
        
        print(f"✅ 导出成功：{filename}")
        return True
        
    except Exception as e:
        print(f"❌ 导出失败: {e}")
        return False


def main():
    """主函数"""
    print("=" * 50)
    print("  今日股市数据导出工具")
    print("=" * 50)
    
    # 获取数据
    df = fetch_stock_data_from_akshare()
    
    # 如果真实数据获取失败，使用模拟数据
    if df is None or df.empty:
        print("真实数据源不可用，切换到模拟数据模式。")
        df = generate_fake_stock_data()
    
    # 显示数据预览
    print(f"\n📊 数据预览（前5行）：")
    print(df.head().to_string(index=False))
    print(f"\n共 {len(df)} 条记录")
    
    # 导出到Excel
    today = get_today_date()
    filename = f"今日股市数据_{today}.xlsx"
    
    success = export_to_excel(df, filename)
    
    if success:
        # 显示文件路径
        abs_path = os.path.abspath(filename)
        print(f"\n📁 文件位置：{abs_path}")
        print(f"📏 文件大小：{os.path.getsize(filename) / 1024:.1f} KB")
    else:
        print("\n❌ 导出失败，请检查错误信息。")
        sys.exit(1)


if __name__ == "__main__":
    main()
"""
)
```

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'stock_exporter'
📄 创建文件 'stock_exporter.py'
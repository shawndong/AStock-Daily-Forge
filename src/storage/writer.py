"""
存储写入工具
所有 md 文件的写入操作统一在此处，业务层不直接操作文件
"""

import os
from datetime import date


def ensure_dir(path: str):
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)


def date_to_filename(d: date) -> str:
    """date 对象 → 文件名，例如 20250110.md"""
    return d.strftime("%Y%m%d") + ".md"


def write_md(dir_path: str, filename: str, content: str, mode: str = "w"):
    """
    写入 md 文件
    :param dir_path: 目标目录
    :param filename: 文件名（含 .md）
    :param content:  文件内容
    :param mode:     'w' 覆盖写入，'a' 追加写入
    """
    ensure_dir(dir_path)
    file_path = os.path.join(dir_path, filename)
    with open(file_path, mode, encoding="utf-8") as f:
        f.write(content)
    return file_path


def rows_to_md_table(headers: list[str], rows: list[list]) -> str:
    """
    将列表数据转换为 Markdown 表格字符串
    :param headers: 表头列表
    :param rows:    数据行列表（每行是一个列表）
    :return: Markdown 表格字符串
    """
    header_row = "| " + " | ".join(headers) + " |"
    separator  = "| " + " | ".join(["---"] * len(headers)) + " |"
    data_rows  = [
        "| " + " | ".join(str(cell) if cell is not None else "N/A" for cell in row) + " |"
        for row in rows
    ]
    return "\n".join([header_row, separator] + data_rows) + "\n"

"""
存储读取工具
所有 md 文件的读取操作统一在此处
"""

import os
import re
from datetime import date, timedelta


def date_to_filename(d: date) -> str:
    return d.strftime("%Y%m%d") + ".md"


def read_md(dir_path: str, filename: str) -> str | None:
    """
    读取 md 文件，文件不存在时返回 None
    """
    file_path = os.path.join(dir_path, filename)
    if not os.path.exists(file_path):
        return None
    with open(file_path, encoding="utf-8") as f:
        return f.read()


def read_md_by_date(dir_path: str, d: date) -> str | None:
    """按日期读取 md 文件"""
    return read_md(dir_path, date_to_filename(d))


def read_recent_mds(dir_path: str, n: int, end_date: date = None) -> list[tuple[date, str]]:
    """
    读取最近 n 个交易日的 md 文件（从目录中已存在的文件推断）
    :return: [(date, content), ...] 按日期升序排列，跳过不存在的文件
    """
    if end_date is None:
        end_date = date.today()

    results = []
    d = end_date
    while len(results) < n and d >= end_date - timedelta(days=60):
        content = read_md_by_date(dir_path, d)
        if content is not None:
            results.append((d, content))
        d -= timedelta(days=1)

    return list(reversed(results))


def parse_md_table(content: str, section: str = None) -> list[dict]:
    """
    解析 md 文件中的表格为字典列表
    :param content: md 文件内容
    :param section: 如果指定，只解析该 ## 标题下的第一个表格
    :return: [{"列名": "值", ...}, ...]
    """
    if section:
        pattern = rf"##\s+{re.escape(section)}\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, content, re.DOTALL)
        content = match.group(1) if match else ""

    lines = [line.strip() for line in content.strip().splitlines()]
    table_lines = [line for line in lines if line.startswith("|")]

    if len(table_lines) < 2:
        return []

    headers = [h.strip() for h in table_lines[0].strip("|").split("|")]
    rows = []
    for line in table_lines[2:]:  # 跳过分隔行
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))

    return rows


def list_stock_dirs(stocks_dir: str) -> list[str]:
    """列出 stocks/ 下所有有效的股票代码目录"""
    if not os.path.exists(stocks_dir):
        return []
    return [
        d for d in os.listdir(stocks_dir)
        if os.path.isdir(os.path.join(stocks_dir, d))
        and not d.startswith(".")
    ]

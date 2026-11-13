"""xlsx 抽取（T9.7）：只读第一张工作表，转成 Markdown 表。

**只读第一张表不是偷懒**：成绩单、课表、考点清单都放在第一张，
后面的表往往是"数据源""透视"之类的中间产物，全读进来会让检索命中一堆重复行。
真要读别的表，用户在 WPS 里挪到第一张就行 —— 比在这里猜"哪张才是主表"可靠。

**200 行上限**：一份课程表 5000 行，切块后前 8 块全是数字行，检索就被淹了。
上限写进 `meta.truncated`，界面上要如实说"只读了前 200 行"。
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

from app.services.extractors.base import ExtractedDoc, Extractor, ExtractError, PageText, \
    md_table, tidy

MAX_ROWS = 200
MAX_COLS = 30


class XlsxExtractor(Extractor):
    ext = "xlsx"

    def extract(self, path: Path, original_name: str = "") -> ExtractedDoc:
        try:
            # read_only 不把整本工作簿读进内存；data_only 取公式的**计算结果**，
            # 否则正文里全是 `=SUM(B2:B9)` 这种没人要的字符串
            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        except Exception as exc:                       # noqa: BLE001
            raise ExtractError(
                "EXTRACT_FAILED", "这个 Excel 文件打不开，可能已损坏或是旧版 .xls 改的后缀",
                f"{type(exc).__name__}: {exc}",
            ) from exc

        try:
            sheet = wb.worksheets[0] if wb.worksheets else None
            if sheet is None:
                raise ExtractError("EXTRACT_FAILED", "这个 Excel 里一张工作表都没有")
            name = str(sheet.title)
            rows, total_rows, truncated = _read_rows(sheet)
            sheets = len(wb.sheetnames)
            names = list(wb.sheetnames)
        finally:
            wb.close()

        table = md_table(rows)
        if table and sheets > 1:
            # 有多张表时说一句读的是哪张，否则用户对不上"我明明有 3 张表"
            table = f"工作表：{name}\n\n{table}"
        text = tidy(table)
        meta = {
            "sheet": name,
            "sheets": sheets,
            "sheet_names": names,
            "rows_read": len(rows),
            "rows_total": total_rows,
            "columns": max((len(r) for r in rows), default=0),
            "truncated": truncated,
        }
        page = PageText(page_no=1, text=text)
        return ExtractedDoc(text=text, pages=[page], page_count=1, meta=meta)


def _read_rows(sheet) -> tuple[list[list], int, bool]:
    """返回（保留的行, 源表实际行数, 是否被截断）。

    `read_only=True` 下 `ws.max_row` 可能偏大（末尾一堆空行）或不准，
    所以行数按**迭代计数**，不信 `max_row`。
    """
    rows: list[list] = []
    total = 0
    truncated = False
    for raw in sheet.iter_rows(values_only=True):
        total += 1
        cells = list(raw[:MAX_COLS])
        # 整行空（或只有空格）不算内容：报表里这种行很常见，留着只是噪音
        if all(c is None or str(c).strip() == "" for c in cells):
            continue
        if len(rows) >= MAX_ROWS:
            truncated = True
            break
        rows.append(cells)
    return _trim(rows), total, truncated


def _trim(rows: list[list]) -> list[list]:
    """砍掉右侧整列为空的列（Excel 的已用区域常比真实内容宽）。"""
    width = 0
    for row in rows:
        for i, cell in enumerate(row):
            if cell is not None and str(cell).strip() != "":
                width = max(width, i + 1)
    return [[("" if c is None else c) for c in row[:width]] for row in rows]

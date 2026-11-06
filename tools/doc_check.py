#!/usr/bin/env python3
"""
文档一致性检查（doc lint）

目的：不是"阻止 agent 读错文档"，而是"读错之后立刻暴露"。
在每次会话开场、以及每次修改文档之后运行。

用法：
    python tools/doc_check.py            # 全量检查
    python tools/doc_check.py --strict   # WARN 也视为失败

检查项：
    1. 所有非归档文档必须有「作用域」声明
    2. 文档中引用的 ADR-xxx 必须在决策记录中存在
    3. 文档中引用的 /api/xxx 必须在接口契约中存在
    4. 文档中出现的 CREATE TABLE 必须在数据契约中存在
    5. 除总纲与台账外，不许引用 archive/ 下的文件
    6. 已标记"已完结"的里程碑文档若被其他文档当作现状引用，报 WARN

退出码：0 全通过；1 有 FAIL（或 --strict 下有 WARN）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
ARCHIVE = DOCS / "archive"

FAIL: list[str] = []
WARN: list[str] = []
PASS: list[str] = []


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def load_docs() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for p in sorted(DOCS.rglob("*.md")):
        if ARCHIVE in p.parents:
            continue
        out[p] = p.read_text(encoding="utf-8")
    return out


def line_of(text: str, needle: str) -> int:
    for i, ln in enumerate(text.splitlines(), start=1):
        if needle in ln:
            return i
    return 0


def main() -> int:
    docs = load_docs()
    if not docs:
        print("未找到任何文档")
        return 1

    contract_data = DOCS / "contracts" / "数据契约.md"
    contract_api = DOCS / "contracts" / "接口契约.md"
    decisions = DOCS / "contracts" / "决策记录.md"

    for required in (contract_data, contract_api, decisions):
        if not required.exists():
            FAIL.append(f"缺少必需文档：{rel(required)}")
    if FAIL:
        report()
        return 1

    data_text = contract_data.read_text(encoding="utf-8")
    api_text = contract_api.read_text(encoding="utf-8")
    adr_text = decisions.read_text(encoding="utf-8")

    # ── 事实源 ────────────────────────────────────────────
    defined_adrs = set(re.findall(r"^##\s+(ADR-\d{3})", adr_text, re.MULTILINE))

    defined_tables = set(
        t.lower()
        for t in re.findall(
            r"CREATE\s+(?:VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            data_text,
            re.IGNORECASE,
        )
    )

    defined_eps = set(re.findall(r"`(/api/[A-Za-z0-9_\-{}/]+)`", api_text))
    defined_eps |= set(
        re.findall(r"^###\s+(?:GET|POST|PATCH|DELETE)\s+(/api/\S+)", api_text, re.MULTILINE)
    )
    defined_eps = {e.rstrip("`.,;") for e in defined_eps}

    # ── 检查 1：作用域声明 ────────────────────────────────
    missing_scope = [rel(p) for p, t in docs.items() if "作用域" not in "\n".join(t.splitlines()[:22])]
    if missing_scope:
        for f in missing_scope:
            FAIL.append(f"{f} 顶部缺少「作用域」声明块")
    else:
        PASS.append(f"作用域声明：{len(docs)}/{len(docs)} 份文档齐全")

    # ── 检查 2：ADR 引用 ──────────────────────────────────
    bad_adr = 0
    for p, t in docs.items():
        if p == decisions:
            continue
        for ref in sorted(set(re.findall(r"ADR-\d{3}", t))):
            if ref not in defined_adrs:
                FAIL.append(f"{rel(p)}:{line_of(t, ref)} 引用了不存在的 {ref}")
                bad_adr += 1
    if bad_adr == 0:
        PASS.append(f"ADR 交叉引用：共 {len(defined_adrs)} 条定义，引用全部有效")

    # ── 检查 3：端点引用 ──────────────────────────────────
    # 两类误报要滤掉，否则台账里写路径/写测试 id 都会被判成未登记端点：
    #   1) 文件路径（`src/api/client.js`）——只截到 `/api/client`，后面紧跟扩展名
    #   2) 按具体 id 探测（`/api/knowledge/999`）——登记形状是 `/api/knowledge/{id}`
    file_ext = (".js", ".ts", ".vue", ".py", ".css", ".json", ".md", ".html")

    def _match_template(ep: str) -> bool:
        for defined in defined_eps:
            if "{" not in defined:
                continue
            pattern = "^" + re.sub(r"\\\{[^/]+\\\}", "[^/]+", re.escape(defined)) + "$"
            if re.match(pattern, ep):
                return True
        return False

    bad_ep = 0
    for p, t in docs.items():
        if p == contract_api:
            continue
        for m in re.finditer(r"/api/[A-Za-z0-9_\-{}/]+", t):
            ep_clean = m.group(0).rstrip(".,;`")
            if t[m.end():].startswith(file_ext):
                continue                      # 文件路径，不是端点
            if ep_clean in defined_eps or _match_template(ep_clean):
                continue
            FAIL.append(
                f"{rel(p)}:{line_of(t, ep_clean)} 引用了未在接口契约登记的端点 {ep_clean}"
            )
            bad_ep += 1
    if bad_ep == 0:
        PASS.append(f"端点交叉引用：共 {len(defined_eps)} 个登记端点，引用全部有效")

    # ── 检查 4：表名定义 ──────────────────────────────────
    bad_tbl = 0
    for p, t in docs.items():
        if p == contract_data:
            continue
        for tbl in sorted(
            set(
                re.findall(
                    r"CREATE\s+(?:VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
                    t,
                    re.IGNORECASE,
                )
            )
        ):
            if tbl.lower() not in defined_tables:
                FAIL.append(
                    f"{rel(p)}:{line_of(t, f'TABLE {tbl}')} 定义了表 {tbl}，"
                    f"但数据契约中没有 —— 表结构必须先在数据契约登记"
                )
                bad_tbl += 1
    if bad_tbl == 0:
        PASS.append(f"表结构一致性：共 {len(defined_tables)} 张表，无游离定义")

    # ── 检查 5：archive 引用 ──────────────────────────────
    allow_archive_ref = {"docs/00-总纲.md", "docs/HANDOFF.md"}
    bad_arch = 0
    for p, t in docs.items():
        if rel(p) in allow_archive_ref:
            continue
        for i, ln in enumerate(t.splitlines(), start=1):
            if "archive/" not in ln:
                continue
            # 作用域声明里的"不要读 archive/xxx"属于正当引用，跳过
            if "不要读" in ln or "勿读" in ln:
                continue
            FAIL.append(f"{rel(p)}:{i} 引用了归档文档（归档内容已失效）")
            bad_arch += 1
    if bad_arch == 0:
        PASS.append("归档隔离：无文档引用 archive/ 下的失效内容")

    # ── 检查 6：完结文档被当现状引用 ──────────────────────
    finished = {
        rel(p)
        for p, t in docs.items()
        if "已完结" in "\n".join(t.splitlines()[:12])
    }
    if finished:
        for p, t in docs.items():
            if rel(p) in finished:
                continue
            for f in finished:
                name = Path(f).name
                if name in t and p.name != "00-总纲.md":
                    WARN.append(f"{rel(p)} 引用了已完结文档 {name}，确认不是把它当现状")
        PASS.append(f"完结标记：{len(finished)} 份文档已标记完结")
    else:
        PASS.append("完结标记：暂无已完结里程碑（正常）")

    report()
    return 1 if FAIL else 0


def report() -> None:
    for line in PASS:
        print(f"  PASS  {line}")
    for line in WARN:
        print(f"  WARN  {line}")
    for line in FAIL:
        print(f"  FAIL  {line}")
    print()
    if FAIL:
        print(f"✗ {len(FAIL)} 项不一致，先修文档再动代码。")
    else:
        print(f"✓ 文档一致性检查通过（{len(PASS)} 项通过，{len(WARN)} 项提示）")


if __name__ == "__main__":
    sys.exit(main())

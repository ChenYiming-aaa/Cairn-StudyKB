# e2e · 浏览器端到端回归

仓库里唯一的 UI 回归。验的是「人真的能走通」，接口健壮性由 `backend/scripts/verify_m1.py` 负责，两者不重复。

## 怎么跑

```bash
# 终端 1
cd backend && uv run uvicorn app.main:app --port 8756

# 终端 2
cd frontend && npm run dev

# 终端 3
cd frontend && npm run e2e
```

`npm run e2e` 调的是 `D:\Anaconda3\python.exe`——本机 Playwright 只装在这个解释器下，
backend 的 `.venv` 里没有。换机器或换 Python 路径时改 `package.json` 的那一行即可。

可选参数（直接调脚本时）：

```bash
D:/Anaconda3/python.exe e2e/m1_flow.py --keep        # 保留截图与测试条目，排障用
D:/Anaconda3/python.exe e2e/m1_flow.py --timeout 300 # 整理等待上限，默认 180s
```

截图落在 `e2e/_shots/`（gitignored），不加 `--keep` 时跑完自动删。

## 它验什么

| 步骤 | 断言 |
|---|---|
| 首屏 | 顶栏显示「已连接」 |
| 粘贴 | 800 字入库，列表首行 pending、徽标「待整理」 |
| 整理 | 真实 LLM 调用；状态转「就绪」，五个字段非空，标题被 AI 改写且 ≤20 字 |
| 分类树 | 左侧出现新分类；点击后列表条数与接口 `total` 一致；总数来自后端聚合 |
| 笔记 | 编辑保存 → toast；刷新后内容仍在、「笔记已手改」出现、note chunk 落库 |
| 收尾 | 浏览器 console 无 error；测试条目被删除、截图被清掉 |

## 注意

- **会花钱**：一次运行至少 1 次真实 LLM 调用（约 2k 输入 token）。
- **会写库**：默认用 `data/data.db`，条目正文带 `【e2e-HHMMSS】` 前缀保证哈希唯一，跑完自动删除；中途崩溃也会在 `finally` 里清理。
- 它不替代人工验收：视觉与交互手感（间距、动效、滚动）仍然要自己看。

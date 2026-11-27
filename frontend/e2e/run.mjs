// 选一个「装了 Playwright 且真能起浏览器」的 Python，再把参数透传给 e2e 脚本。
//
// 为什么要有这一层：`npm run e2e` 原来直接写死 `D:\Anaconda3\python.exe`。
// 那是某台机器上「唯一装了 Playwright 的解释器」，不是仓库事实 —— 换机、换 conda 路径、
// 上 CI 都必然找不到。而「装了包」也不等于「能用」：Playwright 的浏览器是独立下载到
// `%LOCALAPPDATA%\ms-playwright` 的，包版本与已下载的浏览器版本对不上时，import 成功、
// launch 失败，报的还是「请运行 playwright install」。所以判据不是「有没有这个包」，
// 而是**真的起一次浏览器**。
//
// 用法（等价于直接拿某个 python 跑脚本）：
//   node e2e/run.mjs                     # 跑 m1_flow.py
//   node e2e/run.mjs m4_quiz --keep      # 跑 m4_quiz.py，其余参数原样透传
//   CAIRN_PYTHON=/path/to/python node e2e/run.mjs   # 直接指定，跳过探测
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const VENV = path.resolve(HERE, "../../backend/.venv");

// 探测脚本：import 得到 + 起得来浏览器，才算可用。只起一次、立刻关掉。
// 走 stdin（`python -`）而不是 `-c`：Windows 下带换行和引号的 `-c` 参数会被重新切词，
// 实测 `py -3` 会把程序截成半句、报的还是一串乱码。
const PROBE = [
  "from playwright.sync_api import sync_playwright",
  "with sync_playwright() as p:",
  "    b = p.chromium.launch()",
  "    b.close()",
  "print('ok')",
].join("\n");

/** 候选解释器。venv 排前面：它跟着仓库走，比系统 Python 稳。 */
function candidates() {
  const list = [];
  if (process.env.CAIRN_PYTHON) list.push([process.env.CAIRN_PYTHON]);
  for (const rel of ["Scripts/python.exe", "bin/python"]) {
    const p = path.join(VENV, rel);
    if (existsSync(p)) list.push([p]);
  }
  // 系统里的：Windows 用 py -3 更可靠（"python" 常被商店占位符劫走）
  list.push(["python3"], ["python"]);
  if (process.platform === "win32") list.push(["py", "-3"]);
  return list;
}

function probe(cmd) {
  const r = spawnSync(cmd[0], [...cmd.slice(1), "-"], {
    input: PROBE,
    encoding: "utf8",
    timeout: 90_000,
  });
  if (r.error?.code === "ENOENT") return { ok: false, why: "找不到这个解释器" };
  if (r.error) return { ok: false, why: r.error.message.split("\n")[0] };
  if (r.status === 0 && (r.stdout ?? "").includes("ok")) return { ok: true };

  const out = `${r.stdout ?? ""}${r.stderr ?? ""}`;
  if (/No module named '?playwright/.test(out)) return { ok: false, why: "没装 playwright" };
  if (/playwright install/.test(out)) return { ok: false, why: "浏览器版本对不上（缺 playwright install）" };
  return { ok: false, why: (out.trim().split("\n").pop() || `退出码 ${r.status}`).trim() };
}

// 第一个参数若是已知脚本名就换成路径，否则整个当参数
const argv = process.argv.slice(2);
const first = argv[0] && !argv[0].startsWith("-") ? argv[0] : "";
let script = "m1_flow.py";
if (first) {
  script = first.endsWith(".py") ? first : `${first}.py`;
  argv.shift();
}
const target = path.join(HERE, script);
if (!existsSync(target)) {
  console.error(`× 找不到脚本：${target}`);
  process.exit(2);
}

console.log(`探测解释器（要能起 Playwright 浏览器）：`);
let chosen = null;
for (const cmd of candidates()) {
  const r = probe(cmd);
  const label = cmd.join(" ");
  if (r.ok) {
    console.log(`  ✓ ${label}`);
    chosen = cmd;
    break;
  }
  console.log(`  · ${label} —— ${r.why}`);
}

if (!chosen) {
  console.error(
    [
      "",
      "× 没有可用的解释器。任选一条修：",
      "  1) 让仓库自带的 venv 能用：cd backend && uv run playwright install chromium",
      "  2) 指个现成的：          CAIRN_PYTHON=D:/Anaconda3/python.exe npm run e2e",
      "  3) 新装一个：            pip install playwright && playwright install chromium",
    ].join("\n"),
  );
  process.exit(2);
}

const r = spawnSync(chosen[0], [...chosen.slice(1), target, ...argv], { stdio: "inherit" });
process.exit(r.status ?? 1);

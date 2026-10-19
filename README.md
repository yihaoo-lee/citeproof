# 有据 CiteProof

**有据（CiteProof）：可验证的文献证据矩阵。**

输入一个研究问题，输出一张证据矩阵：每篇论文的结论、方法等六个字段，每个字段都能点回原文原句和页码。核心原则只有一条——**核不上原文不上屏**。

## 解决什么问题

写综述、开题、基金本子时，要读几十篇论文。常见的做法是让 AI 帮忙总结，但 AI 总结有两个毛病：结论没有出处，引文可能是编的。

这个项目做的是反过来的事：模型只负责指出证据在哪，原文由程序从 PDF 里取，对不上就丢弃。多篇论文还能自动综合出共识和分歧。

## 工作流

1. 检索：OpenAlex 开放获取论文为主，结果太少时用 arXiv 兜底；中文问题先翻译成英文检索词。
2. 解析：PyMuPDF 按页提取，双栏论文按文本块坐标分栏，断行连字符合并；扫描版无文字层会跳过。
3. 抽取：DeepSeek 按 JSON 输出六个字段（问题/方法/数据集/结论/局限/可复现性）的中文概括，外加每条对应的短锚点。
4. 定位与校验：程序用锚点或模型提案在原文里定位，扩出完整原句；逐字比对分精确/归一化/锚点三档；表格碎片和歧义直接丢弃。
5. 语义复审：claim 和原句再做一次三分类（支持/部分支持/不支持），模型自评。
6. 矩阵：行=论文，列=六字段，点格子看原文；顶部是证据漏斗图。
7. 综合：同字段多篇证据做跨论文共识/分歧（共识/部分共识/分歧/证据不足四档）。
8. 导出：CSV / XLSX / DOCX。

## 关键特性

- 逐字校验：模型提案或锚点定位出的原句，和页面文本逐字比对，对不上不上屏。
- 审计轨迹：每条引用可展开六步——模型提案、锚点定位、服务端扩句、逐字比对、证据级别、语义复审。
- 引文上下文：每条引用可展开所在段落，quote 原文高亮。
- 跨论文综合：同字段多篇证据自动判定共识/分歧，展开可见各方原文。
- 证据漏斗：检索 N 篇 → 全文可解析 → 有引用；候选 N 条 → 校验通过 → 丢弃 → 语义三色。
- 离线演示：点“离线演示”读 `data/cache/demo.json`，不联网。
- 深/浅色主题。
- 排序：相关度/最新/被引三档，在服务端对相关候选池重排，不把排序参数直接交给 OpenAlex。
- 联网 5 篇约 29 秒（下载分层超时 + 8 路并发 + LLM 批量）。
- PDF 上传：校验 `%PDF-` 魔数、文件名 basename、50MB 上限。
- 元数据回填：本地 PDF 的标题/年份按 PDF 元数据 → ACL Anthology → arXiv → 文件名 的顺序补。
- 导出 CSV/XLSX/DOCX。

## 快速开始

环境：Python 3.11+，Windows/macOS/Linux 均可。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env        # 填入 LLM_API_KEY
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 。没配 key 也能跑：点“离线演示”直接加载 5 篇演示论文的缓存矩阵。

`.env` 字段：

| 变量 | 说明 |
|---|---|
| LLM_API_KEY | DeepSeek 或 OpenAI 兼容密钥 |
| LLM_BASE_URL | 默认 `https://api.deepseek.com/v1` |
| LLM_MODEL | 默认 `deepseek-chat` |
| DEMO_MODE | 0=真实检索/抽取；1=启发式 stub（不调模型，仅自测/保底） |
| OPENALEX_MAILTO | OpenAlex 礼貌池邮箱 |

注意区分：页面“离线演示”按钮读的是 `demo.json`（真实模型结果缓存）；`DEMO_MODE=1` 是让分析走启发式 stub，两者不是一回事。

## 目录结构

```text
app/
  main.py               FastAPI 入口与路由
  models.py             数据结构
  services/
    search.py           检索（OpenAlex + arXiv + 中文翻译）
    fetch.py            下载 PDF（超时/大小/魔数）
    parse.py            双栏感知解析 + 断行连字符合并
    extract.py          六字段抽取 + 锚点
    verify.py           三级定位、扩句、上下文、碎片过滤
    entail.py           claim–quote 语义三分类
    matrix.py           矩阵组装 + 并发 + 进度
    export.py           CSV/XLSX/DOCX 导出
    pipeline.py         下载→解析→抽取→校验→综合
    synthesize.py       跨论文共识/分歧
    metadata.py         本地 PDF 标题/年份回填
  static/               前端（index.html / style.css / app.js）
data/
  cache/demo.json       离线演示缓存
  cache/local_meta.json 本地 PDF 标题缓存
  papers/               本地 PDF（上传或手动放入）
scripts/
  selftest.py               离线自测（退出码 0）
  make_demo_cache_local.py  用 data/papers 重新生成缓存
  pick_arxiv_demo.py        从 arXiv 挑解析干净的论文
```

## 演示数据

`data/cache/demo.json` 是 5 篇幻觉检测方向论文的离线结果：22 条引用、可追溯率 88%、支持率 54.6%、字段完整率 96.7%。包含 5 篇的真实标题/年份、每条引用的审计轨迹和上下文，以及 6 个字段的跨论文综合。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/search | 检索论文（query / limit / sort） |
| POST | /api/analyze | 提交分析任务，返回 job_id |
| GET | /api/job/{id} | 轮询任务进度与结果 |
| GET | /api/local | 列出 data/papers 下的本地 PDF |
| POST | /api/upload | 上传 PDF（多文件） |
| GET | /api/demo | 读取离线演示缓存 |
| GET | /api/export?format=csv|xlsx|docx | 导出矩阵 |
| GET | /api/health | 健康检查 |

## 已知限制

- 扫描版 PDF（纯图片）没有文字层，解析不出来，会提示并跳过。
- 锚点定位依赖 PDF 文字层质量；两栏论文已做分栏处理，但复杂的表格/图注仍可能污染文本。
- 语义三分类和跨论文综合都是模型判定，不是人工审核，结论要自己复核。
- 检索以英文开放获取论文为主，中文论文需本地上传 PDF。

## 技术栈

FastAPI + 原生 HTML/CSS/JS（无前端框架）、PyMuPDF、pandas / openpyxl / python-docx、DeepSeek（OpenAI 兼容接口）。

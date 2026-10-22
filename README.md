# 有据 CiteProof

**有据（CiteProof）：可验证的文献证据矩阵。**

输入一个研究问题，输出一张证据矩阵：每篇论文按问题、方法等六个字段展示。已核验字段可查看定位到的原文句子和页码；未找到引用的概括显示为“未找到原文出处”，不作为已核验结论。

## 解决什么问题

写综述、开题、基金本子时，要读几十篇论文。常见的做法是让 AI 帮忙总结，但 AI 总结有两个毛病：结论没有出处，引文可能是编的。

这个项目让模型提出证据位置，再由程序从 PDF 提取文本中定位引用；语义支持程度由模型复审。只有判为“支持”或“部分支持”的证据参与跨论文综合。

## 工作流

1. 检索：OpenAlex 开放获取论文为主，结果太少时用 arXiv 兜底；中文问题先翻译成英文检索词。
2. 解析：PyMuPDF 按页提取，双栏论文按文本块坐标分栏，断行连字符合并；扫描版无文字层会跳过。
3. 抽取：DeepSeek 按 JSON 输出六个字段（问题/方法/数据集/结论/局限/可复现性）的中文概括，外加每条对应的短锚点。
4. 定位与校验：程序用模型提案或锚点定位原句；匹配分精确、归一化、锚点三档，归一化命中也返回 PDF 提取文本中的句子；表格碎片和歧义直接丢弃。
5. 语义复审：claim 和原句再做一次三分类（支持/部分支持/不支持），模型自评。
6. 矩阵：行=论文，列=六字段，点格子看原文；顶部是证据漏斗图。
7. 综合：同字段多篇证据做跨论文共识/分歧（共识/部分共识/分歧/证据不足四档）。
8. 导出：CSV / XLSX / DOCX。

## 关键特性

- 引用定位：精确、归一化或锚点定位成功才展示引用；未找到引用的概括标为“未找到原文出处”。归一化和锚点定位不等同于逐字一致。
- 审计轨迹：每条引用可展开六步——模型提案、锚点定位、服务端扩句、逐字比对、证据级别、语义复审。
- 引文上下文：每条引用可展开所在段落，quote 原文高亮。
- 跨论文综合：使用语义复审判为“支持”或“部分支持”的引用；不足两篇时显示“证据不足”。
- 证据漏斗：检索 N 篇 → 全文可解析 → 有引用；候选 N 条 → 校验通过 → 丢弃 → 语义三色。
- 离线演示：点“离线演示”读 `data/cache/demo.json`，不联网。
- 深/浅色主题。
- 排序：相关度/最新/被引三档，在服务端对相关候选池重排，不把排序参数直接交给 OpenAlex。
- 下载/解析最多 8 路并发，分析任务同时最多 2 个，每次最多 20 篇；实际耗时依网络和模型服务而变化。
- PDF 上传：校验 `%PDF-` 魔数、文件名 basename、50MB 上限。
- 元数据回填：本地 PDF 的标题/年份按 PDF 元数据 → ACL Anthology → arXiv → 文件名 的顺序补。
- 导出 CSV/XLSX/DOCX。
- 日志：`data/logs/app.log` 含每次模型调用的 token 统计与分析任务耗时。
- 测试：安装 `requirements-dev.txt` 后运行 `python -m pytest tests -q`；原有 `scripts/selftest.py` 仍可用于离线自测；端到端自测：先启动服务，再运行 `python scripts/e2e_smoke.py`。

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

## 部署到服务器（公网）

生产部署用 systemd 常驻服务 + nginx 反代，下面按 Ubuntu 举例。

`/etc/systemd/system/citeproof.service`：

```ini
[Unit]
Description=有据 CiteProof
After=network.target

[Service]
WorkingDirectory=/opt/citeproof
EnvironmentFile=/opt/citeproof/.env
ExecStart=/opt/citeproof/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

nginx 反代（`/etc/nginx/sites-available/citeproof`）：

```nginx
server {
    listen 80;
    server_name _;
    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

上线步骤：

1. 云服务器安全组开放 80 端口（以及 SSH 的 22 端口）。
2. `git pull` 拉最新代码，并把重建后的 `data/cache/demo.json` 一并同步过去。
3. `systemctl daemon-reload`，再 `systemctl restart citeproof`。

注意：任务与论文登记都存在进程内存里，服务重启会清空；建议单进程运行，不要开多个 worker。

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

`data/cache/demo.json` 是 5 篇幻觉检测方向论文的离线结果：23 条定位成功引用、引用命中率 92%、模型判为“支持”的比例 60.9%、字段填充率 96.7%。该比例来自本次缓存生成，每次重建会浮动，以 data/cache/demo.json 为准；不代表人工标注准确率。综合面板使用判为“支持”或“部分支持”的引用。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/search | 检索论文（query / limit / sort） |
| POST | /api/analyze | 提交已登记的论文 ID（最多 20 篇），返回 job_id |
| GET | /api/job/{id} | 轮询任务进度与结果 |
| GET | /api/local | 列出 data/papers 下的本地 PDF |
| POST | /api/upload | 上传 PDF（多文件） |
| GET | /api/demo | 读取离线演示缓存 |
| GET | /api/export?job_id=...&format=csv|xlsx|docx | 导出指定任务；离线演示使用 job_id=demo |
| GET | /api/health | 健康检查 |

## 已知限制

- 扫描版 PDF（纯图片）没有文字层，解析不出来，会提示并跳过。
- 锚点定位依赖 PDF 文字层质量；两栏论文已做分栏处理，但复杂的表格/图注仍可能污染文本。
- 语义三分类和跨论文综合都是模型判定，不是人工审核，结论要自己复核。
- 检索以英文开放获取论文为主，中文论文需本地上传 PDF。
- 分析任务和论文登记保存在服务进程内存中；重启会清空任务，当前需以单个服务进程运行。已完成任务最多保留 100 个，登记论文最多保留 1000 篇。

## 技术栈

FastAPI + 原生 HTML/CSS/JS（无前端框架）、PyMuPDF、pandas / openpyxl / python-docx、DeepSeek（OpenAI 兼容接口）。

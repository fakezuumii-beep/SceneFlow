# AI 商业晨报编辑器（MVP）

这是 Scene Flow 旁边的独立内容模块。它不导入 Scene Flow 的业务代码，也不修改项目、分镜或视频生成流程。

它会在一次运行里完成：

1. 从一小组官方 RSS / Atom 源、官方 GitHub Release 和可靠媒体源读取过去 24 小时的信息。
2. 按价格、融资、并购、企业采购、API、产品发布、成本与收入机会等商业信号排序。
3. 合并重复事件，打开原始页面核查，再选出 3～5 条。
4. 输出 `output/research.json` 和 Scene Flow 可直接读取的 `output/script.md`。
5. 同时在 `history/日期/` 保存一份不可覆盖的运行快照；同一天再次运行会新建带时间的子目录。

## 运行

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m ai_morning_editor
```

也可以双击本目录里的 `运行晨报.bat`。

Scene Flow 启动后，也可以点击左侧的“今日 AI 商业晨报”：生成或读取结果，核对事件、商业意义和来源，勾选人工确认后创建一期已经填好原稿的播客。确认动作不会自动开始视频生成，也不会发布。

默认会只读取过去 24 小时。输出位置、时间窗和条数可以调整：

```powershell
.\.venv\Scripts\python.exe -m ai_morning_editor --hours 24 --max-stories 5 --output ai_morning_editor\output
```

## 模型配置

编辑器优先读取下面三个环境变量：

- `MORNING_LLM_API_KEY`
- `MORNING_LLM_BASE_URL`（默认 `https://api.deepseek.com`）
- `MORNING_LLM_MODEL`（默认 `deepseek-v4-flash`）

如果没有设置 `MORNING_LLM_API_KEY`，在这个同仓库版本中会只读复用 `data/private/settings.json` 里已经配置的 Scene Flow 分镜模型密钥。它只复用连接信息，不依赖 Scene Flow 代码；将整个 `ai_morning_editor` 文件夹复制到别处后，设置环境变量即可独立运行。

模型不可用时仍会写出两份结构完整的降级结果，并在 `research.json` 的 `warnings` 中说明。降级稿适合检查流程，不等于人工编辑质量。

## 第一阶段边界

- 没有定时任务、RSSHub、数据库或管理后台。
- 来源清单直接保存在 `collect.py`，方便审阅和小范围调整。
- 不抓取没有明确发布时间的页面；不足 3 条时不会拿更早的旧闻凑数。
- `verified` 表示本次运行确实打开了原页，并取得了足够的正文证据；不是对来源观点真实性的永久背书。
- 媒体报道会保存在 `media_source`；若文章能回溯到并实际打开对应官方页面，则另外保存 `primary_source`。找不到时不会创建假的一手来源。

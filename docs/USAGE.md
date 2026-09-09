# SceneFlow — AI Automatic Podcast Video Workbench

SceneFlow turns scripts or audio into automatically edited videos through semantic shot planning, A-roll/B-roll selection, media retrieval, speech synthesis, lip-sync, and automated editing.

> **把一段文案和一个人物形象，变成一支有口型、有画面、有字幕的单人播客视频。**

SceneFlow 是一个运行在本机浏览器中的单人播客制作工作台。写下想说的话，选择主持人的图片或循环视频，点击一次「一键生成播客」；它会完成配音、时间对齐、分镜、素材匹配、人物口型、字幕与 MP4 导出。

![SceneFlow 工作台：输入文稿、选择人物形象，然后一键生成播客](screenshots/workspace-start.png)

*上图为本仓库正在运行的本地工作台截图。创作入口始终放在同一屏：左侧输入文案，中间选择人物形象，右侧即可启动生成。*

## 只需三步

1. **输入文案**：直接粘贴中文稿，选择声音和语速；也可以导入现成音频或 SRT。
2. **选择人物形象**：直接使用内置女主持或男主持循环视频，也可以上传清晰的单人正脸图，或从「我的素材」选择自己的素材。
3. **点击生成**：SceneFlow 从真实音频开始完成整条制作链，你可以随时在时间线上查看、替换和微调每一镜。

```text
文案 / 音频
    ↓
配音或转录，并与真实音频时间对齐
    ↓
按语义生成镜头时间线，匹配人物与 B-roll
    ↓
所选 A-roll Provider 生成人物口型 + 字幕
    ↓
16:9 MP4、SRT 与镜头来源清单
```

## 成片里有什么

| 模块 | SceneFlow 会做什么 |
| --- | --- |
| 连续配音 | Azure TTS V1 生成完整音轨；失败重试会复用已完成片段。 |
| 真实时间轴 | faster-whisper 为文稿/音频生成词级时间，镜头边界跟随真实停顿与语义节点。 |
| 智能分镜 | 默认由 DeepSeek 判断语义与可视化对象，也可连接自定义 OpenAI 兼容服务；程序统一决定人物出镜、B-roll 占比和镜头节奏。 |
| 画面素材 | 根据具体可视化对象检索 Pexels 或 Pixabay，也能逐镜换片或导入本地图片/视频。 |
| 人物口型 | 可选择轻量本地 Wav2Lip、高质量本地 MuseTalk 1.5，或配置 ComfyUI / 在线 API 自定义工作流。Wav2Lip 与 MuseTalk 均可接入一键生成。 |
| 最终交付 | 导出 16:9 MP4、字幕 SRT，以及可追溯的镜头和素材来源清单。 |

## 技术范围

一个面向普通创作者的本地音频转视频应用。输入中文原稿或导入音频，工作台会完成配音/转录、语义分镜、B-roll 搜索、人物口型、字幕与 MP4 导出。

在「连接与设置」中选择所需服务：

- 分镜 AI：默认支持 DeepSeek，只填写 API Key；高级用户也可以配置 OpenAI 兼容服务。
- B-roll：支持 Pexels / Pixabay，选择素材源后只填写对应 API Key。
- A-roll：支持轻量本地、高质量本地和自定义工作流三档。Wav2Lip 需先确认第三方非商业使用限制，再按需安装独立环境；其模型和代码不随主 Portable 打包。

文字配音使用 Azure TTS V1（`edge-tts`），无需 Azure Key，但需要联网并会把配音原稿发送到微软语音服务。faster-whisper、MuseTalk 1.5 和 FFmpeg 都在本机工作。只有用户主动选择并配置自定义 A-roll 时，工作台才会测试对应的 ComfyUI 或在线服务。

## 能做什么

**文字一键成片**

1. 粘贴原稿，选择 Azure TTS V1 的中文音色与语速。
2. 生成连续配音，再用 faster-whisper 将原稿标点对齐到真实词时间；Azure 失败后重试时会复用已完成段落。
3. DeepSeek 只做候选段语义分类，程序按配置计算视觉/人物双价值，并结合全片比例决定 A/B、叙事段合并和视觉镜头数量。
4. 程序按真实时间优先在标点/词边界切镜头，Pexels 自动匹配 B-roll。
5. 独立 MuseTalk 为 A-roll 生成人物口型。
6. FFmpeg 合成 16:9 MP4、字幕和导出清单。

**音频一键成片**

导入 MP3/WAV/M4A 后，本地 faster-whisper 先生成带真实词时间的标点候选段，再执行同一套规则分镜、素材、口型和导出流程。也可以直接导入 SRT。

## 自动分镜边界

分镜分为两层：`narrative_segments` 保存完整叙事/语义段，`shots` 保存真正出现在时间轴上的 Visual Shot。一个叙事段可以对应一个或多个视觉镜头。

- LLM 输入只有候选段 `id/text` 与少量前后文；输出严格限于 `semantic_type`、`visual_subject`、`importance`、`emotion` 和原样 `id/text`。
- LLM 输出包含时间、A/B、镜头数量或镜头切点会被程序拒绝并重试。
- 程序分别计算 `visual_value`（适合素材展示）与 `host_value`（值得主持人露脸）；`importance`、`emotion` 会直接增加人物价值。明确倾向先锁定，其余候选在全片统一选择，兼顾双价值并尽量贴近项目里的 B-roll 比例目标。
- 2 秒短段合并会分别按真实时长加权双价值，并保留 children 子语义；如果合并结果是 B-roll，素材词从最适合画面检索的 child 产生，不再只跟随最长段。
- A-roll 按时长分层：≤8 秒默认保持，8–12 秒允许 0–1 次变化，12–18 秒通常 1–2 次，超过 18 秒会标记过长语义段供复查。程序优先在停顿、句末、转折、新观点和主语变化处找切点，不用数学均分硬切。
- A-roll 变化会在保持长镜头、切近/切远和轻微推近/拉远中确定性选择，不会绕过全片分配临时改成 B-roll；无合适语义节点时允许保持单镜。连续 B-roll 只在人物价值足够高的自然语义节点回到主持人，没有合适节点时允许继续素材画面。
- 比例是软目标，语义与真实音频时间优先。人工修改镜头类型或边界仍是最终编辑决定。

已选素材、人工调整的镜头边界和已经完成的口型缓存会保留。失败后点击继续只补未完成阶段，不会默默改写时间线。

## Windows 用户推荐

普通用户请从 GitHub Release 下载：

`SceneFlow-Portable-v0.1.0-beta.1-Windows-x64.zip`

1. 解压到普通文件夹。
2. 双击 `SceneFlow.exe`。
3. 首次启动会自动检查并准备核心环境，然后打开默认浏览器进入 SceneFlow。
4. 在「连接与设置」填写 DeepSeek API Key 和 Pexels API Key。

不需要安装 Python、FFmpeg 或 uv，也不需要配置 PATH、pip 或 PowerShell。便携版内置 Python 3.12.10、FFmpeg/ffprobe、SceneFlow 基础依赖和 faster-whisper Base。MuseTalk 与 Wav2Lip 都按需安装到各自的独立环境；Wav2Lip 安装前必须阅读并确认第三方非商业使用限制。A-roll 未安装不会阻止核心工作台启动。

用户项目、设置和缓存保存在便携版文件夹的 `data/` 中。更新应用代码时不会删除 `data/`。

## Windows 源码安装（开发者）

推荐 NVIDIA 显卡，显存 8 GB 以上；MuseTalk 在 CPU 上可以启动，但不适合实际成片。Azure TTS V1 不占用显卡。当前自动安装器面向 Windows 10/11 x64。

1. 下载或克隆本仓库并解压到普通文件夹。
2. 双击 `安装工作台.bat`。安装器会自动下载项目独立的 Python 3.12.10 和 FFmpeg，不需要管理员权限，也不会修改系统 Python；随后安装 Azure TTS V1 客户端、MuseTalk、VAE、Whisper 和人脸检测模型。中断后可再次运行续传。
3. 双击 `启动工作台.bat`，浏览器打开 `http://127.0.0.1:8766`。
4. 在「连接与设置」填写 DeepSeek API Key 和 Pexels API Key，然后安装/校验 MuseTalk。

首次转录所选 faster-whisper 模型时会自动下载模型。默认使用轻量的 `base`；`small` 比 `base` 更重，兼顾速度与准确度，`large-v3` 更准确。

PowerShell 也可以直接运行源码安装脚本：

```powershell
.\安装工作台.ps1
.\启动工作台.ps1
```

只安装独立 Python、FFmpeg 和 Web 服务依赖，不下载口型模型：

```powershell
.\安装工作台.ps1 -SkipModels
```

## 连接与设置

普通用户只需理解三个选择：DeepSeek 填 Key、Pexels 填 Key、A-roll 选择一种。DeepSeek 官方地址和项目已验证模型由程序内置，不在默认设置页暴露：

```text
API 地址：https://api.deepseek.com
模型：deepseek-v4-flash
```

密钥写入 `data/private/settings.json`。`data/` 已在 `.gitignore` 中，项目 JSON、日志、错误信息和导出清单也不会写入或回显密钥。

Pexels 是默认素材源，Pixabay 是可选替代源。Whisper 模型、运行设备和 MuseTalk 显存档位收在折叠的「高级设置」内。所有密钥输入在重新打开时只显示遮罩；留空保存会保留原密钥。

A-roll 三档为：

- 轻量本地 · Wav2Lip：确认第三方限制后按需下载固定源码、官方 TorchScript checkpoint 与独立 Python 3.10 环境；支持图片、正向循环视频、连续 A-roll run 和断点续传。仅建议个人、研究和非商业用途。
- 高质量本地 · MuseTalk 1.5：复用现有独立引擎、断点续传安装器和缓存。
- 自定义工作流：可保存并测试 ComfyUI workflow_api.json / 节点配置，或 SceneFlow External A-roll API 配置。当前版本尚未开放这两类自定义适配器的自动生成协议，未就绪时 preflight 会在任务开始前引导回设置。

## 文字配音

Azure TTS V1 是新项目默认引擎，默认中文音色为 `zh-CN-XiaoxiaoNeural`。界面支持中文/英文音色与 0.85×–1.2× 常用语速。它按自然句子或较长文本连续请求，不会为了逗号分镜逐小句合成；每段最多重试三次，并只在音频可解码后写入缓存。完整音轨生成后才进行原稿/语音对齐和分镜。

文字配音只提供 Azure TTS V1。修改原稿、音色、语言或语速后，工作台会将配音标为需要重做。

## 独立 MuseTalk 口型

工作台直接调用固定版本的 MuseTalk 源码与官方 1.5 权重。一次任务会先加载模型，再连续处理所有待生成 A-roll，避免每个短镜头重新载入模型。静态人物图会保持单机位；人物循环视频按播客绝对时间连续向前取帧，保留原有眨眼和身体动作。

Wav2Lip 使用单独的 `engines/wav2lip-env`，不会升级或降级 MuseTalk 的 `media-env`。安装器固定源码 revision 和依赖版本，模型下载写入 `.part` 并支持 Range 续传，校验大小与 SHA256 后才替换正式文件。自动获取官方模型失败时，可在「连接与设置」选择从官方说明页下载的本地模型文件。

推理运行在独立 Python 进程中：

- 正常完成、取消或报错后，进程退出并释放显存。
- 每个镜头用人物文件、音频、起止时间和适配器版本生成缓存签名。
- 修改人物、音频或镜头边界只会让相关 A-roll 失效。
- 历史成片和历史口型文件保留，新结果通过时长与帧数校验后才替换当前引用。

为了降低 Windows 安装复杂度，工作台使用 OpenCV YuNet 检测正脸，并采用柔边椭圆将生成区域贴回原帧。人物素材应为清晰、无遮挡、单人正脸；多人、侧脸或遮挡严重的视频会明确报错。

## 目录与发布

```text
server.py / core.py       Web API 与整条任务链
storyboard.py             确定性的双价值、全片 A/B 分配、时长和视觉镜头规则
storyboard_rules.json     主链路实际读取的双价值、选择、时长与自然回场配置
speech_units.py           标点候选切分与原稿/Whisper 词时间对齐
static/                   本地 Web 界面
local_engines.py          Azure 配音与媒体引擎生命周期
azure_tts_worker.py       Azure TTS V1 分段请求、重试、缓存与 WAV 合并
aroll.py                  独立 MuseTalk 调度、缓存与校验
musetalk_worker.py        无 ComfyUI 的 MuseTalk 推理进程
engine_setup.py           可续传的源码、运行时与权重安装器
providers/                LLM、B-roll 与 A-roll Provider 注册、解析、状态和缓存身份
data/                     私有设置、项目、缓存、日志（不提交）
engines/                  下载的 MuseTalk 环境、源码与权重（不提交）
.runtime/                 自动安装的 Python/FFmpeg 引导工具与 FFmpeg（不提交）
```

提交公开仓库前运行：

```powershell
.\发布检查.ps1
```

它会拒绝常见密钥格式、机器专用绝对路径、4B/llama.cpp 残留和被误纳入 Git 的项目数据或模型文件。

## 许可

本仓库自有代码采用 MIT License。模型、FFmpeg、PyTorch 与下载的第三方源码仍受各自许可证和模型卡约束，详见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。发布源码不等于获得 Pexels 素材的再分发权；导出作品中的素材使用需遵守素材平台条款。

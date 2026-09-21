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
16:9、1:1 或 9:16 MP4、SRT 与镜头来源清单
```

## 成片里有什么

| 模块 | SceneFlow 会做什么 |
| --- | --- |
| 连续配音 | 可选 Azure TTS V1、豆包 SeedAudio 或本地 IndexTTS 2.5；声纹引擎支持上传本期参考声音。 |
| 真实时间轴 | faster-whisper 为文稿/音频生成词级时间，镜头边界跟随真实停顿与语义节点。 |
| 智能分镜 | 默认由 DeepSeek 判断语义与可视化对象，也可连接自定义 OpenAI 兼容服务；程序根据强语义信号和前后文选择人物或 B-roll，保留连续表达。 |
| 画面素材 | 根据具体可视化对象检索 Pexels 或 Pixabay，也能逐镜换片或导入本地图片/视频。 |
| 人物口型 | 可选择 LatentSync 1.6、Wav2Lip、MuseTalk 1.5、单人 InfiniteTalk Q8、AutoDL MiniMax H3，或配置通用 ComfyUI / 在线 API。前五种均可接入 A-roll 生成。 |
| 自动精剪 | 生成可审阅的 JSON Edit Plan；导出时可压缩长停顿、同步重映射画面与字幕、突出关键词、加入信息卡片，并对背景音乐自动压低。 |
| 最终交付 | 按本期设置导出 16:9、1:1 或 9:16 MP4、字幕 SRT，以及可追溯的镜头和素材来源清单。 |

## 技术范围

一个面向普通创作者的本地音频转视频应用。输入中文原稿或导入音频，工作台会完成配音/转录、语义分镜、B-roll 搜索、人物口型、字幕与 MP4 导出。

在「连接与设置」中选择所需服务：

- 分镜 AI：默认支持 DeepSeek，只填写 API Key；高级用户也可以配置 OpenAI 兼容服务。
- B-roll：支持 Pexels / Pixabay，选择素材源后只填写对应 API Key。
- A-roll：支持轻量本地、高质量本地、既有 ComfyUI 工作流、AutoDL 付费云端和通用自定义入口。Wav2Lip 需先确认第三方非商业使用限制；AutoDL H3 会上传人物图片与对应镜头音频并按实际生成秒数计费。

文字配音默认使用 Azure TTS V1（`edge-tts`），也可选择豆包 SeedAudio 声纹复刻或本地 IndexTTS 2.5。SeedAudio 会上传原稿和所选参考声音；IndexTTS 2.5 通过配置的本机 ComfyUI 运行。faster-whisper、LatentSync 1.6、MuseTalk 1.5 和 FFmpeg 都在本机工作。只有用户主动选择 AutoDL H3 时，人物图片和对应镜头音频才会发送到 AutoDL；通用自定义 A-roll 仍按所填服务配置工作。

## 能做什么

**文字一键成片**

1. 粘贴原稿，选择 Azure TTS V1、豆包 SeedAudio 或本地 IndexTTS 2.5 的声音与语速；使用声纹复刻时先上传参考声音。
2. 生成连续配音，再用 faster-whisper 将原稿标点对齐到真实词时间；Azure 失败后重试时会复用已完成段落。
3. DeepSeek 只做候选段语义分类，程序计算视觉/人物双价值，并按强语义信号与前后文决定 A/B；不再为凑占比或固定节奏额外插入人物镜头。
4. 程序按真实时间优先在标点/词边界切镜头，Pexels / Pixabay 每个检索词会取回 12 个候选，优先从本集未使用且时长足够的素材中随机选片。候选耗尽时会明确标记缺失，不会自动重复旧镜头。
5. 独立 MuseTalk 为 A-roll 生成人物口型。
6. FFmpeg 按本期画幅合成 16:9、1:1 或 9:16 MP4、字幕和导出清单。

**音频一键成片**

导入 MP3/WAV/M4A 后，本地 faster-whisper 先生成带真实词时间的标点候选段，再执行同一套规则分镜、素材、口型和导出流程。也可以直接导入 SRT。

## 自动分镜边界

分镜分为两层：`narrative_segments` 保存完整叙事/语义段，`shots` 保存真正出现在时间轴上的 Visual Shot。一个叙事段可以对应一个或多个视觉镜头。

- LLM 输入只有候选段 `id/text` 与少量前后文；输出严格限于 `semantic_type`、`visual_subject`、`importance`、`emotion` 和原样 `id/text`。
- LLM 输出包含时间、A/B、镜头数量或镜头切点会被程序拒绝并重试。
- 程序分别计算 `visual_value`（适合素材展示）与 `host_value`（值得主持人露脸）；`importance`、`emotion` 会直接增加人物价值。明确倾向直接锁定，较弱的语义段跟随前后一致的强语义；不再使用 B-roll 比例目标、开头结尾锚点或强制主持人回场。
- 2 秒短段合并会分别按真实时长加权双价值，并保留 children 子语义；如果合并结果是 B-roll，素材词从最适合画面检索的 child 产生，不再只跟随最长段。
- 连续 A-roll 作为一个完整镜头呈现，LatentSync、MuseTalk、Wav2Lip 和 InfiniteTalk 不再按时长或句子二次切碎。MiniMax H3 在 15 秒以内整段交给专用自动对口型工作流，每个任务沿用同一张主持人参考图；超过 15 秒时，只为满足服务限制而按最少段数拆分。
- 语义和真实音频时间是主线；B→A 仍会利用真实静音谷保护末字收音。人工修改镜头类型或边界仍是最终编辑决定。

已选素材、人工调整的镜头边界和已经完成的口型缓存会保留。失败后点击继续只补未完成阶段，不会默默改写时间线。

## 自动精剪与 Edit Plan

自动精剪位于「本期设置 → 高级制作设置」。它不会修改原音频、原字幕或原分镜，而是生成独立的 `sceneflow-edit-plan-v1` 计划：

- 长停顿按真实音频能量检测；阈值和停顿边缘保留量由项目设置控制。
- 每个保留区间同时记录原始时间和输出时间，A-roll、B-roll、素材入点、字幕与卡片使用同一份映射。
- 字幕关键词来自已确认的镜头检索词和视觉主体；信息卡片来自标题、高重要度、数据或引用语义。
- 导入背景音乐后可启用自动压低。人声始终保留为主轨，音乐在说话时通过 sidechain ducking 进一步降低。
- 导出目录额外包含 `edit-plan.json`。`manifest.json` 同时记录原时长、精剪后时长、实际画面来源和 BGM 使用情况。

修改镜头、停顿阈值、字幕样式或 BGM 后，旧计划会标记为需要刷新；正式导出前也会自动重新编译并验证时间连续性。

项目标题右侧可删除当前项目。删除前必须二次确认，运行中的项目不允许删除；确认后整个项目会先移到 `data/deleted-projects/`，而不是立即永久清空。

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

A-roll 生成方式为：

- 轻量本地 · Wav2Lip：确认第三方限制后按需下载固定源码、官方 TorchScript checkpoint 与独立 Python 3.10 环境；支持图片、正向循环视频、连续 A-roll run 和断点续传。仅建议个人、研究和非商业用途。
- 高质量本地 · LatentSync 1.6：通过本机 ComfyUI 运行固定 25fps 工作流；可调嘴型表现和生成质量，复用循环视频的绝对时间相位，相邻 A-roll 镜头只推理一次。RTX 2080 Ti 22GB 可运行，但速度明显慢于 MuseTalk。
- 高质量快速本地 · MuseTalk 1.5：独立本地引擎支持最高质量 FP32、官方下巴解析融合、人脸框平滑和低压缩中间文件；也可切换 FP16 高质量或旧版兼容融合。
- 单人影片 · InfiniteTalk Q8：调用已导入的单人 ComfyUI API 工作流，按真实音频帧数生成并取回视频。
- 云端高质量 · MiniMax H3 自动对口型：使用 AutoDL 提示词工作流 `minimax_h3_image_audio_to_video_v2_15s`。默认固定长镜头，也可选择克制切镜或自由切镜；超过 15 秒会自动拆段，最多 6 条并发生成。任务号保存在项目缓存中，重启或网络中断后续查同一任务，避免重复付费提交。完整说明见 [AutoDL H3](autodl-h3.md)。
- G 类 AI 生成镜头复用同一 AutoDL H3 端点的原始多参提交格式，支持最多 9 张参考图，使用独立生成 Prompt；不会调用 A-roll 的单参考对口型提示词，也不会强制主播身份、口播或口型。
- 自定义工作流：可保存并测试 ComfyUI workflow_api.json / 节点配置，或 SceneFlow External A-roll API 配置。当前版本尚未开放这两类自定义适配器的自动生成协议，未就绪时 preflight 会在任务开始前引导回设置。

## 文字配音

首次创建项目时使用 Azure TTS V1；以后新项目会继承上一期的配音引擎、声音、语速、参考声音、人物素材、画幅、画质和字幕设置，不复制上一期文稿、音频或成片。界面也提供豆包 SeedAudio 与 IndexTTS 2.5；两者可使用本期上传的参考声音，IndexTTS 2.5 固定走本地 ComfyUI。SeedAudio 密钥和 Index 地址保存在工作台私有设置中，空密钥保存不会删除已有值。

修改原稿、引擎、音色、参考声音、语言或语速后，工作台会将配音标为需要重做。完整音轨生成后仍会经过 faster-whisper 对齐，再按真实语音时间分镜。

工作台允许多个项目同时启动。配音、转录、分镜、素材和视频合成分别使用自己的队列；LatentSync、InfiniteTalk、MuseTalk、Wav2Lip 等本机人物口型共用 GPU 单路排队。在线 MiniMax H3 不占本机人物口型队列，可跨项目运行，全工作台最多同时保留 6 条 H3 云端任务。每个项目可单独选择人物口型方案，密钥和服务地址仍由工作台共用。项目侧栏会显示进行中或排队中的状态。

Whisper 选择「自动 · GPU 优先」时会在 Windows 上寻找本机可用的 CUDA 12 / cuDNN 9 运行库，包括已有 ComfyUI 的 Torch 运行库。项目会记录最终实际使用 `cuda` 还是 `cpu`；GPU 失败时才回退到 CPU。

## LatentSync 1.6 高质量口型

LatentSync 使用本机 `8189` 的 ComfyUI 与已验证的 `LatentSyncNode`。SceneFlow 会为每个连续 A-roll run 准备主持人视频和对应 16kHz 音频，提交固定 25fps 的工作流，取回后再按时间线裁切。默认嘴型表现为 1.5、生成质量为 20 步；闭嘴源素材或清晰口播可在「连接与设置」中提高到 2.0–2.5 和 30–40 步。参数参与缓存指纹，修改后会生成新结果并保留旧版历史。图片会先转成静态视频；循环视频按播客绝对时间正向循环，因此不同 A-roll run 不会每次从第一帧重新开始。

输出只有在节点执行完成、MP4 可完整解码、帧率为 25fps、帧数覆盖目标镜头后才写入项目。任务编号、原始输出和工作流记录保留在项目缓存中，服务重启后可以继续取回；短于目标镜头的结果不会用冻结尾帧冒充完整生成。

## 独立 MuseTalk 口型

工作台直接调用固定版本的 MuseTalk 源码与官方 1.5 权重。一次任务会先加载模型，再连续处理所有待生成 A-roll，避免每个短镜头重新载入模型。静态人物图会保持单机位；人物循环视频按播客绝对时间连续向前取帧，保留原有眨眼和身体动作。

「最高质量」默认使用 FP32、官方 `jaw` 人脸解析融合、5 帧居中人脸框平滑和 CRF 14 中间文件。在 RTX 2080 Ti 22GB 上，实测批大小 8 可以运行；峰值显存约 19.4GB。下巴活动范围默认 10，左右脸颊默认 90 / 90，音频前后文默认 2 / 2。修改这些参数会改变缓存签名并生成新结果，旧口型和旧成片不会被覆盖。

「高质量」保留官方解析融合但使用 FP16 和 CRF 16，速度与显存更友好。「兼容模式」使用原来的椭圆羽化与 CRF 18，供特殊素材或旧环境回退。25fps、批大小和编码质量不是口型表现滑块：25fps保持固定，批大小只影响速度与显存。

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
auto_edit.py              Edit Plan 编译、字幕/卡片映射与确定性校验
storyboard.py             确定性时长、内部切点与旧 A/B 兼容规则
storyboard_rules.json     主链路实际读取的双价值、强语义阈值、时长与收音保护配置
visual_director/          DeepSeek 理解 Schema、整片 Master Plan、视觉职责路由与节奏校验
motion/                   Remotion 兼容 Motion 参数路由与八类基础模板
speech_units.py           标点候选切分与原稿/Whisper 词时间对齐
static/                   本地 Web 界面
local_engines.py          Azure 配音与媒体引擎生命周期
azure_tts_worker.py       Azure TTS V1 分段请求、重试、缓存与 WAV 合并
aroll.py                  独立 MuseTalk 调度、缓存与校验
musetalk_worker.py        无 ComfyUI 的 MuseTalk 推理进程
engine_setup.py           可续传的源码、运行时与权重安装器
providers/                LLM、B-roll 与 A-roll Provider 注册、解析、状态和缓存身份
providers/generation/     G 类 MiniMax H3 生成场景 Prompt 与统一 Resolver
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

# SOLO 单人播客工作台

一个面向普通创作者的本地音频转视频应用。输入中文原稿或导入音频，工作台会完成配音/转录、语义分镜、B-roll 搜索、人物口型、字幕与 MP4 导出。

发布版需要两个用户自行填写的在线连接：

- DeepSeek API：只判断候选文字的语义类型、可视化对象、重要性与情绪。
- Pexels API：搜索并下载可用的 B-roll 视频。

文字配音默认使用 Azure TTS V1（`edge-tts`），无需 Azure Key，但需要联网并会把配音原稿发送到微软语音服务。Kokoro-82M 保留为可选的本地备用；faster-whisper、MuseTalk 1.5 和 FFmpeg 都在本机工作。语义分镜固定使用 DeepSeek API；工作台不会启动或访问外部工作流服务。

## 能做什么

**文字一键成片**

1. 粘贴原稿，默认选择 Azure TTS V1 的中文音色与语速；也可切换本地 Kokoro。
2. 生成连续配音，再用 faster-whisper 将原稿标点对齐到真实词时间；Azure 失败后重试时会复用已完成段落。
3. DeepSeek 只做候选段语义分类，程序按配置分数决定 A/B、叙事段合并和视觉镜头数量。
4. 程序按真实时间优先在标点/词边界切镜头，Pexels 自动匹配 B-roll。
5. 独立 MuseTalk 为 A-roll 生成人物口型。
6. FFmpeg 合成 16:9 MP4、字幕和导出清单。

**音频一键成片**

导入 MP3/WAV/M4A 后，本地 faster-whisper 先生成带真实词时间的标点候选段，再执行同一套规则分镜、素材、口型和导出流程。也可以直接导入 SRT。

## 自动分镜边界

分镜分为两层：`narrative_segments` 保存完整叙事/语义段，`shots` 保存真正出现在时间轴上的 Visual Shot。一个叙事段可以对应一个或多个视觉镜头。

- LLM 输入只有候选段 `id/text` 与少量前后文；输出严格限于 `semantic_type`、`visual_subject`、`importance`、`emotion` 和原样 `id/text`。
- LLM 输出包含时间、A/B、镜头数量或镜头切点会被程序拒绝并重试。
- A/B 加减分、阈值、2 秒短段合并、A/B 长镜拆分、连续 A/B 复查、软比例目标和 A-roll 变化策略都在 `storyboard_rules.json` 配置。
- A-roll 按时长分层：≤8 秒默认保持，8–12 秒允许 0–1 次变化，12–18 秒通常 1–2 次，超过 18 秒会标记过长语义段供复查。程序优先在停顿、句末、转折、新观点和主语变化处找切点，不用数学均分硬切。
- 变化会在保持长镜头、切近/切远、轻微推近/拉远和有具体可视主体时的短 B-roll 插入中确定性选择；无合适语义节点时允许保持单镜。长 B-roll 仍围绕同一可视化对象生成多个素材镜头。
- 比例是软目标，语义与真实音频时间优先。人工修改镜头类型或边界仍是最终编辑决定。

已选素材、人工调整的镜头边界和已经完成的口型缓存会保留。失败后点击继续只补未完成阶段，不会默默改写时间线。

## Windows 安装

推荐 NVIDIA 显卡，显存 8 GB 以上；MuseTalk 和备用 Kokoro 在 CPU 上可以启动，但不适合实际成片。Azure TTS V1 不占用显卡。当前自动安装器面向 Windows 10/11 x64。

1. 安装 [Python 3.12](https://www.python.org/downloads/) 并勾选 `Add Python to PATH`。
2. 安装 FFmpeg，并确认 `ffmpeg` 与 `ffprobe` 在 PATH 中。
3. 下载或克隆本仓库，双击 `安装工作台.bat`。安装器会安装 Azure TTS V1 客户端，并创建隔离媒体环境，从上游下载备用 Kokoro-82M、MuseTalk、VAE、Whisper 和人脸检测模型；中断后可再次运行续传。
4. 双击 `启动工作台.bat`，浏览器打开 `http://127.0.0.1:8766`。
5. 在「连接与设置」填写 DeepSeek API Key 和 Pexels API Key，然后安装/校验本地媒体引擎。

首次转录所选 faster-whisper 模型时会自动下载模型。设置里的 `small` 更快，`large-v3` 更准确。

PowerShell 也可以直接运行：

```powershell
.\安装工作台.ps1
.\启动工作台.ps1
```

只安装 Web 服务依赖、不下载生成模型：

```powershell
.\安装工作台.ps1 -SkipModels
```

## API 设置

默认使用 DeepSeek 官方兼容地址与模型：

```text
API 地址：https://api.deepseek.com
模型：deepseek-v4-flash
```

密钥写入 `data/private/settings.json`。`data/` 已在 `.gitignore` 中，项目 JSON、日志、错误信息和导出清单也不会写入或回显密钥。

Pexels 是默认素材源。Pixabay 保留为可选替代源；只配置 DeepSeek 与 Pexels 就能走完整的一键流程，Azure TTS V1 本身不需要填写 Key。

## 文字配音

Azure TTS V1 是新项目默认引擎，默认中文音色为 `zh-CN-XiaoxiaoNeural`。界面支持中文/英文音色与 0.85×–1.2× 常用语速。它按自然句子或较长文本连续请求，不会为了逗号分镜逐小句合成；每段最多重试三次，并只在音频可解码后写入缓存。完整音轨生成后才进行原稿/语音对齐和分镜。

已有 Qwen3-TTS 或 Kokoro 项目不会因为升级自动重配音。只有用户修改原稿、引擎、音色、语言或语速后，工作台才会将配音标为需要重做。

## 独立 MuseTalk 口型

工作台直接调用固定版本的 MuseTalk 源码与官方 1.5 权重。一次任务会先加载模型，再连续处理所有待生成 A-roll，避免每个短镜头重新载入模型。静态人物图会保持单机位；人物循环视频按播客绝对时间连续向前取帧，保留原有眨眼和身体动作。

推理运行在独立 Python 进程中：

- 正常完成、取消或报错后，进程退出并释放显存。
- 每个镜头用人物文件、音频、起止时间和适配器版本生成缓存签名。
- 修改人物、音频或镜头边界只会让相关 A-roll 失效。
- 历史成片和历史口型文件保留，新结果通过时长与帧数校验后才替换当前引用。

为了降低 Windows 安装复杂度，工作台使用 OpenCV YuNet 检测正脸，并采用柔边椭圆将生成区域贴回原帧。人物素材应为清晰、无遮挡、单人正脸；多人、侧脸或遮挡严重的视频会明确报错。

## 目录与发布

```text
server.py / core.py       Web API 与整条任务链
storyboard.py             确定性的语义评分、时长和视觉镜头规则
storyboard_rules.json     可调整的 A/B 分数、阈值、时长与连续性配置
speech_units.py           标点候选切分与原稿/Whisper 词时间对齐
static/                   本地 Web 界面
local_engines.py          Azure/Kokoro 配音与媒体引擎生命周期
azure_tts_worker.py       Azure TTS V1 分段请求、重试、缓存与 WAV 合并
aroll.py                  独立 MuseTalk 调度、缓存与校验
musetalk_worker.py        无 ComfyUI 的 MuseTalk 推理进程
engine_setup.py           可续传的源码、运行时与权重安装器
data/                     私有设置、项目、缓存、日志（不提交）
engines/                  下载的环境、源码与权重（不提交）
```

提交公开仓库前运行：

```powershell
.\发布检查.ps1
```

它会拒绝常见密钥格式、机器专用绝对路径、4B/llama.cpp 残留和被误纳入 Git 的项目数据或模型文件。

## 许可

本仓库自有代码采用 MIT License。模型、FFmpeg、PyTorch 与下载的第三方源码仍受各自许可证和模型卡约束，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。发布源码不等于获得 Pexels 素材的再分发权；导出作品中的素材使用需遵守素材平台条款。

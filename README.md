<div align="center">

# 🎬 SceneFlow — AI 播客视频自动生成工作台

### 一段文案，一段音频，就是你下一期视频播客。

**免费开源 · 支持本地运行 · 一键生成单人播客视频**

**不会剪辑也能用：输入一段文案或音频，SceneFlow 自动完成配音、视觉导演、A/B/E/R/M/G 分镜、人物口型、字幕和视频导出。**

当前正式执行 A / B / E / M / G 五条链路：A 走现有 A-roll，B 走库存素材，E 自动搜索真实网页并截图，M 生成数据动效片段，G 使用 MiniMax H3 的原始多参工作流生成非主播场景，不复用 A-roll 对口型 Prompt。R 保留 Schema 兼容，当前自动转为证据截图，失败后回退主播。

适合想做知识口播、单人播客、讲书、解说类视频，但不想学习复杂剪辑软件和 AI 工作流的用户。

*SceneFlow is an open-source AI podcast video generator for Windows that turns scripts or audio into complete videos with visual-director planning, A/B/E/R/M/G routing, local lip-sync, subtitles and MP4 export.*

让人物开口说话，自动配画面、加字幕、剪成片。<br>
你负责想说什么，SceneFlow 负责把它变成视频。

[![License: MIT](https://img.shields.io/badge/License-MIT-4b7045.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-3578b8.svg)](#-下载与启动)
[![Status: Beta](https://img.shields.io/badge/Status-Beta-e4ac45.svg)](https://github.com/fakezuumii-beep/SceneFlow/releases/tag/v0.1.0-beta.1)
[![GitHub Stars](https://img.shields.io/github/stars/fakezuumii-beep/SceneFlow?style=social)](https://github.com/fakezuumii-beep/SceneFlow)

[▶ 看生成案例](#-先看成片) · [📦 下载体验](https://github.com/fakezuumii-beep/SceneFlow/releases/tag/v0.1.0-beta.1) · [📖 使用文档](docs/USAGE.md) · [💬 反馈与建议](https://github.com/fakezuumii-beep/SceneFlow/issues)

</div>

![SceneFlow 一键播客生成：输入文案或音频，选择人物，点击生成](docs/showcase/01-create.png)

## 🚀 只需三步，一键生成视频

| ① 输入文案或音频 | ② 选择人物形象 | ③ 点击一键生成 |
| :---: | :---: | :---: |
| 粘贴想说的内容，或导入已有音频 | 使用内置主持人，或上传自己的图片 / 循环视频 | 自动完成人物口型、配图、字幕与 MP4 导出 |

**不用在多个工具之间来回折腾。准备好内容和人物，剩下的交给 SceneFlow。**

## ✨ 把“我有个想法”，变成“我做了一期节目”

SceneFlow 是一个面向普通用户的免费开源 AI 播客视频生成工具，支持在 Windows 本地运行。无论你想从文案生成视频，还是把现成音频生成视频，都可以用同一套自动播客视频流程完成。

想做知识分享、读书解说、观点表达，或者把已有的音频变成有人物、有配图的视频？

**输入文案或导入音频，选一个人物形象，点击「一键生成播客」。** 首次配置好所需服务后，SceneFlow 会自动完成配音或转录、自动分镜、A-roll/B-roll 编排、数字人口型同步、画面匹配、自动字幕和 MP4 导出。可以直接用内置主持人，也可以换成自己的图片或循环视频。

| 你给它 | 它帮你完成 |
| --- | --- |
| 📝 一段文案 | 生成配音，按真实语音时间自动分镜、自动剪辑 |
| 🎙️ 一段音频 | 转录内容，继续完成分镜与视频制作 |
| 🧑 一个主持人形象 | 让人物跟着声音开口说话 |
| 🌿 想讲的内容 | 自动搜索匹配的素材，与人物镜头交替呈现 |
| 🎬 一次点击 | 合成人物、画面、声音与字幕，导出 16:9、1:1 或 9:16 MP4 |

生成之后也能继续改：换配图、重新生成人物镜头、调整镜头边界，再导出你满意的版本。任务中断后，可以继续补齐未完成的步骤。

在「高级制作设置」中还可以启用**自动精剪**：SceneFlow 会先生成一份可下载的 Edit Plan，按真实音频识别并压缩长停顿，同时重映射画面、字幕和素材入点；也可开启关键词高亮、标题 / 信息卡片，并导入背景音乐自动压低。原始音频和原分镜不会被覆盖，只有导出成片使用精剪时间线。

> **免费与本地运行说明：** SceneFlow 自有代码免费开源，提供 LatentSync 1.6 本地高质量口型方案，并保留 MuseTalk 作为无需外部 ComfyUI 的默认与快速回退；转录、口型推理与视频合成可在本机完成。默认文字配音需要联网，分镜 AI 和素材检索也取决于所选服务；第三方 API 可能收费。“支持本地运行”不代表默认配置完全离线，也不代表所有外接服务免费。

## 👤 适合谁使用？

如果你想做：

- 单人播客视频
- 知识口播
- 讲书 / 解说
- AI 数字人视频
- 文案自动生成视频
- 音频自动配画面

但又不想自己处理复杂的分镜、B-roll 搜索、人物口型和字幕，SceneFlow 就是为这种工作流准备的。

## ▶ 先看成片

**下面两段都是作者用 SceneFlow 在本地运行生成的案例，人物口型使用 MuseTalk。** 没有用付费云端视频模型替代演示中的人物生成；部分联网服务的使用范围见上方说明。

点击播放器的 **▶** 即可直接观看；两个案例并排展示，也支持声音、进度拖动和全屏播放。

<table>
<tr>
<th width="50%">示例 1 · 约 36 秒</th>
<th width="50%">示例 2 · 约 37 秒</th>
</tr>
<tr>
<td>

https://github.com/user-attachments/assets/c6d29653-15c4-4c25-b912-faec5f52b84f

</td>
<td>

https://github.com/user-attachments/assets/55a74a21-31e8-45e3-9542-f78d23a54b78

</td>
</tr>
<tr>
<td align="center">MuseTalk 本地口型 · <a href="https://github.com/fakezuumii-beep/SceneFlow/raw/refs/heads/main/docs/showcase/demo-1.mp4">下载高清原片</a></td>
<td align="center">MuseTalk 本地口型 · <a href="https://github.com/fakezuumii-beep/SceneFlow/raw/refs/heads/main/docs/showcase/demo-2.mp4">下载高清原片</a></td>
</tr>
</table>

*在线播放版经过体积优化，保留完整内容与音频；上方下载链接提供原始导出文件。*

## 🖼️ 从输入到成片，四张图就看懂

**① 配好连接，让分镜、素材和人物一起工作**

分镜 AI、素材源、人物口型集中设置。MuseTalk 1.5 支持 FP32 与官方人脸解析的最高质量模式，也可选择 LatentSync 1.6、InfiniteTalk、Wav2Lip、AutoDL MiniMax H3 或自定义工作流。

![连接与设置：分镜模型、素材搜索 API、MuseTalk 本地人物口型](docs/showcase/02-settings.png)

**② 输入内容，选好人物，一键开工**

粘贴文案或导入音频，选择内置人物或自己的形象，再点击生成。准备好内容后，就不用挨个工具来回搬素材了。

![SceneFlow 创作入口：输入文案或音频、选择人物形象、一键生成视频](docs/showcase/01-create.png)

**③ 先看整体，再看节奏**

生成后直接预览。人物镜头和素材镜头按时间排列，哪里该让主持人出镜、哪里该给观众看画面，一眼就能检查。

![成片预览、字幕与人物和素材镜头时间线](docs/showcase/03-preview.png)

**④ 自动生成之后，每一镜仍然由你决定**

配图不合适就替换，人物镜头不满意就重新生成，还能导入本地图片和视频。自动化帮你完成初稿，编辑界面帮你把作品打磨到满意。

![逐镜编辑：替换配图、导入本地素材、重新生成人物口型](docs/showcase/04-edit.png)

*图解中的个别界面来自早期 SOLO 命名版本，项目现名为 SceneFlow。图中第三方模型、商用和外接能力的简述，请结合下方版本说明与许可证文档阅读。*

## 📦 下载与启动

### Windows 便携版：推荐第一次体验的朋友使用

**[前往 Releases 下载 Windows 便携版 →](https://github.com/fakezuumii-beep/SceneFlow/releases/tag/v0.1.0-beta.1)**

1. 下载发布页中的 Windows x64 便携 ZIP，解压到普通文件夹。
2. 双击 `SceneFlow.exe`，按启动提示完成环境检查，浏览器会打开工作台。
3. 在「连接与设置」配置分镜 AI 和素材源，并安装 / 校验 MuseTalk。
4. 回到首页，输入文案或导入音频，选好人物，点击「一键生成播客」。

便携版包含基础 Python、FFmpeg 与 Whisper Base；人物口型引擎和相关模型按需安装，首次准备需要下载。推荐使用 NVIDIA 显卡；具体安装、显存与配置说明请看 [完整使用文档](docs/USAGE.md)。

### 源码运行

克隆或下载仓库后，在 Windows 下依次双击：

```text
安装工作台.bat
启动工作台.bat
```

启动后访问 `http://127.0.0.1:8766`，按同样步骤配置服务。详细参数、目录结构和排错入口见 [使用与技术说明](docs/USAGE.md)。

## 👄 关于口型效果，说点实在的

做这个项目，是想让更多人能用上自动播客制作。**SceneFlow 已支持 LatentSync 1.6 本地高质量人物口型同步，并保留 MuseTalk 作为默认、快速预览与回退。** 两者都可以把主持人循环视频与配音合成为 A-roll 人物讲话镜头，不需要按次购买云端视频生成。

代价也很直接：有些镜头看起来难免有一点“假”，嘴部融合、表情和动作自然度还有提升空间。上面的案例就是当前本地方案的实际效果，大家可以先看，再决定是否适合自己的内容。

如果追求更好的画面，后续会继续完善外接工作流。**下面是作者在自己的素材与工作流中的主观实测体验，不是统一条件下的模型排名，也不代表当前版本都已接通：**

- **LatentSync 1.6：** 已接入本机 ComfyUI 的固定工作流，口型质量优先；RTX 2080 Ti 22GB 可运行，但速度明显慢于 MuseTalk。
- **ComfyUI + InfiniteTalk：** 可从人物图片生成包含表情和细微动作的新视频；本地推理无需按次支付云端视频生成费。
- **AutoDL MiniMax H3 自动对口型：** 已接入专用图片 + 音频同步工作流，支持 480P/768P/1080P 横竖屏；SceneFlow 会自动按 15 秒以内分段、续查任务、立即下载并校验后拼回 A-roll。每个任务沿用同一张主持人参考图，人物、背景和动作稳定性仍取决于输入素材与云端模型。
- **Seedance 等在线模型：** 预算充足的朋友也可以探索，成片质感有机会再上一个档次；实际效果、费用和可用能力取决于服务与接入方式。

**当前版本状态：** LatentSync 1.6、MuseTalk、Wav2Lip、单人 InfiniteTalk Q8 与 AutoDL MiniMax H3 自动对口型均已接入 A-roll 生成；通用 ComfyUI / 在线 API 仍只支持保存配置与测试连接。H3 会上传人物图片和对应镜头音频并按生成秒数计费；Wav2Lip 有第三方非商业使用限制。详情见 [AutoDL H3 使用说明](docs/autodl-h3.md) 与 [第三方说明](THIRD_PARTY_NOTICES.md)。

## 🚧 先把一个人的节目做好，再让更多角色登场

这个项目最初想做的是**双人播客**。实际做起来，发现双人对话、人物一致性和镜头调度比想象中更麻烦，所以先做一个单人版本试试水，把从内容到成片的流程跑顺，也让大家先用起来。

接下来想继续做的方向：

- [x] 单人播客：文案 / 音频 → 人物口型 + 配图 + 字幕 + 成片
- [x] 成片预览、逐镜换素材、人物镜头重生成
- [x] [单人 InfiniteTalk Q8：已有 ComfyUI 工作流自动生成与取回 A-roll](docs/infinitetalk.md)
- [x] [AutoDL MiniMax H3：图片 + 原音频自动生成、续查、下载并拼回 A-roll](docs/autodl-h3.md)
- [ ] 完善其他通用 ComfyUI 与在线视频模型的自动生成接入
- [ ] 双人播客：对话、角色切换与镜头配合
- [ ] 多角色内容与短剧等更丰富的创作形式

这些是后续方向，还没有承诺发布时间。欢迎在 [Issues](https://github.com/fakezuumii-beep/SceneFlow/issues) 告诉我：你最想先用哪一个？也欢迎带上遇到的问题和你的生成案例。

## ⭐ 如果你也想让创作少一点折腾

**给 SceneFlow 点一个 Star，陪它从单人播客长成双人对话，再走向短剧。**

Star 能让更多人发现它，也让我知道这个方向值得继续做。欢迎提交 Issue、贡献代码，或把你用它做的节目分享出来。

## 🤖 给 AI / Agent 使用

如果你使用 Codex、Claude Code 或其他 AI Agent，可以让它先阅读：

[`docs/skill/SKILL.md`](docs/skill/SKILL.md)

帮助 Agent 快速理解 SceneFlow 能做什么、适合什么任务。

## 致谢与许可

感谢 LatentSync、MuseTalk、Wav2Lip、MiniMax H3、faster-whisper、FFmpeg、edge-tts 等项目，以及 AutoDL 和其他素材服务平台。SceneFlow 把这些能力串成一条面向创作者的制作流程。

本仓库自有代码使用 [MIT License](LICENSE)。第三方代码、模型及素材仍遵循各自许可证与平台条款，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

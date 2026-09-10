<div align="center">

# 🎬 SceneFlow

### 一段文案，一段音频，就是你下一期视频播客。

**免费开源 · 支持本地运行 · 一键生成单人播客视频**

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

想做知识分享、读书解说、观点表达，或者把已有的音频变成有人物、有配图的视频？

**输入文案或导入音频，选一个人物形象，点击「一键生成播客」。** 首次配置好所需服务后，SceneFlow 会自动完成配音或转录、分镜、人物口型、画面匹配、字幕和 MP4 导出。可以直接用内置主持人，也可以换成自己的图片或循环视频。

| 你给它 | 它帮你完成 |
| --- | --- |
| 📝 一段文案 | 生成配音，按真实语音时间安排镜头 |
| 🎙️ 一段音频 | 转录内容，继续完成分镜与视频制作 |
| 🧑 一个主持人形象 | 让人物跟着声音开口说话 |
| 🌿 想讲的内容 | 自动搜索匹配的素材，与人物镜头交替呈现 |
| 🎬 一次点击 | 合成人物、画面、声音与字幕，导出 16:9 MP4 |

生成之后也能继续改：换配图、重新生成人物镜头、调整镜头边界，再导出你满意的版本。任务中断后，可以继续补齐未完成的步骤。

> **免费与本地运行说明：** SceneFlow 自有代码免费开源，默认提供 MuseTalk 本地口型方案，转录、口型推理与视频合成可在本机完成。默认文字配音需要联网，分镜 AI 和素材检索也取决于所选服务；第三方 API 可能收费。“支持本地运行”不代表默认配置完全离线，也不代表所有外接服务免费。

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

分镜 AI、素材源、人物口型集中设置。默认提供 MuseTalk 本地方案，也保留其他引擎与自定义工作流的配置入口。

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

做这个项目，是想让更多人能用上自动播客制作。所以这一版先把 **MuseTalk 作为默认的本地口型方案**：不用为了生成人物说话就先购买云端视频服务。

代价也很直接：有些镜头看起来难免有一点“假”，嘴部融合、表情和动作自然度还有提升空间。上面的案例就是当前本地方案的实际效果，大家可以先看，再决定是否适合自己的内容。

如果追求更好的画面，后续会继续完善外接工作流。**下面是作者在自己的素材与工作流中的主观实测体验，不是统一条件下的模型排名，也不代表当前版本都已接通：**

- **ComfyUI + InfiniteTalk：** 在作者目前测试的几种方案里，人物说话的整体效果最好，可作为更高质量本地工作流的探索方向；本地推理无需按次支付云端视频生成费。
- **LTX / MiniMax：** 作者测试中出现过一些人物偏移，仍需根据素材和工作流继续调试。
- **Seedance 等在线模型：** 预算充足的朋友也可以探索，成片质感有机会再上一个档次；实际效果、费用和可用能力取决于服务与接入方式。

**当前版本状态：** MuseTalk 与 Wav2Lip 已接入一键生成；ComfyUI / 在线 API 目前支持保存配置与测试连接，自动提交生成、注入素材和取回视频尚待开放。Wav2Lip 有第三方非商业使用限制，模型与素材的使用范围请查阅 [第三方说明](THIRD_PARTY_NOTICES.md)。

## 🚧 先把一个人的节目做好，再让更多角色登场

这个项目最初想做的是**双人播客**。实际做起来，发现双人对话、人物一致性和镜头调度比想象中更麻烦，所以先做一个单人版本试试水，把从内容到成片的流程跑顺，也让大家先用起来。

接下来想继续做的方向：

- [x] 单人播客：文案 / 音频 → 人物口型 + 配图 + 字幕 + 成片
- [x] 成片预览、逐镜换素材、人物镜头重生成
- [ ] 完善 ComfyUI 与在线视频模型的自动生成接入
- [ ] 双人播客：对话、角色切换与镜头配合
- [ ] 多角色内容与短剧等更丰富的创作形式

这些是后续方向，还没有承诺发布时间。欢迎在 [Issues](https://github.com/fakezuumii-beep/SceneFlow/issues) 告诉我：你最想先用哪一个？也欢迎带上遇到的问题和你的生成案例。

## ⭐ 如果你也想让创作少一点折腾

**给 SceneFlow 点一个 Star，陪它从单人播客长成双人对话，再走向短剧。**

Star 能让更多人发现它，也让我知道这个方向值得继续做。欢迎提交 Issue、贡献代码，或把你用它做的节目分享出来。

## 致谢与许可

感谢 MuseTalk、Wav2Lip、faster-whisper、FFmpeg、edge-tts 等项目，以及提供素材服务的平台。SceneFlow 把这些能力串成一条面向创作者的制作流程。

本仓库自有代码使用 [MIT License](LICENSE)。第三方代码、模型及素材仍遵循各自许可证与平台条款，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

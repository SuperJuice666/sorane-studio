# 导入一首歌

导入器把录音处理成播放器使用的歌曲包。使用者提供文件与版本线索；Agent 查找和核对歌词、整理读音与乐段、处理模型疑点，再检查成品。过程保存在独立任务中，可以中断后继续。

## 交给 Agent

在能读取本项目、运行命令、搜索资料并检查音频的 Agent 中，发送：

> 请按 docs/agent-import.md 导入这个音频：`音频文件路径`。从文件名和标签识别曲名、歌手及版本，在 work/ 中创建独立任务。完成资料核对、对齐、返修和本地预览；满足检查要求后加入本地曲库。交付新歌包、本机预览、检查记录及待核实内容。

Agent 应自行创建和推进任务，分词、读音和时间标注由任务流程完成。宿主的工具能力决定资料和听音检查范围；交付时列明已完成步骤和待接手环节。

歌词分句默认沿用选定权威来源的原始分行。Agent 在 sources.json 中保存 lineSource 和 canonicalLines；导入器会逐行校验，拒绝未经处理的拆句或合句。播放器的屏幕折行作为显示布局处理，练习句数由来源分行确定。录音版本差异与用户指定的改动须另记依据。

歌词文字与分句优先采用版本吻合的 AWA 原始分行。分段采用歌曲结构：依据音乐变化、重复结构和实际录音划分主歌、副歌、桥段等；已有人工核对分段优先保留。将核对后的结构记录为 canonicalSections（startLine、endLine 为从1开始的含首尾句号，name 为段名），并单独保存 sectionSource 与判定依据。分句来源与结构依据分别记录。

新 Agent 的接手材料包括[执行提示词](../prompts/import-agent.md)、[经验与故障判断](import-lessons.md)、[文字分词规则](../prompts/lyrics.md)和[复核规则](../prompts/review.md)。经验文档归纳来源冲突、转写幻觉、重复段、长尾、回声和播放器错位的处理顺序，为接手者提供处理依据。

## 首次配置

导入工作站使用 FFmpeg、Demucs、SOFA 代码和检查点，见 [模型配置](models.md)。可以用配置中的 vocals 指定已有的等长人声轨来替代分离步骤。日语读音使用本机 VOICEVOX Engine，默认连接 127.0.0.1:50021；选择符合使用范围的声库和 speaker ID。

复制 examples/import-config.json 到 work/import-config.json，填写本机路径。modelPython 留空代表当前解释器，建议使用模型环境解释器的绝对路径。模型路径相对仓库根目录。narration.provider 默认为 voicevox；也可设为 edge，voice 指定声库（如 ja-JP-NanamiNeural）。Edge 适配需要安装 edge-tts，三档速度独立合成，词时间来自服务返回的 WordBoundary，显示词落在同一服务词内部时按假名位置插值；原始边界与删减静音记录保存在 narration-queries。纯原曲包可设为 none；读音服务报错后，任务保留日志，修复配置后继续。

## 启动和恢复

Agent 可以自己创建任务，也可手动创建：

```sh
python -m song_import.import_job start "歌手 - 曲名.ogg" --job work/my-song --id my-song --title "曲名" --artist "歌手" --config work/import-config.json
```

将生成的 work/my-song/TASK.md 交给 Agent，以后让它“继续这个任务”即可。已有 Agent 命令行可以配置 agentCommand 参数数组：其中 {task} 替换为任务说明绝对路径，{job} 替换为任务目录。例如自己的启动脚本可配置为 `["python", "你的启动脚本.py", "--task", "{task}"]`。导入器通过进程参数数组调用配置好的宿主命令。

TASK.md 保存创建时的完整执行提示词与文档入口，job.json 保存对应的 agentInstructionsSha256。可选文本 API 的 .usage.json 另记 instructionSha256 和 inputSha256，便于追溯同一模型为什么产生不同结果。哈希用于追踪输入；模型输出另存为每轮候选。

```sh
python -m song_import.import_job agent work/my-song
python -m song_import.import_job status work/my-song
python -m song_import.import_job doctor work/my-song
```

agent 只是宿主入口，模型选择、工具权限和付费额度由宿主管理。也可以在已有对话中持续执行。

## 处理过程

| 阶段 | 自动完成                             | Agent 完成                                 |
| ---- | ------------------------------------ | ------------------------------------------ |
| 资料 | 保存录音副本、指纹、任务说明         | 核对来源和版本，整理歌词、读音、译文、乐段 |
| 人声 | 规范格式、分离人声、检查分轨长度     | 检查泄漏、辅音丢失和时间偏移               |
| 对齐 | 原速全曲 SOFA、上下文及 CTC 比较     | 解释疑点、修正文字或边界、重跑             |
| 复核 | 全曲试听页、疑点列表、过期报告检查   | 完整试听、核对句界、记录依据               |
| 资源 | 三档原曲、分块、三档合成读音与时间轴 | 检查语义停顿和读音                         |
| 成品 | 独立预览、资源校验、本地安装         | 检查切换、循环、拖动及手机首次播放         |

用 run 推进自动阶段，中断后仍使用同一命令。成功阶段按输入和输出指纹复用；修改草稿、来源、模型或检查点后会重新生成依赖结果。每次尝试放在 runs/，成功产物与失败日志分别保留，任务锁保证单进程写入。

## 查看和验收

```sh
python -m song_import.import_job run work/my-song
python -m song_import.preview work/my-song --port 8090
```

打开 <http://127.0.0.1:8090/review.html>，直接从全曲听起，再集中检查标记的词。status 返回的 preview 目录含独立音源预览，对该目录下的 site/ 使用同一个预览命令即可检查音源和时间标注；实际播放器交互在 Sorane Player 中检查。预览服务器支持音频 Range 跳转，监听本机回环地址。work/ 保存原曲、来源及处理日志，供本地复核。

```text
job.json                    录音指纹、曲名、配置
TASK.md                     Agent 接手说明
sources.json / sources/     来源及版本依据
draft.json                  核对后的文字、读音和结构
runs/                       模型及媒体结果、日志、成品预览
review.html                 全曲和人声复核
reviewed.json               修订后的时间标注
alignment-review.json       对齐问题处理依据
playback-review.json        成品检查结果
events.jsonl                阶段记录
```

Agent 按 [执行规范](agent-import.md) 填写报告，再完成安装：

```sh
python -m song_import.import_job accept work/my-song --report work/my-song/alignment-review.json
python -m song_import.import_job run work/my-song
# 在预览中检查成品，然后填写 playback-review.json。
python -m song_import.import_job install work/my-song --report work/my-song/playback-review.json
# 在 Sorane Player 项目根目录执行：
python -m lyric_player build
python -m server
```

歌曲加入 data/songs/my-song/；同名歌曲存在时停止安装，更新旧歌需另外比较和迁移。构建生成本地网站，发布按 Sorane Player 的部署说明操作。

报告通过指纹关联输入、对齐结果和成品。资料或音频更新后，重新完成受影响的检查；听音记录包含音源、时间窗口和检查结论。待听项目随候选一同交付。

源码包含程序、提示词、配置示例与文档。歌曲、歌词和模型由使用者按相应许可准备；任务资料保存在本机，发送给云端模型的内容由调用者选择。

---
name: sorane-studio
description: 将用户提供的日语歌曲录音制作成 Sorane Player 歌曲包。核对歌词和录音版本，整理读音与乐段，运行人声分离及 SOFA/CTC 对齐，依据证据返修并生成可复核的音频资源。适用于新增或继续导入歌曲。
---

# Sorane Studio

以本文件所在目录为项目根目录。读取仓库中的配置和文档，从用户提供的录音建立任务。

1. 读取 [执行规范](docs/agent-import.md)与[经验和故障判断](docs/import-lessons.md)。首次使用另读[安装与模型配置](docs/models.md)；命令参数见[导入流程](docs/import.md)。
2. 从文件名和标签识别曲名、歌手、版本；使用 `python -m song_import.import_job start` 创建独立任务。已有任务读取 `TASK.md`、`job.json` 并运行 `status` 继续处理。运行 `doctor`，按实际配置补齐依赖。
3. 核对歌词来源，保存原始页面、提取文本及指纹。按版本吻合的 AWA 原始分行锁定歌词和句界；分段采用歌曲结构，保留已有人工复核段落。整理文字时读取 [lyrics 提示词](prompts/lyrics.md)。
4. 推进 `run`：原速全曲分离、SOFA、CTC 与上下文比较。核查重复段、长音、回声、间奏和版本差异；修订应有声学依据，并检查相邻词和句的边界。疑点处理使用[复核规则](prompts/review.md)，保存每轮候选。
5. 使用本机 `song_import.preview` 查看全曲与疑点。完成对齐报告后 `accept`，再 `run` 生成三档原曲、三档合成读音和分块。时间都以原曲绝对秒数为基准。
6. 核对资源与包格式，在真实 Sorane Player 检查切换、循环、拖动和目标设备后填写成品报告。符合门槛再 `install` 到用户指定的本地曲库；部署只按用户明确范围执行。

宿主负责搜索、内容判断和可用的听音工具；程序负责可恢复执行、媒体制作、指纹和报告校验。`song_import.assist` 提供可选的文本整理接口；声学时间由音频模型测量。

来源或听音待核实时，交付候选、具体问题和优先试听窗口；检查记录对应实际执行情况。交付说明包含歌曲包路径、来源与版本、实际模型和可得 token 用量、修改及遗留问题。宿主用量字段缺失时记“未提供”。格式兼容关系见 [relationship](docs/relationship.md)。

# Sorane Studio

把录音制作成 [Sorane Player](https://github.com/SuperJuice666/sorane-player) 歌曲包的 AI Skill。包括歌词与版本核对、分词读音、歌曲结构、人声分离、SOFA / CTC 对齐、疑点返修、三档音频和读音、分块打包及复核。

[体验歌曲包的播放效果](https://superjuice666.github.io/sorane-player/?song=strings) · STRiNGS — THE ORCHESTRA TOKYO

<img src="https://raw.githubusercontent.com/SuperJuice666/sorane-player/main/docs/images/strings-reading.gif" width="240" alt="STRiNGS 歌曲包在 Sorane Player 中逐句播放读音" />

`SKILL.md` 提供 Agent 入口，`song_import/` 执行处理任务，`docs/` 和 `prompts/` 说明流程与判断规则。完整目录可作为 Skill 安装到支持本地工具调用的 Agent 中。

## 安装

需要 Python 3.12、FFmpeg；音频推理环境按[模型配置](docs/models.md)安装。完整下载本项目，进入根目录，再创建自己的 Python 环境。日常命令均在根目录运行；安装时保留完整目录，供程序读取提示词和配置。

```sh
git clone https://github.com/SuperJuice666/sorane-studio.git
cd sorane-studio
python -m venv .venv-models
# 激活环境，然后按 docs/models.md 安装适合硬件的推理依赖。
python -m song_import.import_job --help
python -m song_import.contract
```

将整个项目目录作为 Skill 安装到宿主的技能目录，目录名使用 `sorane-studio`；也可以让已有 Agent 直接读取根目录的 [SKILL.md](SKILL.md)。宿主 Agent 提供搜索、命令执行和听音能力。可选文本 API 通过环境变量配置，见模型配置；文字整理可使用宿主模型或指定的文本 API。

## 使用

给 Agent 音频路径，并告诉它：

> 使用 Sorane Studio 导入这个音频。从文件名和标签核对曲名、歌手与版本，在独立任务中完成资料核对、对齐、返修与本地预览。保留来源和修改依据，交付歌曲包、本机预览和复核记录。

Agent 按 [执行规范](docs/agent-import.md)创建可恢复任务，检查依赖、运行模型、核对异常并返回结果。词和句的时间由声学对齐生成，Agent 负责核查与返修。首次配置、命令和报告说明见[导入流程](docs/import.md)。交付包括候选结果、检查记录和待核对项；资料、对齐、听音与设备检查分别记录。

歌词文字和分句优先采用版本吻合的 AWA 原始分行。段落按歌曲结构判断，已有人工核对分段优先保留。

## 交付给播放器

```sh
python -m song_import.import_job install work/my-song --report work/my-song/playback-review.json --library /path/to/sorane-player/data/songs
```

安装将通过检查的新歌复制到指定曲库；同名歌曲进入更新流程。然后在播放器仓库运行 `python -m lyric_player build`。默认安装目录为本项目 `data/songs/`，也可将完整歌曲包单独交付。
内置预览用于检查音源、速度、句界和词标注；分块、循环和设备检查在 Sorane Player 中完成。

## 开发

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests
python -m ruff check song_import tests
python -m ruff format --check song_import tests
python -m song_import.contract
```

FFmpeg 在 PATH 时，回归测试会真实生成媒体文件；也可设置 `TEST_FFMPEG`。对齐与 TTS 回归使用固定夹具，歌曲听感通过实际试听检查。

发布前将 `PLAYER_SOURCE` 设为下载的 Sorane Player 源码目录，再运行测试。跨项目测试会用真实 FFmpeg 制作三档音频和分块，然后交给播放器校验、构建，并核对时间标记及资源。独立开发时该项显示为跳过；联调时设置此变量启用。

音乐包格式由 Sorane Player 维护。本仓库固定格式 1.0.0 / schemaVersion 1，携带可离线运行的校验器快照及指纹。同步规则见[项目关系](docs/relationship.md)。

代码采用 MIT。模型、声库和导入内容的许可见[第三方组件](docs/third-party.md)。

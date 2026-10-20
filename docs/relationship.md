# 项目协作与版本

本项目与 [Sorane Player](https://github.com/SuperJuice666/sorane-player) 分别维护和发布，通过歌曲包交接。

Sorane Player 负责在线练习、曲库构建及格式定义。Sorane Studio 负责工作站上的 Agent 流程、模型处理与歌曲包交付。播放器与制作工作站通过歌曲包交接，可分别部署在服务器和本地工作站。

当前接口为 schemaVersion 1，格式修订 1.0.0。歌曲包包含 `song.json` 与所有相对路径资源；词和句使用原曲绝对秒数，变速资源按比率换算，分块以绝对采样数索引。源码版本与格式版本分别管理。

格式唯一维护位置是 Sorane Player 的 `docs/data-format.md`、`lyric_player/schema.py` 和 `format-version.json`。Sorane Studio 的 `contract.json` 固定校验器和规范的 SHA256，并携带相同快照供离线检查。格式变更按下述升级流程同步。

格式升级先在播放器提交规范、校验器和兼容测试，标注版本；导入器随后显式更新快照及 contract.json，再用新生成歌曲包通过播放器真实校验和构建。已有字段含义改变必须升 schemaVersion；仅增加可选字段仍应更新格式修订。保留旧版本包支持时应提供测试。

```sh
# 在 Sorane Studio 根目录：检查固定快照，或与下载的播放器源码比对。
python -m song_import.contract
python -m song_import.contract --player /path/to/sorane-player
```

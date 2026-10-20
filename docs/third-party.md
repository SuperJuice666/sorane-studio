# 第三方组件

| 组件                                                                               | 用途             | 范围                                   |
| ---------------------------------------------------------------------------------- | ---------------- | -------------------------------------- |
| [SOFA](https://github.com/qiuqiao/SOFA)                                            | 歌声音素对齐     | 外部源码，MIT；适配器固定修订          |
| [akm_ja_v001](https://github.com/ariikamusic/SOFA_Models/releases/tag/akm_ja_v001) | 日语歌声检查点   | 由使用者另行下载；许可按作者说明       |
| [PyTorch](https://pytorch.org/) / [TorchAudio](https://github.com/pytorch/audio)   | 模型推理及 CTC   | 工作站模型推理环境                     |
| [Demucs](https://github.com/facebookresearch/demucs)                               | 可选人声分离     | 外部命令行工具，未随仓库打包           |
| [FFmpeg](https://ffmpeg.org/)                                                      | 变速、编码和分块 | 外部程序；发行版本的许可取决于构建选项 |
| [Ruff](https://docs.astral.sh/ruff/)                                               | 开发检查         | 版本固定于依赖文件                     |

上游模型和媒体资料按各自许可取得与使用。源码附带本项目编写的示例文字；示例和代码采用 MIT 许可。安装依赖时保留其许可文件。

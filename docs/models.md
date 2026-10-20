# 模型和外部服务

导入工作站使用 Demucs 分离人声、SOFA / CTC 测量音素时间、VOICEVOX 合成读音。Agent 或使用者负责歌词整理、翻译与复核。

## SOFA 环境

适配器使用 [SOFA](https://github.com/qiuqiao/SOFA) 的 `584d6b9` 修订和 [akm_ja_v001 日语歌声模型](https://github.com/ariikamusic/SOFA_Models/releases/tag/akm_ja_v001)。适配器按这一修订调用上游接口，升级时执行兼容检查。

建议单独建立 Python 3.12 环境：

```sh
python -m venv .venv-models
# 激活环境后，按自己的 CPU / CUDA 平台安装匹配的 PyTorch wheels。
python -m pip install torch==2.8.0 torchaudio==2.8.0
python -m pip install -r requirements-models.txt
git clone https://github.com/qiuqiao/SOFA.git models/SOFA
git -C models/SOFA checkout 584d6b9
```

从模型作者的发布页下载检查点，放到 `models/sofa-ja/model.ckpt`。权重保存在本地 models/ 目录。检查点加载使用 PyTorch pickle，必须来自可信来源。权重的使用和分发遵循模型作者许可。

已验证的本地组合为 Python 3.12、PyTorch/TorchAudio 2.8.0、CUDA 12.8 wheels。`torchaudio.functional.forced_align` 在 2.8 已弃用，所以这里固定版本；升级时同步适配 CTC 接口并验证。

`song_import.align --device auto` 有 CUDA 时用 CUDA，否则用 CPU。首次运行可能有 JIT 编译耗时。全曲推理的神经网络前向按窗口处理，但完整特征和动态规划仍会占用内存；遇到超长音频应先按实际乐段拆分任务并保留绝对偏移。

## 发音输入

每个显示词必须有 `kana`。`song_import/phonemes.py` 将假名转换为模型音素，处理促音、拨音、拗音和常见长音。遇到未知字符直接报错。

日式英语、特殊唱法和汉字变读需要按录音确认。可为词提供 `phonemes` 数组覆盖默认转换，例如 `{"jp":"...","kana":"...","phonemes":["k","a"]}`。这里的音素必须属于当前检查点词表，按当前检查点词表填写。

## 文本模型

`song_import.assist` 使用兼容 Chat Completions 的 JSON 接口。服务地址、模型和密钥通过环境变量配置。

PowerShell 示例：

```powershell
$env:AI_BASE_URL = 'https://api.deepseek.com'
$env:AI_MODEL = '你的模型名称'
$env:AI_API_KEY = '你的密钥'
python -m song_import.assist lyrics work/source-text.json --output work/text-draft.json
python -m song_import.assist review work/review-input.json --output work/review-notes.json
```

地址应为提供 `/chat/completions` 的 API 根路径。运行前确认服务支持 `response_format: json_object`。Linux/macOS 用 `export` 设置同名环境变量。实际密钥保存在本地环境配置中。

每次调用只发送指定 JSON 的内容和对应提示词。`lyrics` 输入示例见 `examples/text-input.json`；`review` 可以包含来源、草稿和审计中需要检查的部分。输入文件按当前文字任务选取歌词、来源和审计内容。

输出旁边保存 `.usage.json`，记录模型名和服务返回的 token 用量。费用由供应商计价；用量字段缺失时保留空对象。每条命令对应一次请求，响应保存为草稿，核对后写入任务。

提示词是普通文件，可以在调用前审阅和修改：

- `prompts/lyrics.md`：有来源的文字、读音和译文草稿。
- `prompts/review.md`：根据输入证据列出问题及试听窗口。

文本接口处理 JSON 输入；来源收集和实际试听由宿主 Agent 或使用者完成，见 [Agent 导入规范](agent-import.md)。

## 完整导入工作站

`song_import.import_job` 使用 `examples/import-config.json` 组织模型。模型解释器还需要 Demucs：

```sh
python -m pip install demucs==4.0.1
```

FFmpeg 应在 PATH，或在配置中填写绝对路径。设置 vocals 可提供已有分轨，须与原曲长度、起点相同。模型路径相对仓库根目录，解释器建议使用绝对路径。

读音适配器连接本机 [VOICEVOX Engine](https://github.com/VOICEVOX/voicevox_engine)。从官方发行渠道安装并启动引擎，使用 `/speakers` 接口选择声库；声库许可和标注要求需单独遵守。默认端口 50021，speaker 3 只是示例值。

适配器调用 `/audio_query` 和 `/synthesis`，按 speedScale 1、0.75、0.55 分别合成，保持原有句尾语调。时间按引擎音素时长的 24000/256 帧率逐音素舍入，并验证实际 WAV 长度。实现依据见 [引擎时间转换代码](https://github.com/VOICEVOX/voicevox_engine/blob/master/voicevox_engine/tts_pipeline/tts_engine.py)。升级引擎后先验证接口、音素序列和帧率；校验异常时停止，修复适配后继续。

查询先使用歌词文字，以保留词界与重音；音素与指定读音不符时，重试明确的片假名读音。两次查询都会保存，第二次仍不符就停止。语音中的 `えい`、`おう` 可以保留两种元音，也可以读成长音；两者只按相同的音素位置匹配，时间始终来自实际合成查询。朗读与歌声分别使用各自的长音处理规则。

原曲 SOFA 时间和读音时间互相独立。时间结构与音频质量分别检查。

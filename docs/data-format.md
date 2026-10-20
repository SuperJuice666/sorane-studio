# 歌曲格式

每首歌放在 `data/songs/<id>/song.json`，资源路径相对于该文件所在目录。格式版本为 `schemaVersion: 1`，完整小例子见 `examples/song.json`。

| 字段              | 含义                                    |
| ----------------- | --------------------------------------- |
| `id`              | 稳定的小写英文、数字和连字符 ID         |
| `title`、`artist` | 显示名称，也用于识别已上线歌曲          |
| `duration`        | 原曲完整长度，单位秒                    |
| `audio`           | `1`、`0.75`、`0.5` 三种预制音频的 `src` |
| `lines`           | 按原曲时间顺序排列的歌词句              |
| `chunks`          | 可选；以整段音频 `src` 为键的分块索引   |

句子有 `jp`、`section`、`start`、`end`、`tokens`，可加 `translation`。`start/end` 记录实际发声边界。`clipStart/clipEnd` 是可选的练习裁切边界，默认使用句子起止；必须包住实际句子。

每个词有 `jp`、`kana`、`romaji` 和绝对 `start/end`。词和句按时间顺序排列，区间保持互斥。歌唱重叠、和声或回声由导入端确定练习声部，再记录相应边界。

可选的读音字段：

```json
{
  "jp": "歩こう",
  "kana": "あるこう",
  "romaji": "arukō",
  "start": 1.0,
  "end": 2.0,
  "ruby": [{ "text": "歩", "reading": "ある" }, { "text": "こう" }],
  "readingParts": ["a", "ru", "kō"]
}
```

`ruby` 明确对应书写片段；熟字训或无法自然拆开的读音可以整词标注。注音按实际读音对应汉字或词组。未提供 `ruby` 时浏览器按送假名和整词读音显示保守的注音。

`readingParts` 是显示辅助，当前只有至少 8 个罗马字母且 5 个分组的长读音才展开；下一句仍显示原始 `romaji`。对齐使用原词的时间字段。

## 读音录音

`line.narration` 可省略。提供时必须包含 `normal`、`slow`、`verySlow`，每项包含 `src`、`duration`、`tokens`。这些词标注是该读音文件的相对秒数，词数必须与显示词数相同。

```json
{
  "src": "reading/01-slow.mp3",
  "duration": 2.2,
  "tokens": [
    { "start": 0.1, "end": 0.8 },
    { "start": 1.0, "end": 2.0 }
  ]
}
```

三档分别由语音模型合成，每档保存对应的词时间。裁掉静音、拼接片段后也必须重算词时间。

导入草稿还可设置 `line.narrationBreaks`（需要短停顿的词索引，表示在该词之后），以及 `token.narrationKana`（与歌唱读音不同的朗读假名）。这两个字段供导入端制作读音使用。默认连续朗读；有明确语义依据才插入停顿。

## 分块索引

`sampleRate` 固定 44100，`frames` 是这一档音频的总采样帧数。`chunks` 中每项的 `[first,last)` 必须连续覆盖全曲。`decodedFrames` 是文件解码帧数；`trimStart` 是主区间前的保留帧数；`postRoll` 是后面的保留帧数。

单个四声道文件用 `src`，两个立体声文件用 `parts: [伴奏, 人声]`，同时让 `src` 等于第一项。Sorane Studio 的 `song_import.media` 按实际采样数据生成分块索引。

构建校验资源、包内路径、时间顺序、词数和块覆盖；歌词内容与听感在导入复核阶段检查。

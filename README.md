# AstrBot 鉴屎查重插件

`astrbot_plugin_shit_duplication_detector` 使用 AstrBot 已配置的聊天模型，识别群聊中的玩梗、恶搞、荒诞及抽象文本，逐项比较本群历史记录，并对重复搬运进行傲娇吐槽。

## 使用

1. 将插件放在 `data/plugins/astrbot_plugin_shit_duplication_detector/`，通过 AstrBot 插件管理加载。
2. 使用 AstrBot 原生 QQ 官方机器人 WebSocket 适配器 `qq_official`。
3. 在手机 QQ 的群聊机器人设置中，将“机器人可获取的群聊消息范围”设为“获取群内全部消息”。否则插件收不到普通的非 @ 消息。QQ 配置参考 [AstrBot 官方文档](https://docs.astrbot.app/platform/qqofficial/websockets.html)。
4. 在 AstrBot 中为当前会话选择聊天 Provider，鉴屎、查重和吐槽均使用当前会话的模型。

插件没有自定义配置项或配置文件，提示词固定在代码中，直接使用 AstrBot 的模型接口，无需额外 API Key 或 SDK。

## 处理规则

- 监听群消息，无需 @ 机器人。只提取文字，不识别图片消息段；没有文字的消息直接忽略。文字中的文件链接在保存时归档为附件。
- 非屎消息直接忽略，不写入插件数据目录。
- 确认是屎后，才读取本群历史记录，从早到晚逐项调用模型比较。
- 将轻微改字、标点或排版变化后的相同内容视为搬运；同一梗的新创作或新增实质内容不算重复。原作者再次发送也算重复。
- 全部比较均明确不重复，才保存文字和记录；遇到最早的匹配记录就停止比较。
- 确认重复后，回复一条包含 @ 搬运者、动态吐槽、首发者 ID 和北京时间的消息，不重发原文。
- 不设置回复冷却或回复时限，查重完成并确认重复后正常生成和发送吐槽。
- 本插件只在确认重复时发言，不关闭 AstrBot 默认聊天或其他插件；它们仍可能单独响应消息。

## 本地数据

通过 `StarTools.get_data_dir("astrbot_plugin_shit_duplication_detector")` 获取目录，默认位于：

```text
data/plugin_data/astrbot_plugin_shit_duplication_detector/
└── group-<群ID>/
    └── msg-<记录ID>/
        ├── message.json
        ├── record.json
        └── attachments/
            └── <链接中的文件名>
```

`message.json` 保存文字消息段。`record.json` 保存约定的 `group_id`、`sender_id`、`id` 和 `timestamp`。查重按 `timestamp` 从早到晚比较，返回原始记录。

保存时提取文字中的 HTTP(S) 链接、`file://` 链接和 AstrBot `data` 目录内的本地路径。网络文件直接以链接路径中的文件名保存到当前记录的 `attachments/`，本地数据文件创建硬链接；同名附件已存在时直接复用。成功后把文字中的链接替换成 `attachments/...` 相对路径，链接没有文件名、无法下载或无法创建硬链接时保留原链接。

只保存确认的新内容，不创建 `pending` 目录。首发以插件记录的最早原始内容为准，不追溯接入前的群历史。

## 失败行为

异常交给 AstrBot 处理，插件不重试、不恢复。判断失败或查重未完成时不保存为新内容。

## 验证状态

未编写或运行测试，未进行 QQ 联调，待用户自行验证。

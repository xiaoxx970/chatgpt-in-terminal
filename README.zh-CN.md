## 在终端与GPT聊天

[![English badge](https://img.shields.io/badge/%E8%8B%B1%E6%96%87-English-blue)](https://github.com/xiaoxx970/chatgpt-in-terminal/blob/main/README.md)
[![简体中文 badge](https://img.shields.io/badge/%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-Simplified%20Chinese-blue)](https://github.com/xiaoxx970/chatgpt-in-terminal/blob/main/README.zh-CN.md)
[![Platform badge](https://img.shields.io/badge/Platform-MacOS%7CWindows%7CLinux-green)]()
[![standard-readme compliant](https://img.shields.io/badge/readme%20style-standard-brightgreen.svg)](https://github.com/RichardLitt/standard-readme)

本项目实现在终端与 ChatGPT 聊天

回答中的 Markdown 内容渲染为富文本的精美格式

支持上键历史检索、可选的多行提问、tokens 统计

聊天框中支持斜杠(/)命令，可实时切换多行提问模式、撤销上一次提问和回答、修改system prompt等，具体请查看下面的可用命令

支持将聊天消息保存到 JSON 文件中，并能够从文件中加载

> 注意，终端需能正常访问外网（配置代理的环境变量）才能运行代码，如系统已开启代理但没有配置终端代理，API 请求就会从国内 IP 发起，可能导致账号停用 ([#2](https://github.com/xiaoxx970/chatgpt-in-terminal/issues/2))

![example](https://github.com/xiaoxx970/chatgpt-in-terminal/raw/main/README.assets/small.gif)

默认使用 [gpt-3.5-turbo](https://platform.openai.com/docs/guides/chat/chat-completions-beta) 模型，也就是 ChatGPT(免费版) 所使用的模型。

### 相关项目

[C/C++实现的GPTerm](https://github.com/Ace-Radom/cGPTerm) by @Ace-Radom

[可以调用 POE API 的 gpt-term](https://github.com/Lemon-2333/chatgpt-in-terminal-Poe-Api) by @Lemon-2333

## 更新记录

### 2023-05-20

- 新增 host 配置项支持，在使用自建 API 反向代理服务器的时候很有用([#49](https://github.com/xiaoxx970/chatgpt-in-terminal/issues/49))，你现在可以使用 `gpt-term --set-host HOST` 来配置 host，默认为 https://api.openai.com。

### 2023-05-18

- 新增多语言支持：英语、中文、日语、德语，默认跟随系统语言，现在可以使用 `/lang` 来切换语言

<details>
  <summary>更多 Change log</summary>

### 2023-05-11

- 在输入未被识别的命令时查找用户最可能想输入的命令

### 2023-05-05

- 添加`/rand`命令设置temperature参数

- 为 `/stream` 命令添加 overflow 模式切换，现在可以运行命令 `/stream visible` 切换到始终可见模式。在这个模式下，超出屏幕的内容将被向上滚动，新内容会一直输出直到完成

### 2023-04-23

- 发布 `gpt-term` 到 [Pypi](https://pypi.org/project/gpt-term/)，开始版本管理，现在不需要克隆项目到本地，直接使用 `pip` 命令就可以安装 `gpt-term`

### 2023-04-15

- 新增在单行模式下换行功能，现在可以使用 `Esc` + `Enter` 在单行模式下换行

### 2023-04-13

- 增加后台生成并设置终端标题功能，现在客户端会将第一个提问内容的摘要作为终端标题

### 2023-04-09

- 增加文件名生成功能，客户端在执行保存命令时会将第一个提问内容的摘要作为文件名的建议

### 2023-04-05

- 添加`/delete`命令删除本次对话中的第一个问题和答案以减少 token

### 2023-04-01

- 增加 `/copy` 命令，用于复制回复内容
- 增加流式输出模式，默认开启，使用 `/stream` 切换

### 2023-03-28

- 增加 `--model` 运行参数和 `/model` 命令，用于选择 / 更改使用的模型

### 2023-03-27

- 增加 `--key` 运行参数，用于选择使用哪一个储存在 `.env` 文件中的API key

### 2023-03-23

- 增加了斜杠(/)命令功能
- 增加了 `--load` 运行参数，加载已经保存的聊天记录
- 修改了程序结构和交互方式，将原来的 `input()` 函数改为了 `prompt_toolkit` 库提供的输入界面，支持多行输入和命令行补全等功能。
- 改进了错误处理机制，增加了聊天记录备份、日志记录等功能，提高了程序的可靠性和容错能力。
- 重构了代码逻辑和函数结构，增加了模块化和可读性。

</details>

## 准备工作

1. 一个 OpenAI API 密钥。你需要注册一个 OpenAI 帐户并获取 API 密钥。

   OpenAI 的 API 密钥可在主页右上角点击 "View API keys" 打开的页面中生成，直达链接：https://platform.openai.com/account/api-keys

   ![image-20230303233352970](https://github.com/xiaoxx970/chatgpt-in-terminal/raw/main/README.assets/image-20230303233352970.png)

2. [Python](https://www.python.org/downloads/) 3.7 或更高版本

   **注意：尽量不要使用系统自带的 Python（包括Windows11 的应用商店版 Python 和 MacOS 的预装 Python），否则会出现安装好后gpt-term 命令找不到的情况 ([#38](https://github.com/xiaoxx970/chatgpt-in-terminal/issues/38))**

## 安装

1. 使用 `pip` 安装 `GPT-Term`

   ```shell
   pip3 install gpt-term
   ```
   
2. 配置 API Key

   ```shell
   gpt-term --set-apikey 你的API_KEY
   ```

   > 如果现在不配置  API Key，也可在运行时根据提示输入 API Key


## 更新

如果要把 `GPT-Term` 更新为最新版本，在命令行中运行：

```sh
pip3 install --upgrade gpt-term
```

> 如果有新版本，`GPT-Term` 会在退出时提示用户更新

## 如何使用

使用以下命令运行：

```shell
gpt-term
```

或者：

```shell
python3 -m gpt_term
```

在默认的单行模式下输入提问时，使用 `Esc` + `Enter` 换行，`Enter` 提交

以下是一些常见的快捷键（同时也是shell的快捷键）：

- `Ctrl+_`: 撤消
- `Ctrl+L`: 清屏，相当于shell中的`clear`命令
- `Ctrl+C`: 停止当前回答或取消当前输入
- `Tab`：自动补全命令或参数
- `Ctrl+U`：删除光标左侧的所有字符
- `Ctrl+K`：删除光标右侧的所有字符
- `Ctrl+W`：删除光标左侧的单词

>  原始格式的对话记录会存至 `~/.gpt-term/chat.log`

### 可用参数

| 选项          | 功能                              | 示例                                          |
| ------------- | --------------------------------- | --------------------------------------------- |
| -h, --help    | 显示此帮助信息并退出              | `gpt-term --help`                             |
| --load FILE   | 从文件中加载聊天记录              | `gpt-term --load chat_history_code_check.json` |
| --key API_KEY | 选择 config.ini 文件中要使用的 API 密钥 | `gpt-term --key OPENAI_API_KEY1`              |
| --model MODEL | 选择要使用的 AI 模型              | `gpt-term --model gpt-3.5-turbo`              |
| --host HOST | 设置在本次运行中使用的 API Host 地址（这通常被用来配置代理） | `gpt-term --host https://closeai.deno.dev`              |
| -m, --multi   | 启用多行模式                      | `gpt-term --multi`                            |
| -r, --raw     | 启用原始模式                      | `gpt-term --raw`                              |
| -l, --lang LANG | 设置本次运行语言：en, zh_CN, jp, de | `gpt-term --lang en` |
| --set-host HOST        | 设置API Host地址（这通常被用来配置代理）              | `gpt-term --set-host https://closeai.deno.dev` |
| --set-apikey KEY        | 设置 OpenAI 的 API 密钥                          | `gpt-term --set-apikey sk-xxx` |
| --set-timeout SEC       | 设置 API 请求的最大等待时间                        | `gpt-term --set-timeout 10` |
| --set-gentitle BOOL     | 设置是否为聊天自动生成标题                          | `gpt-term --set-gentitle True` |
| --set-saveperfix PERFIX | 设置聊天历史文件的保存前缀                          | `gpt-term --set-saveperfix chat_history_` |
| --set-loglevel LEVEL    | 设置日志级别：DEBUG, INFO, WARNING, ERROR, CRITICAL | `gpt-term --set-loglevel DEBUG` |
| --set-lang LANG    | 设置语言：en, zh_CN, jp, de | `gpt-term --set-lang en` |

> 多行模式与 raw 模式可以同时使用

### 配置文件

配置文件位于 `~/.gpt-term/config.ini`，由程序自动生成，可以通过程序 `--set` 参数修改，也可手动修改

默认配置如下

```ini config.ini
[DEFAULT]
# OpenAI 的 API 密钥
OPENAI_API_KEY=

# 向 API 请求的最大等待时间，默认30s
OPENAI_API_TIMEOUT=30

# 是否为对话自动生成标题，默认开启（生成标题将额外消耗少量 token）
AUTO_GENERATE_TITLE=True

# 定义 /save 命令保存聊天历史时的默认文件前缀，默认值为"./chat_history_"，表示将聊天历史存到当前目录的以"chat_history_"开头的文件中
# 同时该前缀还可以指定为目录+/的形式来让程序保存聊天历史到一个文件夹中(注意需要提前创建好对应文件夹)，比如：CHAT_SAVE_PERFIX=chat_history/
CHAT_SAVE_PERFIX=./chat_history_

# 日志级别，默认为INFO，可选值：DEBUG、INFO、WARNING、ERROR、CRITICAL
LOG_LEVEL=INFO

# 设置程序的语言，默认为空，将跟随系统语言
LANGUAGE=
```

### 可用命令

- `/raw`：在回复中显示原始文本，而不是渲染后的 Markdown 格式

  > 切换后可使用 `/last` 命令重新打印当前回复

- `/multi`：启用或禁用多行模式，允许用户输入多行文本

  > 多行模式下使用 `Esc` + `Enter` 提交问题
  >
  > 如果是粘贴多行文本，则单行模式也可以正常粘贴

- `/stream`：禁用或启用流式传输

  > 在流式传输模式下，回复将在客户端收到第一部分回应后开始逐字输出，减少等待时间。流式传输默认为开启。

  - `/stream ellipsis` （默认）

    > 切换流式输出的模式为自动省略，当输出内容超过屏幕时，将在屏幕下方显示三个小点并等待直到输出完成

  - `/stream visible`

    > 切换流式输出的模式为始终可见，在这个模式下，超出屏幕的内容将被向上滚动，新内容会一直输出直到完成。注意在这个模式下终端将无法正确清理超出屏幕的内容。

- `/tokens`：显示已花费的 API token 数统计和本次对话的 token 长度

  > GPT-3.5的对话token限制为4096，可通过此命令实时查看是否接近限制

- `/usage`：显示已用的 API 的账号余额

  > 这个功能也许会不稳定。如果使用这个命令时频繁报错或无法正常输出，你可以访问 [usage 页面](https://platform.openai.com/account/usage) 查看更多信息。

- `/model`：显示或选择使用的模型

  > 默认支持 `gpt-4`，`gpt-4-32k`，`gpt-3.5-turbo`，其余的模型需要在代码内更改 API endpoint

- `/last`：显示最后一条回复

- `/copy` 或 `/copy all`：将最后一条回复内容复制至剪切板

  - `/copy code [index]`：将最后一条回复内容中的第 `index` 块代码复制至剪切板

    > 如果不指定 `index`，则终端会打印所有代码块并询问要复制的序号

- `/delete` 或 `/delete first`：将当前会话第一条提问和回答内容删除

    > 在会话 token 将要达到上限时会提示用户，已经超出上限时会询问是否删除第一条信息

  - `/delete all`：将所有会话删除

- `/save [filename_or_path]`：将聊天记录保存到指定的 JSON 文件中

  > 如果未提供文件名或路径，客户端将生成一个，如果生成失败，则在输入时建议使用文件名 `chat_history_年-月-日_时,分,秒.json`

- `/system [new_prompt]`：修改系统提示语

- `/rand [randomness]`: 设置对话随机程度（0~2），较高的值如 0.8 将使输出更随机，而较低的值如 0.2 将使回答更集中和确定

- `/title [new_title]`: 为这个聊天终端设置标题

   > 如果没有提供 new_title，将根据第一个提问生成新标题

- `/timeout [new_timeout]`：修改 API 超时时间

  > 超时默认30s，也可通过 `~/.gpt-term/config.ini` 文件中的 `OPENAI_API_TIMEOUT=` 配置默认超时

- `/undo`：删除上一个问题和回答

- `/version`：显示 `GPT-Term` 的本地版本和远程版本

- `/help`：显示可用命令

- `/exit`：退出应用

### 退出词

在聊天中，使用退出词可以结束本次会话，退出词有：

```py
['再见', 'bye', 'goodbye', '结束', 'end', '退出', 'exit', 'quit']
```

退出词将作为一个问题发送给 ChatGPT，在 GPT 回答后退出。

也可使用 `Ctrl-D` 或 `/exit` 立即退出

退出后将显示本次聊天所使用的 tokens 统计

> 目前价格为: $0.002 / 1K tokens，免费版速率限制为: 20次 / min (`gpt-3.5-turbo`)

## 依赖

感谢以下项目为本脚本提供强大的支持：

- [requests](https://github.com/psf/requests)：用于处理 HTTP 请求
- [pyperclip](https://github.com/asweigart/pyperclip)：跨平台剪贴板操作库
- [rich](https://github.com/willmcgugan/rich)：用于在终端中输出富文本
- [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit)：命令行输入处理库
- [sseclient-py](https://github.com/mpetazzoni/sseclient)：用于实现回答的流式输出
- [tiktoken](https://github.com/OpenAI/tiktoken)：用于计算和处理 OpenAI API token 的库

## 如何贡献

非常欢迎你的加入！[提一个 Issue](https://github.com/xiaoxx970/chatgpt-in-terminal/issues/new) 或者提交一个 Pull Request。

### 贡献者

感谢以下参与项目的人：
<a href="https://github.com/xiaoxx970/chatgpt-in-terminal/graphs/contributors"><img src="https://opencollective.com/chatgpt-in-terminal/contributors.svg?width=890&button=false" /></a>

## 项目结构

```sh
.
├── LICENSE						# 许可证
├── README.md					# 说明文档
├── chat.py						# 脚本入口
├── gpt_term					# 项目包文件夹
│   ├── __init__.py
│   ├── config.ini	  # 密钥存储以及其他设置
│   └── main.py				# 主程序
├── requirements.txt	# 依赖包列表
└── setup.py
```

## 许可证

该项目遵守[MIT许可证](LICENSE)。
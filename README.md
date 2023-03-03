## 关于这个项目

在终端与 ChatGPT 聊天，回答中的 Markdown 内容渲染为富文本的精美格式，支持可选的多行提问、上键历史检索、tokens 统计功能。

![example](README.assets/small.gif)

使用最新的 [gpt-3.5-turbo](https://platform.openai.com/docs/guides/chat/chat-completions-beta) 模型，也就是 ChatGPT 所使用的模型（并非前一代的 `text-davinci-003` 模型）。

## 安装

1. 克隆 Repo 并进入目录

   ```shell
   git clone https://github.com/xiaoxx970/chatgpt-in-terminal.git
   cd ./chatgpt-in-terminal
   ```

2. 在项目根目录下的 `.env` 文件中写入 OPENAI_API_KEY 变量，内容如下

   ```
   OPENAI_API_KEY=你的API_KEY
   ```

   OpenAI 的密钥可在主页右上角点击 `View API keys` 打开的页面中生成

   ![image-20230303233352970](README.assets/image-20230303233352970.png)

3. 通过 requirements.txt 安装依赖

   ```shell
   pip3 install -r requirements.txt
   ```

## 如何使用

使用以下命令进行运行：

```shell
python3 chat.py
```

> 如果问题需要多行输入，以 `-m` 参数运行：
>
> ```shell
> python3 chat.py -m
> ```
>
> 多行模式下按回车切换下一行，如果在空行回车则提交问题
>

在聊天中，使用退出词可以结束本次会话，退出词有：

```py
['再见', 'bye', '结束', 'end', '退出', 'exit']
```

退出词将作为一个问题发送给 ChatGPT，在 GPT 回答后退出。

也可使用 `Ctrl-C` 或者 `Ctrl-D` 立即退出

退出后将显示本次聊天所使用的 tokens 统计，目前价格为: $0.002 / 1K tokens，免费版速率限制为: 20次 / min

## 项目结构

```
├── README.md           # 项目说明文档
├── chat.py             # 项目主要代码
├── requirements.txt    # 依赖包列表
├── chat.log						# 聊天后生成的对话日志
└── .env								# 密钥存储文件
```

## 许可证

该项目遵守[MIT许可证](LICENSE)。
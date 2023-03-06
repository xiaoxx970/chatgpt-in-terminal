#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import openai
import logging
import platform
if platform.system() in {"Linux", "Darwin"}:
    # 用于支持Linux/MacOS终端下input()函数的历史回朔和修改操作
    import readline
from rich.console import Console
from rich.markdown import Markdown
from dotenv import load_dotenv

# 从 .env 文件中读取 OPENAI_API_KEY
load_dotenv()
api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    api_key = input("OpenAI API Key: ")

# 日志记录到 chat.log，注释下面这行可不记录日志
logging.basicConfig(filename='chat.log', format='%(asctime)s %(name)s: %(levelname)-6s %(message)s',
                    datefmt='[%Y-%m-%d %H:%M:%S]', level=logging.INFO, encoding="UTF-8")
log = logging.getLogger("chat")


class CHATGPT:
    def __init__(self, api_key: str):
        openai.api_key = api_key
        self.messages = [
            {"role": "system", "content": "You are a helpful assistant."}]
        self.total_tokens = 0

    def send(self, message: str):
        self.messages.append({"role": "user", "content": message})
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=self.messages
        )
        log.debug(f"Response: {response}")
        self.total_tokens += response["usage"]["total_tokens"]
        reply = response["choices"][0]["message"]
        self.messages.append(reply)
        return reply

    def get_total_tokens(self):
        return self.total_tokens


def multi_input(prompt: str):
    lines = []
    while True:
        line = input(prompt)
        if not line:
            break
        lines.append(line)
    return '\n'.join(lines)


chatGPT = CHATGPT(api_key)
console = Console()
try:
    console.print("Hi, welecome to chat with gpt.", style="dim")
    while True:
        # 运行参数中带有“-m”，则使用多行输入函数
        message = "-m" in sys.argv and multi_input("> ") or input("> ")

        # 如果没有发送任何消息，就继续显示“> ”
        if not message:
            continue

        log.info(f"> {message}")
        # 发送消息后显示动画等待
        with console.status("[bold cyan]ChatGPT is thinking...") as status:
            reply = chatGPT.send(message)

        log.info(f"ChatGPT: {reply['content']}")
        # 输出回复
        console.print("ChatGPT: ", end='', style="bold cyan")
        if "-raw" in sys.argv:
            print(reply["content"])
        else:
            console.print(Markdown(reply["content"]), new_line_start=True)

        # 退出词判断
        if message.lower() in ['再见', 'bye', 'goodbye', '结束', 'end', '退出', 'exit']:
            break

except (EOFError, KeyboardInterrupt):
    print("\nExiting...")
finally:
    console.print(
        f"[bright_magenta]Total tokens used: [bold]{chatGPT.get_total_tokens()}")

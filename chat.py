#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import openai
import logging
import readline
from rich.console import Console
from rich.markdown import Markdown
from dotenv import load_dotenv
load_dotenv()

api_key = os.environ.get("OPENAI_API_KEY")
console = Console()
logging.basicConfig(filename='chat.log', level=logging.INFO, encoding="UTF-8")


class CHATGPT:
    def __init__(self, api_key):
        openai.api_key = api_key
        self.messages = [
            {"role": "system", "content": "You are a helpful assistant."}]
        self.total_tokens = 0

    def send(self, message):
        self.messages.append({"role": "user", "content": message})
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=self.messages
        )
        logging.info(f"Send: {self.messages}")
        logging.info(f"Get: {response}")
        self.total_tokens += response["usage"]["total_tokens"]
        reply = response["choices"][0]["message"]
        self.messages.append(reply)
        return reply

    def get_total_tokens(self):
        return self.total_tokens


def multi_input(prompt):
    lines = []
    while True:
        line = input(prompt)
        if not line:
            break
        lines.append(line)
    return '\n'.join(lines)


chatGPT = CHATGPT(api_key)
try:
    console.print("Hi, welecome to chat with gpt.", style="dim")
    while True:
        message = "-m" in sys.argv and multi_input("> ") or input("> ")
        if not message:
            continue
        with console.status("[bold cyan]ChatGPT is thinking...") as status:
            reply = chatGPT.send(message)
        console.print("ChatGPT: ", end='', style="bold cyan")
        console.print(Markdown(reply["content"]), new_line_start=True)
        if message.lower() in ['再见', 'bye', '结束', 'end', '退出', 'exit']:
            break
except (EOFError, KeyboardInterrupt):
    print("\nExiting...")
finally:
    console.print(
        f"[bright_magenta]Total tokens used: [bold]{chatGPT.get_total_tokens()}")

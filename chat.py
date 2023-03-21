#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import openai
import logging
import json
from prompt_toolkit import prompt, PromptSession, print_formatted_text
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import confirm
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from dotenv import load_dotenv

# 从 .env 文件中读取 OPENAI_API_KEY
load_dotenv()
api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    api_key = prompt("OpenAI API Key: ")

# 日志记录到 chat.log，注释下面这行可不记录日志
logging.basicConfig(filename=f'{sys.path[0]}/chat.log', format='%(asctime)s %(name)s: %(levelname)-6s %(message)s',
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
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=self.messages
            )
        except KeyboardInterrupt:
            self.messages.pop()
            raise
        log.debug(f"Response: {response}")
        self.total_tokens += response["usage"]["total_tokens"]
        reply = response["choices"][0]["message"]
        self.messages.append(reply)
        return reply

    def get_total_tokens(self):
        return self.total_tokens


def multi_input(prompt: str, session):
    lines = []
    while True:
        line = session.prompt(prompt)
        if not line:
            break
        lines.append(line)
    return '\n'.join(lines)


def save_chat_history(chatGPT, filename):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(chatGPT.messages, f, ensure_ascii=False, indent=4)
    print_formatted_text(FormattedText(
        [("class:info", f"Chat history saved to {filename}")]))


chatGPT = CHATGPT(api_key)
console = Console()
try:
    print_formatted_text(FormattedText(
        [("class:info", "Hi, welcome to chat with GPT.")]))

    style = Style.from_dict({
        'info': 'fg:#808080',
        'exiting': 'bold fg:#ff0000',
        'prompt': 'bold',
    })

    session = PromptSession()

    raw_mode = False
    multi_line_mode = False

    commands = WordCompleter([
        '/raw', '/multi', '/tokens', '/resend', '/save', '/undo'
    ])

    while True:
        try:
            message = session.prompt(FormattedText(
                [('class:prompt', '> ')]), completer=commands, complete_while_typing=True)

            if message.startswith('/'):
                command = message.strip().lower()

                if command == '/raw':
                    raw_mode = not raw_mode
                    print_formatted_text(FormattedText(
                        [("class:info", "Raw mode toggled.")]))

                elif command == '/multi':
                    multi_line_mode = not multi_line_mode
                    print_formatted_text(FormattedText(
                        [("class:info", "Multi-line mode toggled.")]))

                elif command == '/tokens':
                    print_formatted_text(FormattedText(
                        [("class:info", f"Total tokens used: {chatGPT.get_total_tokens()}")]))

                elif command == '/resend':
                    reply = chatGPT.messages[-1]
                    log.info(f"ChatGPT: {reply['content']}")
                    console.print("ChatGPT: ", end='', style="bold cyan")
                    if raw_mode:
                        print(reply["content"])
                    else:
                        console.print(
                            Markdown(reply["content"]), new_line_start=True)

                elif command == '/save':
                    save_chat_history(chatGPT, 'chat_history.json')

                elif command == '/undo':
                    if len(chatGPT.messages) > 2:
                        chatGPT.messages.pop()
                        chatGPT.messages.pop()
                        print_formatted_text(FormattedText(
                            [("class:info", "Last question and answer removed.")]))
                    else:
                        print_formatted_text(FormattedText(
                            [("class:info", "Nothing to undo.")]))

            else:
                if not message:
                    continue

                log.info(f"> {message}")

                if multi_line_mode:
                    message = multi_input("> ", session)

                with console.status("[bold cyan]ChatGPT is thinking...") as status:
                    reply = chatGPT.send(message)

                log.info(f"ChatGPT: {reply['content']}")
                console.print("ChatGPT: ", end='', style="bold cyan")
                if raw_mode:
                    print(reply["content"])
                else:
                    console.print(
                        Markdown(reply["content"]), new_line_start=True)

                if message.lower() in ['再见', 'bye', 'goodbye', '结束', 'end', '退出', 'exit']:
                    break

        except KeyboardInterrupt:
            continue
        except EOFError:
            print_formatted_text(FormattedText(
                [("class:exiting", "\nExiting...")]))
            break

finally:
    log.info(f"Total tokens used: {chatGPT.get_total_tokens()}")
print_formatted_text(FormattedText(
    [("class:info", f"Total tokens used: {chatGPT.get_total_tokens()}")]))

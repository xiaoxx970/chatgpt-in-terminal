#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import openai
import logging
import json
import argparse
from datetime import datetime
from prompt_toolkit import prompt, PromptSession
from prompt_toolkit.keys import Keys
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.completion import Completer, Completion
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
        self.current_tokens = 0

    def send(self, message: str):
        self.messages.append({"role": "user", "content": message})
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=self.messages
            )
        except KeyboardInterrupt:
            self.messages.pop()
            console.print("[bold cyan]Aborted.")
            raise
        log.debug(f"Response: {response}")
        self.current_tokens = response["usage"]["total_tokens"]
        self.total_tokens += self.current_tokens
        reply = response["choices"][0]["message"]
        self.messages.append(reply)
        return reply

    def save_chat_history(self, filename):
        with open(f"{filename}", 'w', encoding='utf-8') as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=4)
        console.print(
            f"[dim]Chat history saved to: [bright_magenta]{filename}", highlight=False)

    def modify_system_prompt(self, new_content):
        if self.messages[0]['role'] == 'system':
            old_content = self.messages[0]['content']
            self.messages[0]['content'] = new_content
            console.print(
                f"[dim]System prompt has been modified from '{old_content}' to '{new_content}'.")
            if len(self.messages) > 1:
                console.print(
                    "[dim]Note this is not a new chat, modifications to the system prompt have limited impact on answers.")
        else:
            console.print(
                f"[dim]No system prompt found in messages.")


class CustomCompleter(Completer):
    commands = [
        '/raw', '/multi', '/tokens', '/last', '/save', '/system', '/undo', '/help', '/exit'
    ]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith('/'):
            for command in self.commands:
                if command.startswith(text):
                    yield Completion(command, start_position=-len(text))


key_bindings = KeyBindings()


@key_bindings.add(Keys.Enter, eager=True)
def _(event):
    buffer = event.current_buffer
    text = buffer.text.strip()
    if text.startswith('/') or not multi_line_mode:
        buffer.validate_and_handle()
    else:
        buffer.insert_text('\n')


def print_message(message):
    role = message["role"]
    content = message["content"]
    if role == "user":
        print(f"> {content}")
    else:
        console.print("ChatGPT: ", end='', style="bold cyan")
        if raw_mode:
            print(content)
        else:
            console.print(Markdown(content), new_line_start=True)


chatGPT = CHATGPT(api_key)
console = Console()

parser = argparse.ArgumentParser(description='Chat with GPT-3.5')
parser.add_argument('--load', type=str, help='Load chat history from file')

args = parser.parse_args()

raw_mode = False
multi_line_mode = False

try:
    console.print(
        "[dim]Hi, welcome to chat with GPT. Type `[bright_magenta]\help[/]` to display available commands.")

    if args.load:
        with open(args.load, 'r', encoding='utf-8') as f:
            chat_history = json.load(f)
        chatGPT.messages = chat_history
        for message in chatGPT.messages[1:]:
            print_message(message)
        console.print(
            f"[dim]Chat history successfully loaded from: [bright_magenta]{args.load}", highlight=False)

    session = PromptSession()
    commands = CustomCompleter()

    while True:
        try:
            message = session.prompt(
                '> ', completer=commands, complete_while_typing=True, key_bindings=key_bindings)

            if message.startswith('/'):
                command = message.strip().lower()

                if command == '/raw':
                    raw_mode = not raw_mode
                    console.print(
                        f"[dim]Raw mode {'enabled' if raw_mode else 'disabled'}, use `/last` to display the last answer.")

                elif command == '/multi':
                    multi_line_mode = not multi_line_mode
                    if multi_line_mode:
                        console.print(
                            f"[dim]Multi-line mode enabled, press [[bright_magenta]Esc[/]] + [[bright_magenta]ENTER[/]] to submit.")
                    else:
                        console.print(f"[dim]Multi-line mode disabled.")

                elif command == '/tokens':
                    console.print(
                        f"[dim]Total tokens: {chatGPT.total_tokens}")
                    console.print(
                        f"[dim]Current tokens: {chatGPT.current_tokens}[/]/[black]4097")

                elif command == '/last':
                    reply = chatGPT.messages[-1]
                    log.info(f"ChatGPT: {reply['content']}")
                    print_message(reply)

                elif command == '/save':
                    args = command.split()
                    if len(args) > 1:
                        filename = args[1]
                    else:
                        now = datetime.now()
                        filename = f'{sys.path[0]}/chat_history_{now.strftime("%Y-%m-%d_%H:%M:%S")}.json'
                    chatGPT.save_chat_history(filename)

                elif command.startswith('/system'):
                    args = command.split()
                    if len(args) > 1:
                        new_content = ' '.join(args[1:])
                    else:
                        console.print(
                            f"[dim]Current system prompt: '{chatGPT.messages[0]['content']}'", )
                        new_content = prompt("New system prompt: ")
                    chatGPT.modify_system_prompt(new_content)

                elif command == '/undo':
                    if len(chatGPT.messages) > 2:
                        answer = chatGPT.messages.pop()
                        question = chatGPT.messages.pop()
                        truncated_question = question['content'].split('\n')[0]
                        if len(question['content']) > len(truncated_question):
                            truncated_question += "..."
                        console.print(
                            f"[dim]Last question: '{truncated_question}' and it's answer has been removed.")
                    else:
                        console.print("[dim]Nothing to undo.")

                elif command == '/exit':
                    console.print("Exiting...")
                    break

                else:
                    console.print('''[bold]Available commands:[/]
    /raw                     - Toggle raw mode (showing raw text of ChatGPT's reply)
    /multi                   - Toggle multi-line mode (allow multi-line input)
    /tokens                  - Show total tokens and current tokens used
    /last                    - Display last ChatGPT's reply
    /save \[filename_or_path] - Save the chat history to a file
    /system \[new_prompt]     - Modify the system prompt
    /undo                    - Undo the last question and remove its answer
    /help                    - Show this help message
    /exit                    - Exit the application''')

            else:
                if not message:
                    continue

                log.info(f"> {message}")

                with console.status("[bold cyan]ChatGPT is thinking...") as status:
                    reply = chatGPT.send(message)

                log.info(f"ChatGPT: {reply['content']}")
                print_message(reply)

                if message.lower() in ['再见', 'bye', 'goodbye', '结束', 'end', '退出', 'exit', 'quit']:
                    break

        except KeyboardInterrupt:
            continue
        except EOFError:
            console.print("Exiting...")
            break

finally:
    log.info(f"Total tokens used: {chatGPT.total_tokens}")
console.print(
    f"[bright_magenta]Total tokens used: [bold]{chatGPT.total_tokens}")

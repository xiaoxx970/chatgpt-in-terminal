#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime

import pyperclip
import requests
import sseclient
import tiktoken
from dotenv import load_dotenv
from prompt_toolkit import PromptSession, prompt
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.shortcuts import confirm
from prompt_toolkit.styles import Style
from prompt_toolkit.validation import ValidationError, Validator
from rich import print as rprint
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

# 日志记录到 chat.log，注释下面这行可不记录日志
logging.basicConfig(filename=f'{sys.path[0]}/chat.log', format='%(asctime)s %(name)s: %(levelname)-6s %(message)s',
                    datefmt='[%Y-%m-%d %H:%M:%S]', level=logging.INFO, encoding="UTF-8")
log = logging.getLogger("chat")

console = Console()

style = Style.from_dict({
    "prompt": "ansigreen",  # 将提示符设置为绿色
})


class ChatMode:
    raw_mode = False
    multi_line_mode = False
    stream_mode = True

    @classmethod
    def toggle_raw_mode(cls):
        cls.raw_mode = not cls.raw_mode
        console.print(
            f"[dim]Raw mode {'enabled' if cls.raw_mode else 'disabled'}, use `/last` to display the last answer.")

    @classmethod
    def toggle_stream_mode(cls):
        cls.stream_mode = not cls.stream_mode
        if cls.stream_mode:
            console.print(
                f"[dim]Stream mode enabled, the answer will start outputting as soon as the first response arrives.")
        else:
            console.print(
                f"[dim]Stream mode disabled, the answer is being displayed after the server finishes responding.")

    @classmethod
    def toggle_multi_line_mode(cls):
        cls.multi_line_mode = not cls.multi_line_mode
        if cls.multi_line_mode:
            console.print(
                f"[dim]Multi-line mode enabled, press [[bright_magenta]Esc[/]] + [[bright_magenta]ENTER[/]] to submit.")
        else:
            console.print(f"[dim]Multi-line mode disabled.")


class ChatGPT:
    def __init__(self, api_key: str, timeout: int):
        self.api_key = api_key
        self.endpoint = "https://api.openai.com/v1/chat/completions"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        self.messages = [
            {"role": "system", "content": "You are a helpful assistant."}]
        self.model = 'gpt-3.5-turbo'
        self.tokens_limit = 4096
        # as default: gpt-3.5-turbo has a tokens limit as 4096
        # when model changes, tokens will also be changed
        self.total_tokens_spent = 0
        self.current_tokens = count_token(self.messages)
        self.timeout = timeout
        self.title = None

    def send_request(self, data, tips = "ChatGPT is thinking...", stream = ChatMode.stream_mode):
        try:
            with console.status(f"[bold cyan]{tips}"):
                response = requests.post(
                    self.endpoint, headers=self.headers, data=json.dumps(data), timeout=self.timeout, stream=stream)
            # 匹配4xx错误，显示服务器返回的具体原因
            if response.status_code // 100 == 4:
                error_msg = response.json()['error']['message']
                console.print(f"[red]Error: {error_msg}")
                log.error(error_msg)
                return None

            response.raise_for_status()
            return response
        except KeyboardInterrupt:
            console.print("[bold cyan]Aborted.")
            raise
        except requests.exceptions.ReadTimeout as e:
            console.print(
                f"[red]Error: API read timed out ({self.timeout}s). You can retry or increase the timeout.", highlight=False)
            return None
        except requests.exceptions.RequestException as e:
            console.print(f"[red]Error: {str(e)}")
            log.exception(e)
            return None

    def process_stream_response(self, response):
        reply = ""
        client = sseclient.SSEClient(response)
        with Live(console=console, auto_refresh=False) as live:
            try:
                rprint("[bold cyan]ChatGPT: ")
                for event in client.events():
                    if event.data == '[DONE]':
                        break
                    part = json.loads(event.data)
                    if "content" in part["choices"][0]["delta"]:
                        content = part["choices"][0]["delta"]["content"]
                        reply += content
                        if ChatMode.raw_mode:
                            rprint(content, end="", flush=True),
                        else:
                            live.update(Markdown(reply), refresh=True)
            except KeyboardInterrupt:
                live.stop()
                console.print("Aborted.", style="bold cyan")
            finally:
                return {'role': 'assistant', 'content': reply}

    def process_response(self, response) -> dict[str, any]:
        if ChatMode.stream_mode:
            return self.process_stream_response(response)
        else:
            response_json = response.json()
            log.debug(f"Response: {response_json}")
            reply_message = response_json["choices"][0]["message"]
            print_message(reply_message)
            return reply_message

    def delete_first_conversation(self):
        if len(self.messages) >= 3:
            truncated_question = self.messages[1]['content'].split('\n')[0]
            if len(self.messages[1]['content']) > len(truncated_question):
                truncated_question += "..."

            # delete the first request and response (never delete system prompt, which means messages[0])
            del self.messages[1:3]
            self.title = None

            # recount current tokens
            new_tokens = count_token(self.messages)
            tokens_saved = self.current_tokens - new_tokens
            self.current_tokens = new_tokens

            console.print(
                f"[dim]First question: '{truncated_question}' and it's answer has been deleted, saved tokens: {tokens_saved}")
        else:
            console.print("[red]No conversations yet.")

    def handle(self, message: str):
        try:
            self.messages.append({"role": "user", "content": message})
            data = {
                "model": self.model,
                "messages": self.messages,
                "stream": ChatMode.stream_mode
            }
            response = self.send_request(data)
            if response is None:
                self.messages.pop()
                if self.current_tokens >= self.tokens_limit:
                    if confirm("Reached tokens limit, do you want me to forget the earliest message of current chat?"):
                        self.delete_first_conversation()
                return

            reply_message = self.process_response(response)
            if reply_message is not None:
                log.info(f"ChatGPT: {reply_message['content']}")
                self.messages.append(reply_message)
                self.current_tokens = count_token(self.messages)
                self.total_tokens_spent += self.current_tokens

                if self.tokens_limit - self.current_tokens in range(1, 500):
                    console.print(
                        f"[dim]Approaching the tokens limit: {self.tokens_limit - self.current_tokens} tokens left", new_line_start=True)
                # approaching tokens limit (less than 500 left), show info

        except Exception as e:
            console.print(
                f"[red]Error: {str(e)}. Check log for more information")
            log.exception(e)
            self.save_chat_history(
                f'{sys.path[0]}/chat_history_backup_{datetime.now().strftime("%Y-%m-%d_%H,%M,%S")}.json')
            raise EOFError

        return reply_message

    def gen_title(self) -> str | None:
        if len(self.messages) < 2:
            self.title = None
            return
        if self.title:
            return self.title
        prompt = 'Generate a filename for the following content, no more than 10 words, only use filenames that work on multiple platforms, no suffix. \n\nContent: '
        try:
            messages = [{"role": "user", "content": prompt +
                         self.messages[1]['content']}]
            data = {
                "model": "gpt-3.5-turbo",
                "messages": messages,
                "temperature": 0.5
            }
            response = self.send_request(data, tips="Generating title... [/](Ctrl-C to skip)", stream=False)
            if response is None:
                return
            self.title = response.json()["choices"][0]["message"]['content']
            log.info(f"Title generated: {self.title}")

        except KeyboardInterrupt:
            return

        except Exception as e:
            console.print(
                f"[red]Error: {str(e)}. Check log for more information")
            log.exception(e)
            self.save_chat_history(
                f'{sys.path[0]}/chat_history_backup_{datetime.now().strftime("%Y-%m-%d_%H,%M,%S")}.json')
            raise EOFError

        return self.title

    def save_chat_history(self, filename):
        with open(f"{filename}", 'w', encoding='utf-8') as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=4)
        console.print(
            f"[dim]Chat history saved to: [bright_magenta]{filename}", highlight=False)

    def get_credit_usage(self):
        url = 'https://api.openai.com/dashboard/billing/credit_grants'
        try:
            response = requests.get(url, headers=self.headers)
        except requests.exceptions.RequestException as e:
            console.print(f"[red]Error: {str(e)}")
            log.exception(e)
            return None
        except Exception as e:
            console.print(
                f"[red]Error: {str(e)}. Check log for more information")
            log.exception(e)
            self.save_chat_history(
                f'{sys.path[0]}/chat_history_backup_{datetime.now().strftime("%Y-%m-%d_%H,%M,%S")}.json')
            raise EOFError
        return response.json()

    def modify_system_prompt(self, new_content):
        if self.messages[0]['role'] == 'system':
            old_content = self.messages[0]['content']
            self.messages[0]['content'] = new_content
            console.print(
                f"[dim]System prompt has been modified from '{old_content}' to '{new_content}'.")
            self.current_tokens = count_token(self.messages)
            # recount current tokens
            if len(self.messages) > 1:
                console.print(
                    "[dim]Note this is not a new chat, modifications to the system prompt have limited impact on answers.")
        else:
            console.print(
                f"[dim]No system prompt found in messages.")

    def set_model(self, new_model: str):
        old_model = self.model
        if not new_model:
            console.print(
                f"[dim]Empty input, the model remains '{old_model}'.")
            return
        self.model = str(new_model)
        if "gpt-4-32k" in self.model:
            self.tokens_limit = 32768
        elif "gpt-4" in self.model:
            self.tokens_limit = 8192
        elif "gpt-3.5-turbo" in self.model:
            self.tokens_limit = 4096
        else:
            self.tokens_limit = -1
        console.print(
            f"[dim]Model has been set from '{old_model}' to '{new_model}'.")

    def set_timeout(self, timeout):
        try:
            self.timeout = float(timeout)
        except ValueError:
            console.print("[red]Input must be a number")
            return
        console.print(f"[dim]API timeout set to [green]{timeout}s[/].")


class CustomCompleter(Completer):
    commands = [
        '/raw', '/multi', '/stream', '/tokens', '/last', '/copy', '/model', '/save', '/system', '/timeout', '/undo', '/delete', '/help', '/exit'
    ]

    copy_actions = [
        "code",
        "all"
    ]

    delete_actions = [
        "first",
        "all"
    ]

    available_models = [
        "gpt-3.5-turbo",
        "gpt-3.5-turbo-0301",
        "gpt-4",
        "gpt-4-0314",
        "gpt-4-32k",
        "gpt-4-32k-0314",
    ]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith('/'):
            # Check if it's a /model command
            if text.startswith('/model '):
                model_prefix = text[7:]
                for model in self.available_models:
                    if model.startswith(model_prefix):
                        yield Completion(model, start_position=-len(model_prefix))
            # Check if it's a /copy command
            elif text.startswith('/copy '):
                copy_prefix = text[6:]
                for copy in self.copy_actions:
                    if copy.startswith(copy_prefix):
                        yield Completion(copy, start_position=-len(copy_prefix))

            # Check if it's a /delete command
            elif text.startswith('/delete '):
                delete_prefix = text[8:]
                for delete in self.delete_actions:
                    if delete.startswith(delete_prefix):
                        yield Completion(delete, start_position=-len(delete_prefix))

            else:
                for command in self.commands:
                    if command.startswith(text):
                        yield Completion(command, start_position=-len(text))


def count_token(messages: list):
    '''计算 messages 占用的 token
    `cl100k_base` 编码适用于: gpt-4, gpt-3.5-turbo, text-embedding-ada-002'''
    encoding = tiktoken.get_encoding("cl100k_base")
    length = 0
    for message in messages:
        length += len(encoding.encode(
            f"role: {message['role']}, content: {message['content']}"))
    return length


class NumberValidator(Validator):
    def validate(self, document):
        text = document.text
        if not text.isdigit():
            raise ValidationError(message="Please input an Integer!",
                                  cursor_position=len(text))


def print_message(message):
    '''打印单条来自 ChatGPT 或用户的消息'''
    role = message["role"]
    content = message["content"]
    if role == "user":
        print(f"> {content}")
    elif role == "assistant":
        console.print("ChatGPT: ", end='', style="bold cyan")
        if ChatMode.raw_mode:
            print(content)
        else:
            console.print(Markdown(content), new_line_start=True)


def copy_code(message, select_code_idx: int = None):
    '''Copy the code in ChatGPT's last reply to Clipboard'''
    code_list = re.findall(r'```[\s\S]*?```', message["content"])
    if len(code_list) == 0:
        console.print("[dim]No code found")
        return

    if len(code_list) == 1 and select_code_idx is None:
        selected_code = code_list[0]
        # if there's only one code, and select_code_idx not given, just copy it
    else:
        if select_code_idx is None:
            console.print(
                "[dim]There are more than one code in ChatGPT's last reply")
            code_num = 0
            for codes in code_list:
                code_num += 1
                console.print(f"[yellow]Code {code_num}:")
                console.print(Markdown(codes))

            select_code_idx = prompt(
                "Please select which code to copy: ", style=style, validator=NumberValidator())
            # get the number of the selected code
        try:
            selected_code = code_list[int(select_code_idx)-1]
        except ValueError:
            console.print("[red]Code index must be an Integer")
            return
        except IndexError:
            if len(code_list) == 1:
                console.print(
                    "[red]Index out of range: There is only one code in ChatGPT's last reply")
            else:
                console.print(
                    f"[red]Index out of range: You should input an Integer in range 1 ~ {len(code_list)}")
                # show idx range
                # use len(code_list) instead of code_num as the max of idx
                # in order to avoid error 'UnboundLocalError: local variable 'code_num' referenced before assignment' when inputing select_code_idx directly
            return

    bpos = selected_code.find('\n')    # code begin pos.
    epos = selected_code.rfind('```')  # code end pos.
    pyperclip.copy(''.join(selected_code[bpos+1:epos-1]))
    # erase code begin and end sign
    console.print("[dim]Code copied to Clipboard")


def handle_command(command: str, chat_gpt: ChatGPT):
    '''处理斜杠(/)命令'''
    if command == '/raw':
        ChatMode.toggle_raw_mode()
    elif command == '/multi':
        ChatMode.toggle_multi_line_mode()
    elif command == '/stream':
        ChatMode.toggle_stream_mode()

    elif command == '/tokens':
        # here: tokens count may be wrong because of the support of changing AI models, because gpt-4 API allows max 8192 tokens (gpt-4-32k up to 32768)
        # one possible solution is: there are only 6 models under '/v1/chat/completions' now, and with if-elif-else all cases can be enumerated
        # but that means, when the model list is updated, here needs to be updated too

        # tokens limit judge moved to ChatGPT.set_model function

        console.print(Panel(f"[bold bright_magenta]Total Tokens Spent:[/]\t{chat_gpt.total_tokens_spent}\n"
                            f"[bold green]Current Tokens:[/]\t\t{chat_gpt.current_tokens}/[bold]{chat_gpt.tokens_limit}",
                            title='token_summary', title_align='left', width=40, style='dim'))

    elif command == '/usage':
        with console.status("Getting credit usage...") as status:
            credit_usage = chat_gpt.get_credit_usage()
        if not credit_usage:
            return
        console.print(Panel(f"[bold blue]Total Granted:[/]\t${credit_usage.get('total_granted')}\n"
                            f"[bold bright_yellow]Used:[/]\t\t${credit_usage.get('total_used')}\n"
                            f"[bold green]Available:[/]\t${credit_usage.get('total_available')}",
                            title=credit_usage.get('object'), title_align='left', width=35, style='dim'))
        console.print(
            "[red]`[bright_magenta]/usage[/]` command is currently unavailable, it's not sure if this command will be available again or not.")

    elif command.startswith('/model'):
        args = command.split()
        if len(args) > 1:
            new_model = args[1]
        else:
            new_model = prompt(
                "OpenAI API model: ", default=chat_gpt.model, style=style)
        if new_model != chat_gpt.model:
            chat_gpt.set_model(new_model)
        else:
            console.print("[dim]No change.")

    elif command == '/last':
        reply = chat_gpt.messages[-1]
        print_message(reply)

    elif command.startswith('/copy'):
        args = command.split()
        reply = chat_gpt.messages[-1]
        if len(args) > 1:
            if args[1] == 'all':
                pyperclip.copy(reply["content"])
                console.print("[dim]Last reply copied to Clipboard")
            elif args[1] == 'code':
                if len(args) > 2:
                    copy_code(reply, args[2])
                else:
                    copy_code(reply)
            else:
                console.print(
                    "[dim]Nothing to do. Available copy command: `[bright_magenta]/copy code \[index][/]` or `[bright_magenta]/copy all[/]`")
        else:
            pyperclip.copy(reply["content"])
            console.print("[dim]Last reply copied to Clipboard")

    elif command.startswith('/save'):
        args = command.split()
        if len(args) > 1:
            filename = args[1]
        else:
            gen_filename = chat_gpt.gen_title()
            if gen_filename:
                gen_filename = gen_filename.replace('"','')
                gen_filename = f"./chat_history_{gen_filename}.json"
            date_filename = f'./chat_history_{datetime.now().strftime("%Y-%m-%d_%H,%M,%S")}.json'
            filename = prompt(
                "Save to: ", default=gen_filename or date_filename, style=style)
        chat_gpt.save_chat_history(filename)

    elif command.startswith('/system'):
        args = command.split()
        if len(args) > 1:
            new_content = ' '.join(args[1:])
        else:
            new_content = prompt(
                "System prompt: ", default=chat_gpt.messages[0]['content'], style=style)
        if new_content != chat_gpt.messages[0]['content']:
            chat_gpt.modify_system_prompt(new_content)
        else:
            console.print("[dim]No change.")

    elif command.startswith('/timeout'):
        args = command.split()
        if len(args) > 1:
            new_timeout = args[1]
        else:
            new_timeout = prompt(
                "OpenAI API timeout: ", default=str(chat_gpt.timeout), style=style)
        if new_timeout != str(chat_gpt.timeout):
            chat_gpt.set_timeout(new_timeout)
        else:
            console.print("[dim]No change.")

    elif command == '/undo':
        if len(chat_gpt.messages) > 2:
            question = chat_gpt.messages.pop()
            if question['role'] == "assistant":
                question = chat_gpt.messages.pop()
            truncated_question = question['content'].split('\n')[0]
            if len(question['content']) > len(truncated_question):
                truncated_question += "..."
            console.print(
                f"[dim]Last question: '{truncated_question}' and it's answer has been removed.")
        else:
            console.print("[dim]Nothing to undo.")

    elif command.startswith('/delete'):
        args = command.split()
        if len(args) > 1:
            if args[1] == 'first':
                chat_gpt.delete_first_conversation()
            elif args[1] == 'all':
                del chat_gpt.messages[1:]
                chat_gpt.current_tokens = count_token(chat_gpt.messages)
                # recount current tokens
                console.print("[dim]Current chat deleted.")
            else:
                console.print(
                    "[dim]Nothing to do. Avaliable delete command: `[bright_magenta]/delete first[/]` or `[bright_magenta]/delete all[/]`")
        else:
            chat_gpt.delete_first_conversation()

    elif command == '/exit':
        raise EOFError

    else:
        console.print('''[bold]Available commands:[/]
    /raw                     - Toggle raw mode (showing raw text of ChatGPT's reply)
    /multi                   - Toggle multi-line mode (allow multi-line input)
    /stream                  - Toggle stream output mode (flow print the answer)
    /tokens                  - Show the total tokens spent and the tokens for the current conversation
    /last                    - Display last ChatGPT's reply
    /copy (all)              - Copy the full ChatGPT's last reply (raw) to Clipboard
    /copy code \[index]       - Copy the code in ChatGPT's last reply to Clipboard
    /save \[filename_or_path] - Save the chat history to a file
    /model \[model_name]      - Change AI model
    /system \[new_prompt]     - Modify the system prompt
    /timeout \[new_timeout]   - Modify the api timeout
    /undo                    - Undo the last question and remove its answer
    /delete (first)          - Delete the first conversation in current chat
    /delete all              - Clear all messages and conversations current chat
    /help                    - Show this help message
    /exit                    - Exit the application''')


def load_chat_history(file_path):
    '''从 file_path 加载聊天记录'''
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            chat_history = json.load(f)
        return chat_history
    except FileNotFoundError:
        console.print(f"[bright_red]File not found: {file_path}")
    except json.JSONDecodeError:
        console.print(f"[bright_red]Invalid JSON format in file: {file_path}")
    return None


def create_key_bindings():
    '''自定义回车事件绑定，实现斜杠命令的提交忽略多行模式'''
    key_bindings = KeyBindings()

    @key_bindings.add(Keys.Enter, eager=True)
    def _(event):
        buffer = event.current_buffer
        text = buffer.text.strip()
        if text.startswith('/') or not ChatMode.multi_line_mode:
            buffer.validate_and_handle()
        else:
            buffer.insert_text('\n')

    return key_bindings


def main(args):
    # 从 .env 文件中读取 OPENAI_API_KEY
    load_dotenv()

    # if 'key' arg triggered, load the api key from .env with the given key-name;
    # otherwise load the api key with the key-name "OPENAI_API_KEY"
    if args.key:
        api_key = os.environ.get(args.key)
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        api_key = prompt("OpenAI API Key not found, please input: ")

    api_timeout = int(os.environ.get("OPENAI_API_TIMEOUT", "30"))

    chat_gpt = ChatGPT(api_key, api_timeout)

    console.print(
        "[dim]Hi, welcome to chat with GPT. Type `[bright_magenta]/help[/]` to display available commands.")

    if args.model:
        chat_gpt.set_model(args.model)

    if args.multi:
        ChatMode.toggle_multi_line_mode()

    if args.raw:
        ChatMode.toggle_raw_mode()

    if args.load:
        chat_history = load_chat_history(args.load)
        if chat_history:
            chat_gpt.messages = chat_history
            for message in chat_gpt.messages:
                print_message(message)
            chat_gpt.current_tokens = count_token(chat_gpt.messages)
            console.print(
                f"[dim]Chat history successfully loaded from: [bright_magenta]{args.load}", highlight=False)

    session = PromptSession()

    # 自定义命令补全，保证输入‘/’后继续显示补全
    commands = CustomCompleter()

    # 绑定回车事件，达到自定义多行模式的效果
    key_bindings = create_key_bindings()

    while True:
        try:
            message = session.prompt(
                '> ', completer=commands, complete_while_typing=True, key_bindings=key_bindings)

            if message.startswith('/'):
                command = message.strip().lower()
                handle_command(command, chat_gpt)
            else:
                if not message:
                    continue

                log.info(f"> {message}")
                chat_gpt.handle(message)

                if message.lower() in ['再见', 'bye', 'goodbye', '结束', 'end', '退出', 'exit', 'quit']:
                    break

        except KeyboardInterrupt:
            continue
        except EOFError:
            console.print("Exiting...")
            break

    log.info(f"Total tokens spent: {chat_gpt.total_tokens_spent}")
    console.print(
        f"[bright_magenta]Total tokens spent: [bold]{chat_gpt.total_tokens_spent}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Chat with GPT-3.5')
    parser.add_argument('--load', metavar='FILE', type=str,
                        help='Load chat history from file')
    parser.add_argument('--key', type=str, help='choose the API key to load')
    parser.add_argument('--model', type=str, help='choose the AI model to use')
    parser.add_argument('-m', '--multi', action='store_true',
                        help='Enable multi-line mode')
    parser.add_argument('-r', '--raw', action='store_true',
                        help='Enable raw mode')
    args = parser.parse_args()

    main(args)

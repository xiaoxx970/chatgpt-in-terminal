#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import concurrent.futures
import json
import logging
import os
import platform
import re
import sys
import threading
import time
from configparser import ConfigParser
from datetime import date, datetime, timedelta
from importlib.resources import read_text
from pathlib import Path
from queue import Queue
from typing import Dict, List

import pyperclip
import requests
import sseclient

from packaging.version import parse as parse_version
from prompt_toolkit import PromptSession, prompt
from prompt_toolkit.completion import (Completer, Completion, NestedCompleter,
                                       PathCompleter)
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


from .Ai.AiClass import ChatMode
from .Ai.OpenAi import openai
from .Ai.Poe import poe_mode

if not (__name__ == "__main__"):
    from . import __version__


Use_tiktoken = 0    #临时设定的变量(用于解决tiktoken库无法使用的问题)

if Use_tiktoken:
    import tiktoken


data_dir = Path.home() / '.gpt-term'
data_dir.mkdir(parents=True, exist_ok=True)
config_path = data_dir / 'config.ini'
if not config_path.exists():
    with config_path.open('w') as f:
        f.write(read_text('gpt_term', 'config.ini'))

# 日志记录到 chat.log，注释下面这行可不记录日志,如果要注释Poe模式下的注释,请到Poe类定义处
logging.basicConfig(filename=f'{data_dir}/chat.log', format='%(asctime)s %(name)s: %(levelname)-6s %(message)s',
                    datefmt='[%Y-%m-%d %H:%M:%S]', level=logging.INFO)

log = logging.getLogger("chat")

console = Console()
ChatMode.init(console=console)
style = Style.from_dict({
    "prompt": "ansigreen",  # 将提示符设置为绿色
})

remote_version = None
if not (__name__ == "__main__"):
    local_version = parse_version(__version__)
else:
    local_version = "test"
threadlock_remote_version = threading.Lock()


class CommandCompleter(Completer):
    def __init__(self):
        self.nested_completer = NestedCompleter.from_nested_dict({
            '/raw': None,
            '/multi': None,
            '/stream': {"visible", "ellipsis"},
            '/tokens': None,
            '/usage': None,
            '/last': None,
            '/copy': {"code", "all"},
            '/model': {
                "gpt-3.5-turbo",
                "gpt-3.5-turbo-0301",
                "gpt-4",
                "gpt-4-0314",
                "gpt-4-32k",
                "gpt-4-32k-031"},
            '/save': PathCompleter(file_filter=self.path_filter),
            '/system': None,
            '/rand': None,
            '/temperature': None,
            '/title': None,
            '/timeout': None,
            '/undo': None,
            '/delete': {"first", "all"},
            '/reset': None,
            '/version': None,
            '/help': None,
            '/exit': None,
        })

    def path_filter(self, filename):
        # 路径自动补全，只补全json文件和文件夹
        return filename.endswith(".json") or os.path.isdir(filename)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith('/'):
            for cmd in self.nested_completer.options.keys():
                # 如果匹配到第一层命令
                if text in cmd:
                    yield Completion(cmd, start_position=-len(text))
            # 如果匹配到第n层命令
            if ' ' in text:
                for sub_cmd in self.nested_completer.get_completions(document, complete_event):
                    yield sub_cmd


# 自定义命令补全，保证输入‘/’后继续显示补全
command_completer = CommandCompleter()




class NumberValidator(Validator):
    def validate(self, document):
        text = document.text
        if not text.isdigit():
            raise ValidationError(message="Please input an Integer!",
                                  cursor_position=len(text))

class FloatRangeValidator(Validator):
    def __init__(self, min_value=None, max_value=None):
        self.min_value = min_value
        self.max_value = max_value

    def validate(self, document):
        try:
            value = float(document.text)
        except ValueError:
            raise ValidationError(message='Input must be a number')

        if self.min_value is not None and value < self.min_value:
            raise ValidationError(message=f'Input must be at least {self.min_value}')
        if self.max_value is not None and value > self.max_value:
            raise ValidationError(message=f'Input must be at most {self.max_value}')
        
temperature_validator = FloatRangeValidator(min_value=0.0, max_value=2.0)

def print_message(message: Dict[str, str]):
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


def copy_code(message: Dict[str, str], select_code_idx: int = None):
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


def change_CLI_title(new_title: str):
    if platform.system() == "Windows":
        os.system(f"title {new_title}")
    else:
        print(f"\033]0;{new_title}\007", end='')
        sys.stdout.flush()
        # flush the stdout buffer in order to making the control sequences effective immediately
    log.debug(f"CLI Title changed to '{new_title}'")

def get_levenshtein_distance(s1: str, s2: str):
    s1_len = len(s1)
    s2_len = len(s2)

    v = [[0 for _ in range(s2_len+1)] for _ in range(s1_len+1)]
    for i in range(0, s1_len+1):
        for j in range(0, s2_len+1):
            if i == 0:
                v[i][j] = j
            elif j == 0:
                v[i][j] = i
            elif s1[i-1] == s2[j-1]:
                v[i][j] = v[i-1][j-1]
            else:
                v[i][j] = min(v[i-1][j-1], min(v[i][j-1], v[i-1][j])) + 1

    return v[s1_len][s2_len]


def handle_command(command: str, chat_gpt: openai or poe_mode, key_bindings: KeyBindings, chat_save_perfix: str):
    '''处理斜杠(/)命令'''
    if command == '/raw':
        ChatMode.toggle_raw_mode()
    elif command == '/multi':
        ChatMode.toggle_multi_line_mode()

    elif command.startswith('/stream'):
        args = command.split()
        if len(args) > 1:
            chat_gpt.set_stream_overflow(args[1])
        else:
            ChatMode.toggle_stream_mode()

    elif command == '/tokens':
        chat_gpt.threadlock_total_tokens_spent.acquire()
        console.print(Panel(f"[bold bright_magenta]Total Tokens Spent:[/]\t{chat_gpt.total_tokens_spent}\n"
                            f"[bold green]Current Tokens:[/]\t\t{chat_gpt.current_tokens}/[bold]{chat_gpt.tokens_limit}",
                            title='token_summary', title_align='left', width=40))
        chat_gpt.threadlock_total_tokens_spent.release()

    elif command == '/usage':
        with console.status("[cyan]Getting credit usage..."):
            if not chat_gpt.get_credit_usage():
                return
        console.print(Panel(f"[bold green]Total Granted:[/]\t\t${format(chat_gpt.credit_total_granted, '.2f')}\n"
                            f"[bold cyan]Used This Month:[/]\t${format(chat_gpt.credit_used_this_month, '.2f')}\n"
                            f"[bold blue]Used Total:[/]\t\t${format(chat_gpt.credit_total_used, '.2f')}",
                            title="Credit Summary", title_align='left', subtitle=f"[bright_blue]Plan: {chat_gpt.credit_plan}", width=35))

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
                gen_filename = re.sub(r'[\/\\\*\?\"\<\>\|\:]', '', gen_filename)
                gen_filename = f"{chat_save_perfix}{gen_filename}.json"
            # here: if title is already generated or generating, just use it
            # but title auto generation can also be disabled; therefore when title is not generated then try generating a new one
            date_filename = f'{chat_save_perfix}{datetime.now().strftime("%Y-%m-%d_%H,%M,%S")}.json'
            filename = prompt(
                "Save to: ", default=gen_filename or date_filename, style=style)
        chat_gpt.save_chat_history(filename)

    elif command.startswith('/system'):
        args = command.split()
        if len(args) > 1:
            new_content = ' '.join(args[1:])
        else:
            new_content = prompt(
                "System prompt: ", default=chat_gpt.messages[0]['content'], style=style, key_bindings=key_bindings)
        if new_content != chat_gpt.messages[0]['content']:
            chat_gpt.modify_system_prompt(new_content)
        else:
            console.print("[dim]No change.")

    elif command.startswith('/rand') or command.startswith('/temperature'):
        args = command.split()
        if len(args) > 1:
            new_temperature = args[1]
        else:
            new_temperature = prompt(
                "New Randomness: ", default=str(chat_gpt.temperature), style=style, validator=temperature_validator)
        if new_temperature != str(chat_gpt.temperature):
            chat_gpt.set_temperature(new_temperature)
        else:
            console.print("[dim]No change.")            

    elif command.startswith('/title'):
        args = command.split()
        if len(args) > 1:
            chat_gpt.title = ' '.join(args[1:])
            change_CLI_title(chat_gpt.title)
        else:
            # generate a new title
            new_title = chat_gpt.gen_title(force=True)
            if not new_title:
                console.print("[red]Failed to generate title.")
                return
        console.print(f"[dim]CLI Title changed to '{chat_gpt.title}'")

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
            chat_gpt.current_tokens = chat_gpt.count_token(chat_gpt.messages)
        else:
            console.print("[dim]Nothing to undo.")

    elif command.startswith('/reset'):
        chat_gpt.delete_all_conversation()

    elif command.startswith('/delete'):
        args = command.split()
        if len(args) > 1:
            if args[1] == 'first':
                chat_gpt.delete_first_conversation()
            elif args[1] == 'all':
                chat_gpt.delete_all_conversation()
            else:
                console.print(
                    "[dim]Nothing to do. Avaliable delete command: `[bright_magenta]/delete first[/]` or `[bright_magenta]/delete all[/]`")
        else:
            chat_gpt.delete_first_conversation()

    elif command == '/version':
        threadlock_remote_version.acquire()
        console.print(Panel(f"[bold blue]Local Version:[/]\tv{str(local_version)}\n"
                            f"[bold green]Remote Version:[/]\tv{str(remote_version)}",
                            title='Version', title_align='left', width=28))
        threadlock_remote_version.release()

    elif command == '/exit':
        raise EOFError

    elif command == '/help':
        console.print('''[bold]Available commands:[/]
    /raw                     - Toggle raw mode (showing raw text of ChatGPT's reply)
    /multi                   - Toggle multi-line mode (allow multi-line input)
    /stream \[overflow_mode]  - Toggle stream output mode (flow print the answer)
    /tokens                  - Show the total tokens spent and the tokens for the current conversation
    /usage                   - Show total credits and current credits used
    /last                    - Display last ChatGPT's reply
    /copy (all)              - Copy the full ChatGPT's last reply (raw) to Clipboard
    /copy code \[index]       - Copy the code in ChatGPT's last reply to Clipboard
    /save \[filename_or_path] - Save the chat history to a file, suggest title if filename_or_path not provided
    /model \[model_name]      - Change AI model
    /system \[new_prompt]     - Modify the system prompt
    /rand \[randomness]       - Set Model sampling temperature (0~2)
    /title \[new_title]       - Set title for this chat, if new_title is not provided, a new title will be generated
    /timeout \[new_timeout]   - Modify the api timeout
    /undo                    - Undo the last question and remove its answer
    /delete (first)          - Delete the first conversation in current chat
    /delete all              - Clear all messages and conversations current chat
    /version                 - Show gpt-term local and remote version
    /help                    - Show this help message
    /exit                    - Exit the application''')
        
    else:
        set_command = set(command)
        min_levenshtein_distance = len(command)
        most_similar_command = ""
        for slash_command in command_completer.nested_completer.options.keys():
            this_levenshtein_distance = get_levenshtein_distance(command, slash_command)
            if this_levenshtein_distance < min_levenshtein_distance:
                set_slash_command = set(slash_command)
                if len(set_command & set_slash_command) / len(set_command | set_slash_command) >= 0.75:
                    most_similar_command = slash_command
                    min_levenshtein_distance = this_levenshtein_distance
        
        console.print(f"Unrecognized Slash Command `[bold red]{command}[/]`", end=" ")
        if most_similar_command:
            console.print(f"Do you mean `[bright magenta]{most_similar_command}[/]`?")
        else:
            console.print("")
        console.print("Use `[bright magenta]/help[/]` to see all available slash commands")


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
    '''自定义回车事件绑定，实现斜杠命令的提交忽略多行模式，以及单行模式下 `esc+Enter` 换行'''
    key_bindings = KeyBindings()

    @key_bindings.add(Keys.Enter)
    def _(event):
        buffer = event.current_buffer
        text = buffer.text.strip()
        if text.startswith('/') or not ChatMode.multi_line_mode:
            buffer.validate_and_handle()
        else:
            buffer.insert_text('\n')

    @key_bindings.add(Keys.Escape, Keys.Enter)
    def _(event):
        buffer = event.current_buffer
        if ChatMode.multi_line_mode:
            buffer.validate_and_handle()
        else:
            buffer.insert_text('\n')

    return key_bindings


def get_remote_version():
    global remote_version
    try:
        response = requests.get(
            "https://pypi.org/pypi/gpt-term/json", timeout=10)
        response.raise_for_status()
        threadlock_remote_version.acquire()
        remote_version = parse_version(response.json()["info"]["version"])
        threadlock_remote_version.release()
    except requests.RequestException as e:
        log.error("Get remote version failed")
        log.exception(e)
        return
    log.debug(f"Remote version: {str(remote_version)}")


def write_config(config_ini: ConfigParser):
    with open(f'{data_dir}/config.ini', 'w') as configfile:
        config_ini.write(configfile)


def set_config_by_args(args: argparse.Namespace, config_ini: ConfigParser):
    config_need_to_set = {}
    if args.set_apikey:     config_need_to_set.update({"OPENAI_API_KEY"      : args.set_apikey})
    if args.set_timeout:    config_need_to_set.update({"OPENAI_API_TIMEOUT"  : args.set_timeout})
    if args.set_saveperfix: config_need_to_set.update({"CHAT_SAVE_PERFIX"    : args.set_saveperfix})
    if args.set_loglevel:   config_need_to_set.update({"LOG_LEVEL"           : args.set_loglevel})
    if args.set_gentitle:   config_need_to_set.update({"AUTO_GENERATE_TITLE" : args.set_gentitle})

    if len(config_need_to_set) == 0:
        return
    # nothing to set

    for key, val in config_need_to_set.items():
        config_ini['DEFAULT'][key] = str(val)
        console.print(f"Config item `[bright_magenta]{key}[/]` is set to [green]{val}[/]")

    write_config(config_ini)
    exit(0)


def main():
    parser = argparse.ArgumentParser(description='Use ChatGPT in terminal')
    parser.add_argument('--version', action='version', version=f'%(prog)s v{local_version}')
    parser.add_argument('--load', metavar='FILE', type=str, help='Load chat history from file')
    parser.add_argument('--key', type=str, help='Choose the API key to load')
    parser.add_argument('--model', type=str, help='Choose the AI model to use')
    parser.add_argument('-m', '--multi', action='store_true', help='Enable multi-line mode')
    parser.add_argument('-r', '--raw', action='store_true', help='Enable raw mode')
    # normal function args

    parser.add_argument('--set-apikey', metavar='KEY', type=str, help='Set API key for OpenAI')
    parser.add_argument('--set-timeout', metavar='SEC', type=int, help='Set maximum waiting time for API requests')
    parser.add_argument('--set-gentitle', metavar='BOOL', type=str, help='Set whether to automatically generate a title for chat')
    parser.add_argument('--set-saveperfix', metavar='PERFIX', type=str, help='Set chat history file\'s save perfix')
    parser.add_argument('--set-loglevel', metavar='LEVEL', type=str, help='Set log level: DEBUG, INFO, WARNING, ERROR, CRITICAL')
    # setting args
    args = parser.parse_args()

    # 读取配置文件
    config_ini = ConfigParser()
    config_ini.read(f'{data_dir}/config.ini', encoding='utf-8')
    config = config_ini['DEFAULT']

    set_config_by_args(args, config_ini)

    try:
        log_level = getattr(logging, config.get("LOG_LEVEL", "INFO").upper())
    except AttributeError as e:
        console.print(
            f"[dim]Invalid log level: {e}, check config.ini file. Set log level to INFO.")
        log_level = logging.INFO
    log.setLevel(log_level)
    # log level set must be before debug logs, because default log level is INFO, and before new log level being set debug logs will not be written to log file
    log.info("GPT-Term start")

    log.debug(f"Local version: {str(local_version)}")
    # get local version from pkg resource

    check_remote_update_thread = threading.Thread(target=get_remote_version, daemon=True)
    check_remote_update_thread.start()
    log.debug("Remote version get thread started")
    # try to get remote version and check update

    # if 'key' arg triggered, load the api key from config.ini with the given key-name;
    # otherwise load the api key with the key-name "OPENAI_API_KEY"
    if args.key:
        log.debug(f"Try loading API key with {args.key} from config.ini")
        api_key = config.get(args.key)
    else:
        api_key = config.get("OPENAI_API_KEY")

    if not api_key:
        log.debug("API Key not found, waiting for input")
        api_key = prompt("OpenAI API Key not found, please input: ")
        if confirm('Save API Key to config file?'):
            config["OPENAI_API_KEY"] = api_key
            write_config(config_ini)

    api_key_log = api_key[:3] + '*' * (len(api_key) - 7) + api_key[-4:]
    log.debug(f"Loaded API Key: {api_key_log}")

    api_timeout = config.getfloat("OPENAI_API_TIMEOUT", 30)
    log.debug(f"API Timeout set to {api_timeout}")

    chat_save_perfix = config.get("CHAT_SAVE_PERFIX", "./chat_history_")

    openai_api_key="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"
    poe_api_key="tKSUqU_FYfgznLgFkudAmw%3D%3D"
    chat_gpt = poe_mode(api_key=poe_api_key,console=console,timeout=api_timeout,log=log,data_dir=data_dir,Use_tiktoken=1)
    #chat_gpt = openai(api_key=openai_api_key,console=console,timeout=api_timeout,log=log,data_dir=data_dir,Use_tiktoken=1)

    if not config.getboolean("AUTO_GENERATE_TITLE", True):
        chat_gpt.auto_gen_title_background_enable = False
        log.debug("Auto title generation [bright_red]disabled[/]")

    gen_title_daemon_thread = threading.Thread(
        target=chat_gpt.auto_gen_title_background, daemon=True)
    gen_title_daemon_thread.start()
    log.debug("Title generation daemon thread started")

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
            change_CLI_title(args.load.rstrip(".json"))
            chat_gpt.messages = chat_history
            for message in chat_gpt.messages:
                print_message(message)
            chat_gpt.current_tokens = chat_gpt.count_token(chat_gpt.messages)
            log.info(f"Chat history successfully loaded from: {args.load}")
            console.print(
                f"[dim]Chat history successfully loaded from: [bright_magenta]{args.load}", highlight=False)

    session = PromptSession()

    # 绑定回车事件，达到自定义多行模式的效果
    key_bindings = create_key_bindings()

    while True:
        try:
            message = session.prompt(
                '> ', completer=command_completer, complete_while_typing=True, key_bindings=key_bindings)

            if message.startswith('/'):
                command = message.strip().lower()
                handle_command(command, chat_gpt,
                               key_bindings, chat_save_perfix)
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
    
    threadlock_remote_version.acquire()
    if remote_version and remote_version > local_version:
        console.print(Panel(Group(
            Markdown("Use `pip install --upgrade gpt-term` to upgrade."),
            Markdown("Visit our [GitHub Site](https://github.com/xiaoxx970/chatgpt-in-terminal) to see what have been changed!")),
            title=f"New Version Available: [red]v{str(local_version)}[/] -> [green]v{str(remote_version)}[/]",
            width=58, style="blue", title_align="left"))
    threadlock_remote_version.release()

if __name__ == "__main__":
    main()


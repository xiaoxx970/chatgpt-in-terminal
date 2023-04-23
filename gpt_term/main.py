#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import concurrent.futures
import json
import logging
import os
import platform
import re
import shutil
import sys
import threading
import time
from configparser import ConfigParser
from datetime import date, datetime, timedelta
from queue import Queue
from typing import Dict, List

import pyperclip
import requests
import sseclient
import tiktoken
from packaging.version import parse as parse_version
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

from . import __version__

data_dir = os.path.expanduser("~") + "/.gpt-term"
if not os.path.exists(data_dir):
    os.makedirs(data_dir)
    shutil.copy('config.ini', data_dir)

# 日志记录到 chat.log，注释下面这行可不记录日志
logging.basicConfig(filename=f'{data_dir}/chat.log', format='%(asctime)s %(name)s: %(levelname)-6s %(message)s',
                    datefmt='[%Y-%m-%d %H:%M:%S]', level=logging.INFO, encoding="UTF-8")

log = logging.getLogger("chat")

console = Console()

style = Style.from_dict({
    "prompt": "ansigreen",  # 将提示符设置为绿色
})

remote_version = None
local_version = parse_version(__version__)
threadlock_remote_version = threading.Lock()


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
    def __init__(self, api_key: str, timeout: float):
        self.api_key = api_key
        self.endpoint = "https://api.openai.com/v1/chat/completions"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        self.messages = [
            {"role": "system", "content": f"You are a helpful assistant.\nKnowledge cutoff: 2021-09\nCurrent date: {datetime.now().strftime('%Y-%m-%d')}"}]
        self.model = 'gpt-3.5-turbo'
        self.tokens_limit = 4096
        # as default: gpt-3.5-turbo has a tokens limit as 4096
        # when model changes, tokens will also be changed
        self.total_tokens_spent = 0
        self.current_tokens = count_token(self.messages)
        self.timeout = timeout
        self.title: str = None
        self.gen_title_messages = Queue()
        self.auto_gen_title_background_enable = True
        self.threadlock_total_tokens_spent = threading.Lock()

        self.credit_total_granted = 0
        self.credit_total_used = 0
        self.credit_used_this_month = 0
        self.credit_plan = ""

    def add_total_tokens(self, tokens: int):
        self.threadlock_total_tokens_spent.acquire()
        self.total_tokens_spent += tokens
        self.threadlock_total_tokens_spent.release()

    def send_request(self, data):
        try:
            with console.status(f"[bold cyan]ChatGPT is thinking..."):
                response = requests.post(
                    self.endpoint, headers=self.headers, data=json.dumps(data), timeout=self.timeout, stream=ChatMode.stream_mode)
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

    def send_request_silent(self, data):
        # this is a silent sub function, for sending request without outputs (silently)
        # it SHOULD NOT be triggered or used by not-silent functions
        # it is only used by gen_title_silent now
        try:
            response = requests.post(
                self.endpoint, headers=self.headers, data=json.dumps(data), timeout=self.timeout)
            # match 4xx error codes
            if response.status_code // 100 == 4:
                error_msg = response.json()['error']['message']
                log.error(error_msg)
                return None

            response.raise_for_status()
            return response
        except requests.exceptions.ReadTimeout as e:
            log.error("Automatic generating title failed as timeout")
            return None
        except requests.exceptions.RequestException as e:
            log.exception(e)
            return None

    def process_stream_response(self, response: requests.Response):
        reply: str = ""
        client = sseclient.SSEClient(response)
        with Live(console=console, auto_refresh=False) as live:
            try:
                rprint("[bold cyan]ChatGPT: ")
                for event in client.events():
                    if event.data == '[DONE]':
                        # finish_reason = part["choices"][0]['finish_reason']
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

    def process_response(self, response: requests.Response):
        if ChatMode.stream_mode:
            return self.process_stream_response(response)
        else:
            response_json = response.json()
            log.debug(f"Response: {response_json}")
            reply_message: Dict[str, str] = response_json["choices"][0]["message"]
            print_message(reply_message)
            return reply_message

    def delete_first_conversation(self):
        if len(self.messages) >= 3:
            question = self.messages[1]
            del self.messages[1]
            if self.messages[1]['role'] == "assistant":
                # 如果第二个信息是回答才删除
                del self.messages[1]
            truncated_question = question['content'].split('\n')[0]
            if len(question['content']) > len(truncated_question):
                truncated_question += "..."

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
                self.add_total_tokens(self.current_tokens)

                if len(self.messages) == 3 and self.auto_gen_title_background_enable:
                    self.gen_title_messages.put(self.messages[1]['content'])

                if self.tokens_limit - self.current_tokens in range(1, 500):
                    console.print(
                        f"[dim]Approaching the tokens limit: {self.tokens_limit - self.current_tokens} tokens left")
                # approaching tokens limit (less than 500 left), show info

        except Exception as e:
            console.print(
                f"[red]Error: {str(e)}. Check log for more information")
            log.exception(e)
            self.save_chat_history_urgent()
            raise EOFError

        return reply_message

    def gen_title(self, force: bool = False):
        # Empty the title if there is only system message left
        if len(self.messages) < 2:
            self.title = None
            return

        try:
            with console.status("[bold cyan]Waiting last generationg to finish..."):
                self.gen_title_messages.join()
            if self.title and not force:
                return self.title

            # title not generated, do

            content_this_time = self.messages[1]['content']
            self.gen_title_messages.put(content_this_time)
            with console.status("[bold cyan]Generating title... [/](Ctrl-C to skip)"):
                self.gen_title_messages.join()
        except KeyboardInterrupt:
            console.print("Skip wait.", style="bold cyan")
            raise

        return self.title

    def gen_title_silent(self, content: str):
        # this is a silent sub function, only for sub thread which auto-generates title when first conversation is made and debug functions
        # it SHOULD NOT be triggered or used by any other functions or commands
        # because of the usage of this subfunction, no check for messages list length and title appearance is needed
        prompt = f'Generate title shorter than 10 words for the following content in content\'s language. The tilte contains ONLY words. DO NOT include line-break. \n\nContent: """\n{content}\n"""'
        messages = [{"role": "user", "content": prompt}]
        data = {
            "model": "gpt-3.5-turbo",
            "messages": messages,
            "temperature": 0.5
        }
        response = self.send_request_silent(data)
        if response is None:
            self.title = None
            return
        reply_message = response.json()["choices"][0]["message"]
        self.title: str = reply_message['content']
        # here: we don't need a lock here for self.title because: the only three places changes or uses chat_gpt.title will never operate together
        # they are: gen_title, gen_title_silent (here), '/save' command
        log.debug(f"Title background silent generated: {self.title}")

        messages.append(reply_message)
        self.add_total_tokens(count_token(messages))
        # count title generation tokens cost

        return self.title

    def auto_gen_title_background(self):
        # this is the auto title generation daemon thread main function
        # it SHOULD NOT be triggered or used by any other functions or commands
        while True:
            try:
                content_this_time = self.gen_title_messages.get()
                log.debug(f"Title Generation Daemon Thread: Working with message \"{content_this_time}\"")
                new_title = self.gen_title_silent(content_this_time)
                self.gen_title_messages.task_done()
                time.sleep(0.2)
                if not new_title:
                    log.error("Background Title auto-generation Failed")
                else:
                    change_CLI_title(self.title)
                log.debug("Title Generation Daemon Thread: Pause")

            except Exception as e:
                console.print(
                    f"[red]Background Title auto-generation Error: {str(e)}. Check log for more information")
                log.exception(e)
                self.save_chat_history_urgent()
                while self.gen_title_messages.unfinished_tasks:
                    self.gen_title_messages.task_done()
                continue
                # something went wrong, continue the loop

    def save_chat_history(self, filename):
        try:
            with open(f"{filename}", 'w', encoding='utf-8') as f:
                json.dump(self.messages, f, ensure_ascii=False, indent=4)
            console.print(
                f"[dim]Chat history saved to: [bright_magenta]{filename}", highlight=False)
        except Exception as e:
            console.print(
                f"[red]Error: {str(e)}. Check log for more information")
            log.exception(e)
            self.save_chat_history_urgent()
            return

    def save_chat_history_urgent(self):
        filename = f'{data_dir}/chat_history_backup_{datetime.now().strftime("%Y-%m-%d_%H,%M,%S")}.json'
        with open(f"{filename}", 'w', encoding='utf-8') as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=4)
        console.print(
            f"[dim]Chat history urgently saved to: [bright_magenta]{filename}", highlight=False)

    def send_get(self, url, params=None):
        try:
            response = requests.get(
                url, headers=self.headers, timeout=self.timeout, params=params)
        # 匹配4xx错误，显示服务器返回的具体原因
            if response.status_code // 100 == 4:
                error_msg = response.json()['error']['message']
                console.print(f"[red]Get {url} Error: {error_msg}")
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

    def fetch_credit_total_granted(self):
        url_subscription = "https://api.openai.com/dashboard/billing/subscription"
        response_subscription = self.send_get(url_subscription)
        if not response_subscription:
            self.credit_total_granted = None
        response_subscription_json = response_subscription.json()
        self.credit_total_granted = response_subscription_json["hard_limit_usd"]
        self.credit_plan = response_subscription_json["plan"]["title"]

    def fetch_credit_monthly_used(self, url_usage):
        usage_get_params_monthly = {
            "start_date": str(date.today().replace(day=1)),
            "end_date": str(date.today() + timedelta(days=1))}
        response_monthly_usage = self.send_get(
            url_usage, params=usage_get_params_monthly)
        if not response_monthly_usage:
            self.credit_used_this_month = None
        self.credit_used_this_month = response_monthly_usage.json()[
            "total_usage"] / 100

    def get_credit_usage(self):
        url_usage = "https://api.openai.com/dashboard/billing/usage"
        try:
            # get response from /dashborad/billing/subscription for total granted credit
            fetch_credit_total_granted_thread = threading.Thread(
                target=self.fetch_credit_total_granted)
            fetch_credit_total_granted_thread.start()

            # get usage this month
            fetch_credit_monthly_used_thread = threading.Thread(
                target=self.fetch_credit_monthly_used, args=(url_usage,))
            fetch_credit_monthly_used_thread.start()

            # start with 2023-01-01, get 99 days' data per turn
            usage_get_start_date = date(2023, 1, 1)
            usage_get_end_date = usage_get_start_date + timedelta(days=99)
            # 创建线程池，设置最大线程数为5
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                # 提交任务到线程池列表
                futures = []
                while usage_get_start_date < date.today():
                    usage_get_params = {
                        "start_date": str(usage_get_start_date),
                        "end_date": str(usage_get_end_date)}
                    futures.append(executor.submit(
                        self.send_get, url_usage, usage_get_params))
                    usage_get_start_date = usage_get_end_date
                    usage_get_end_date = usage_get_start_date + timedelta(days=99)

            fetch_credit_total_granted_thread.join()
            fetch_credit_monthly_used_thread.join()

            credit_total_used_cent = 0
            # 获取所有线程池任务的返回值
            for future in futures:
                result = future.result()
                if result:
                    credit_total_used_cent += result.json()["total_usage"]
            # get all usage info from 2023-01-01 to now
            self.credit_total_used = credit_total_used_cent / 100

        except KeyboardInterrupt:
            console.print("[bold cyan]Aborted.")
            raise
        except Exception as e:
            console.print(
                f"[red]Error: {str(e)}. Check log for more information")
            log.exception(e)
            self.save_chat_history_urgent()
            raise EOFError
        return True

    def modify_system_prompt(self, new_content: str):
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
        '/raw', '/multi', '/stream', '/tokens', '/usage', '/last', '/copy', '/model', '/save', '/system', '/title', '/timeout', '/undo', '/delete', '/version', '/help', '/exit'
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


def count_token(messages: List[Dict[str, str]]):
    '''计算 messages 占用的 token
    `cl100k_base` 编码适用于: gpt-4, gpt-3.5-turbo, text-embedding-ada-002'''
    encoding = tiktoken.get_encoding("cl100k_base")
    length = 0
    for message in messages:
        length += len(encoding.encode(str(message)))
    return length


class NumberValidator(Validator):
    def validate(self, document):
        text = document.text
        if not text.isdigit():
            raise ValidationError(message="Please input an Integer!",
                                  cursor_position=len(text))


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


def handle_command(command: str, chat_gpt: ChatGPT, key_bindings: KeyBindings, chat_save_perfix: str):
    '''处理斜杠(/)命令'''
    if command == '/raw':
        ChatMode.toggle_raw_mode()
    elif command == '/multi':
        ChatMode.toggle_multi_line_mode()
    elif command == '/stream':
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
                            title="Credit Summary", title_align='left', subtitle=f"[blue]Plan: {chat_gpt.credit_plan}", width=35))

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
            chat_gpt.current_tokens = count_token(chat_gpt.messages)
        else:
            console.print("[dim]Nothing to undo.")

    elif command.startswith('/delete'):
        args = command.split()
        if len(args) > 1:
            if args[1] == 'first':
                chat_gpt.delete_first_conversation()
            elif args[1] == 'all':
                del chat_gpt.messages[1:]
                chat_gpt.title = None
                chat_gpt.current_tokens = count_token(chat_gpt.messages)
                # recount current tokens
                console.print("[dim]Current chat deleted.")
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

    else:
        console.print('''[bold]Available commands:[/]
    /raw                     - Toggle raw mode (showing raw text of ChatGPT's reply)
    /multi                   - Toggle multi-line mode (allow multi-line input)
    /stream                  - Toggle stream output mode (flow print the answer)
    /tokens                  - Show the total tokens spent and the tokens for the current conversation
    /usage                   - Show total credits and current credits used
    /last                    - Display last ChatGPT's reply
    /copy (all)              - Copy the full ChatGPT's last reply (raw) to Clipboard
    /copy code \[index]       - Copy the code in ChatGPT's last reply to Clipboard
    /save \[filename_or_path] - Save the chat history to a file, suggest title if filename_or_path not provided
    /model \[model_name]      - Change AI model
    /system \[new_prompt]     - Modify the system prompt
    /title \[new_title]       - Set title for this chat, if new_title is not provided, a new title will be generated
    /timeout \[new_timeout]   - Modify the api timeout
    /undo                    - Undo the last question and remove its answer
    /delete (first)          - Delete the first conversation in current chat
    /delete all              - Clear all messages and conversations current chat
    /version                 - Show gpt-term local and remote version
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

    check_remote_update_thread = threading.Thread(target=get_remote_version)
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

    chat_gpt = ChatGPT(api_key, api_timeout)

    if not config.getboolean("AUTO_GENERATE_TITLE", True):
        chat_gpt.auto_gen_title_background_enable = False
        log.debug("Auto title generation disabled")

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
            chat_gpt.current_tokens = count_token(chat_gpt.messages)
            log.info(f"Chat history successfully loaded from: {args.load}")
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

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
import tiktoken
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

from . import __version__
from .locale import set_lang, get_lang
import locale

data_dir = Path.home() / '.gpt-term'
data_dir.mkdir(parents=True, exist_ok=True)
config_path = data_dir / 'config.ini'
if not config_path.exists():
    with config_path.open('w') as f:
        f.write(read_text('gpt_term', 'config.ini'))

# 日志记录到 chat.log，注释下面这行可不记录日志
logging.basicConfig(filename=f'{data_dir}/chat.log', format='%(asctime)s %(name)s: %(levelname)-6s %(message)s',
                    datefmt='[%Y-%m-%d %H:%M:%S]', level=logging.INFO)

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
        if cls.raw_mode:
            console.print(_("gpt_term.raw_mode_enabled"))
        else:
            console.print(_("gpt_term.raw_mode_disabled"))

    @classmethod
    def toggle_stream_mode(cls):
        cls.stream_mode = not cls.stream_mode
        if cls.stream_mode:
            console.print(
                _("gpt_term.stream_mode_enabled"))
        else:
            console.print(
                _("gpt_term.stream_mode_disabled"))

    @classmethod
    def toggle_multi_line_mode(cls):
        cls.multi_line_mode = not cls.multi_line_mode
        if cls.multi_line_mode:
            console.print(
                _("gpt_term.multi_line_enabled"))
        else:
            console.print(_("gpt_term.multi_line_disabled"))


class ChatGPT:
    def __init__(self, api_key: str, timeout: float):
        self.api_key = api_key
        self.host = "https://api.openai.com"
        self.endpoint = self.host + "/v1/chat/completions"
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
        self.temperature = 1
        self.total_tokens_spent = 0
        self.current_tokens = count_token(self.messages)
        self.timeout = timeout
        self.title: str = None
        self.gen_title_messages = Queue()
        self.auto_gen_title_background_enable = True
        self.threadlock_total_tokens_spent = threading.Lock()
        self.stream_overflow = 'ellipsis'

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
            with console.status(_("gpt_term.ChatGPT_thinking")):
                response = requests.post(
                    self.endpoint, headers=self.headers, data=json.dumps(data), timeout=self.timeout, stream=ChatMode.stream_mode)
            # 匹配4xx错误，显示服务器返回的具体原因
            if response.status_code // 100 == 4:
                error_msg = response.json()['error']['message']
                console.print(_("gpt_term.Error_message",error_msg=error_msg))
                log.error(error_msg)
                return None

            response.raise_for_status()
            return response
        except KeyboardInterrupt:
            console.print(_("gpt_term.Aborted"))
            raise
        except requests.exceptions.ReadTimeout as e:
            console.print(
                _("gpt_term.Error_timeout",timeout=self.timeout), highlight=False)
            return None
        except requests.exceptions.RequestException as e:
            console.print(_("gpt_term.Error_message",error_msg=str(e)))
            log.exception(e)
            return None

    def send_request_silent(self, data):
        # this is a silent sub function, for sending request without outputs (silently)
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
        with Live(console=console, auto_refresh=False, vertical_overflow=self.stream_overflow) as live:
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
                console.print(_('gpt_term.Aborted'))
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
                _('gpt_term.delete_first_conversation_yes',truncated_question=truncated_question,tokens_saved=tokens_saved))
        else:
            console.print(_('gpt_term.delete_first_conversation_no'))
    
    def delete_all_conversation(self):
        del self.messages[1:]
        self.title = None
        # recount current tokens
        self.current_tokens = count_token(self.messages)
        os.system('cls' if os.name == 'nt' else 'clear')
        console.print(_('gpt_term.delete_all'))

    def handle_simple(self, message: str):
        self.messages.append({"role": "user", "content": message})
        data = {
            "model": self.model,
            "messages": self.messages,
            "temperature": self.temperature
        }
        response = self.send_request_silent(data)
        if response:
            response_json = response.json()
            log.debug(f"Response: {response_json}")
            print(response_json["choices"][0]["message"]["content"])

    def handle(self, message: str):
        try:
            self.messages.append({"role": "user", "content": message})
            data = {
                "model": self.model,
                "messages": self.messages,
                "stream": ChatMode.stream_mode,
                "temperature": self.temperature
            }
            response = self.send_request(data)
            if response is None:
                self.messages.pop()
                if self.current_tokens >= self.tokens_limit:
                    console.print(_('gpt_term.tokens_reached'))
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
                        _("gpt_term.tokens_approaching",token_left=self.tokens_limit - self.current_tokens))
                # approaching tokens limit (less than 500 left), show info

        except Exception as e:
            console.print(
                _("chat_term.Error_look_log",error_msg=str(e)))
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
            with console.status(_("gpt_term.title_waiting_gen")):
                self.gen_title_messages.join()
            if self.title and not force:
                return self.title

            # title not generated, do

            content_this_time = self.messages[1]['content']
            self.gen_title_messages.put(content_this_time)
            with console.status(_("gpt_term.title_gening")):
                self.gen_title_messages.join()
        except KeyboardInterrupt:
            console.print(_("gpt_term.title_skip_gen"))
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
                console.print(_("gpt_term.title_auto_gen_fail",error_msg=str(e))
                    )
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
                _("gpt_term.save_history_success",filename=filename), highlight=False)
        except Exception as e:
            console.print(
                _("gpt_term.Error_look_log"))
            log.exception(e)
            self.save_chat_history_urgent()
            return

    def save_chat_history_urgent(self):
        filename = f'{data_dir}/chat_history_backup_{datetime.now().strftime("%Y-%m-%d_%H,%M,%S")}.json'
        with open(f"{filename}", 'w', encoding='utf-8') as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=4)
        console.print(
            _("gpt_term.save_history_urgent_success",filename=filename), highlight=False)

    def send_get(self, url, params=None):
        try:
            response = requests.get(
                url, headers=self.headers, timeout=self.timeout, params=params)
        # 匹配4xx错误，显示服务器返回的具体原因
            if response.status_code // 100 == 4:
                error_msg = response.json()['error']['message']
                console.print(_("gpt_term.Error_get_url",url=url,error_msg=error_msg))
                log.error(error_msg)
                return None
            response.raise_for_status()
            return response
        except KeyboardInterrupt:
            console.print(_("gpt_term.Aborted"))
            raise
        except requests.exceptions.ReadTimeout as e:
            console.print(
                _("gpt_term.Error_timeot",timeout=self.timeout), highlight=False)
            return None
        except requests.exceptions.RequestException as e:
            console.print(_("gpt_term.Error_message",error_msg=str(e)))
            log.exception(e)
            return None

    def fetch_credit_total_granted(self):
        url_subscription = self.host + "/dashboard/billing/subscription"
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
        url_usage = self.host + "/dashboard/billing/usage"
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
            console.print(_("gpt_term.Aborted"))
            raise
        except Exception as e:
            console.print(
                _("gpt_term.Error_message",error_msg=str(e)))
            log.exception(e)
            self.save_chat_history_urgent()
            raise EOFError
        return True
    
    def set_host(self, host: str):
        self.host = host
        self.endpoint = self.host + "/v1/chat/completions"

    def modify_system_prompt(self, new_content: str):
        if self.messages[0]['role'] == 'system':
            old_content = self.messages[0]['content']
            self.messages[0]['content'] = new_content
            console.print(
                _("gpt_term.system_prompt_modified",old_content=old_content,new_content=new_content))
            self.current_tokens = count_token(self.messages)
            # recount current tokens
            if len(self.messages) > 1:
                console.print(
                    _("gpt_term.system_prompt_note"))
        else:
            console.print(
                _("gpt_term.system_prompt_found"))

    def set_stream_overflow(self, new_overflow: str):
        # turn on stream if not
        if not ChatMode.stream_mode:
            ChatMode.toggle_stream_mode()

        if new_overflow == self.stream_overflow:
            console.print(_("gpt_term.No_change"))
            return

        old_overflow = self.stream_overflow
        if new_overflow == 'ellipsis' or new_overflow == 'visible':
            self.stream_overflow = new_overflow
            console.print(
                _("gpt_term.stream_overflow_modified",old_overflow=old_overflow,new_overflow=new_overflow))
            if new_overflow == 'visible':
                console.print(_("gpt_term.stream_overflow_visible"))
        else:
            console.print(_("gpt_term.stream_overflow_no_changed",old_overflow=old_overflow))
        

    def set_model(self, new_model: str):
        old_model = self.model
        if not new_model:
            console.print(
                _("gpt_term.model_set"),old_model=old_model)
            return
        self.model = str(new_model)
        if "gpt-4-32k" in self.model:
            self.tokens_limit = 32768
        elif "gpt-4" in self.model:
            self.tokens_limit = 8192
        elif "gpt-3.5-turbo-16k" in self.model:
            self.tokens_limit = 16384
        elif "gpt-3.5-turbo" in self.model:
            self.tokens_limit = 4096
        else:
            self.tokens_limit = float('nan')
        console.print(
            _("gpt_term.model_changed",old_model=old_model,new_model=new_model))

    def set_timeout(self, timeout):
        try:
            self.timeout = float(timeout)
        except ValueError:
            console.print(_("gpt_term.Error_input_number"))
            return
        console.print(_("gpt_term.timeput_changed",timeout=timeout))

    def set_temperature(self, temperature):
        try:
            new_temperature = float(temperature)
        except ValueError:
            console.print(_("gpt_term.temperature_must_between"))
            return
        if new_temperature > 2 or new_temperature < 0:
            console.print(_("gpt_term.temperature_must_between"))
            return
        self.temperature = new_temperature
        console.print(_("gpt_term.temperature_set",temperature=temperature))


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
                "gpt-4", 
                "gpt-4-0613", 
                "gpt-4-32k", 
                "gpt-4-32k-0613", 
                "gpt-3.5-turbo", 
                "gpt-3.5-turbo-0613", 
                "gpt-3.5-turbo-16k", 
                "gpt-3.5-turbo-16k-0613"},
            '/save': PathCompleter(file_filter=self.path_filter),
            '/system': None,
            '/rand': None,
            '/temperature': None,
            '/title': None,
            '/timeout': None,
            '/undo': None,
            '/delete': {"first", "all"},
            '/reset': None,
            '/lang' : {"zh_CN", "en", "jp", "de"},
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
            raise ValidationError(message=_("gpt_term.Error_input_int"),
                                  cursor_position=len(text))

class FloatRangeValidator(Validator):
    def __init__(self, min_value=None, max_value=None):
        self.min_value = min_value
        self.max_value = max_value

    def validate(self, document):
        try:
            value = float(document.text)
        except ValueError:
            raise ValidationError(message=_('gpt_term.Error_input_number'))

        if self.min_value is not None and value < self.min_value:
            raise ValidationError(message=_("gpt_term.Error_input_least",min_value=self.min_value))
        if self.max_value is not None and value > self.max_value:
            raise ValidationError(message=_("gpt_term.Error_input_most",max_value=self.max_value))
        
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
        console.print(_("gpt_term.code_not_found"))
        return

    if len(code_list) == 1 and select_code_idx is None:
        selected_code = code_list[0]
        # if there's only one code, and select_code_idx not given, just copy it
    else:
        if select_code_idx is None:
            console.print(
                _("gpt_term.code_too_many_found"))
            code_num = 0
            for codes in code_list:
                code_num += 1
                console.print(_("gpt_term.code_num",code_num=code_num))
                console.print(Markdown(codes))

            select_code_idx = prompt(
                _("gpt_term.code_select"), style=style, validator=NumberValidator())
            # get the number of the selected code
        try:
            selected_code = code_list[int(select_code_idx)-1]
        except ValueError:
            console.print(_("gpt_term.code_index_must_int"))
            return
        except IndexError:
            if len(code_list) == 1:
                console.print(
                    _("gpt_term.code_index_out_range_one"))
            else:
                console.print(
                    _("gpt_term.code_index_out_range_many",len(code_list)))
                # show idx range
                # use len(code_list) instead of code_num as the max of idx
                # in order to avoid error 'UnboundLocalError: local variable 'code_num' referenced before assignment' when inputing select_code_idx directly
            return

    bpos = selected_code.find('\n')    # code begin pos.
    epos = selected_code.rfind('```')  # code end pos.
    pyperclip.copy(''.join(selected_code[bpos+1:epos-1]))
    # erase code begin and end sign
    console.print(_("gpt_term.code_copy"))


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


def handle_command(command: str, chat_gpt: ChatGPT, key_bindings: KeyBindings, chat_save_perfix: str):
    '''处理斜杠(/)命令'''
    global _
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
        console.print(Panel(_("gpt_term.tokens_used",total_tokens_spent=chat_gpt.total_tokens_spent,current_tokens=chat_gpt.current_tokens,tokens_limit=chat_gpt.tokens_limit),
                            title=_("gpt_term.tokens_title"), title_align='left', width=40))
        chat_gpt.threadlock_total_tokens_spent.release()

    elif command == '/usage':
        with console.status(_("gpt_term.usage_getting")):
            if not chat_gpt.get_credit_usage():
                return
        console.print(Panel(f'{_("gpt_term.usage_granted",credit_total_granted=format(chat_gpt.credit_total_granted, ".2f"))}\n'
                            f'{_("gpt_term.usage_used_month",credit_used_this_month=format(chat_gpt.credit_used_this_month, ".2f"))}\n'
                            f'{_("gpt_term.usage_total",credit_total_used=format(chat_gpt.credit_total_used, ".2f"))}',
                            title=_("gpt_term.usage_title"), title_align='left', subtitle=_("gpt_term.usage_plan",credit_plan=chat_gpt.credit_plan), width=35))

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
            console.print(_("gpt_term.No_change"))

    elif command == '/last':
        reply = chat_gpt.messages[-1]
        print_message(reply)

    elif command.startswith('/copy'):
        args = command.split()
        reply = chat_gpt.messages[-1]
        if len(args) > 1:
            if args[1] == 'all':
                pyperclip.copy(reply["content"])
                console.print(_("gpt_term.code_last_copy"))
            elif args[1] == 'code':
                if len(args) > 2:
                    copy_code(reply, args[2])
                else:
                    copy_code(reply)
            else:
                console.print(
                    _("gpt_term.code_copy_fail"))
        else:
            pyperclip.copy(reply["content"])
            console.print(_("gpt_term.code_last_copy"))

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
                _("gpt_term.system_prompt"), default=chat_gpt.messages[0]['content'], style=style, key_bindings=key_bindings)
        if new_content != chat_gpt.messages[0]['content']:
            chat_gpt.modify_system_prompt(new_content)
        else:
            console.print(_("gpt_term.No_change"))

    elif command.startswith('/rand') or command.startswith('/temperature'):
        args = command.split()
        if len(args) > 1:
            new_temperature = args[1]
        else:
            new_temperature = prompt(
                _("gpt_term.new_temperature"), default=str(chat_gpt.temperature), style=style, validator=temperature_validator)
        if new_temperature != str(chat_gpt.temperature):
            chat_gpt.set_temperature(new_temperature)
        else:
            console.print(_("gpt_term.No_change"))            

    elif command.startswith('/title'):
        args = command.split()
        if len(args) > 1:
            chat_gpt.title = ' '.join(args[1:])
            change_CLI_title(chat_gpt.title)
        else:
            # generate a new title
            new_title = chat_gpt.gen_title(force=True)
            if not new_title:
                console.print(_("gpt_term.title_gen_fail"))
                return
        console.print(_('gpt_term.title_changed',title=chat_gpt.title))

    elif command.startswith('/timeout'):
        args = command.split()
        if len(args) > 1:
            new_timeout = args[1]
        else:
            new_timeout = prompt(
                _("gpt_term.timeout_prompt"), default=str(chat_gpt.timeout), style=style)
        if new_timeout != str(chat_gpt.timeout):
            chat_gpt.set_timeout(new_timeout)
        else:
            console.print(_("gpt_term.No_change"))

    elif command == '/undo':
        if len(chat_gpt.messages) > 2:
            question = chat_gpt.messages.pop()
            if question['role'] == "assistant":
                question = chat_gpt.messages.pop()
            truncated_question = question['content'].split('\n')[0]
            if len(question['content']) > len(truncated_question):
                truncated_question += "..."
            console.print(
                _("gpt_term.undo_removed",truncated_question=truncated_question))
            chat_gpt.current_tokens = count_token(chat_gpt.messages)
        else:
            console.print(_("gpt_term.undo_nothing"))

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
                    _("gpt_term.delete_nothing"))
        else:
            chat_gpt.delete_first_conversation()

    elif command == '/version':
        threadlock_remote_version.acquire()
        string=_("gpt_term.version_all",local_version=str(local_version),remote_version=str(remote_version))
        console.print(Panel(string,
                            title=_("gpt_term.version_name"), title_align='left', width=28))
        threadlock_remote_version.release()
    
    elif command.startswith('/lang'):
        args = command.split()
        if len(args) > 1:
            new_lang = args[1]
        else:
            new_lang = prompt(
                _("gpt_term.new_lang_prompt"), default=get_lang(), style=style)
        if new_lang != get_lang():
            if new_lang in supported_langs:
                _=set_lang(new_lang)
                console.print(_("gpt_term.lang_switch"))
            else:
                console.print(_("gpt_term.lang_unsupport", new_lang=new_lang))
        else:
            console.print(_("gpt_term.No_change"))

    elif command == '/exit':
        raise EOFError

    elif command == '/help':
        console.print(_("gpt_term.help_text"))
        
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
        
        console.print(_("gpt_term.help_uncommand",command=command), end=" ")
        if most_similar_command:
            console.print(_("gpt_term.help_mean_command",most_similar_command=most_similar_command))
        else:
            console.print("")
        console.print(_("gpt_term.help_use_help"))


def load_chat_history(file_path):
    '''从 file_path 加载聊天记录'''
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            chat_history = json.load(f)
        return chat_history
    except FileNotFoundError:
        console.print(_("gpt_term.load_file_not",file_path=file_path))
    except json.JSONDecodeError:
        console.print(_("gpt_term.load_json_error",file_path=file_path))
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
    global _
    config_need_to_set = {}
    if args.set_host:       config_need_to_set.update({"OPENAI_HOST"         : args.set_host})
    if args.set_apikey:     config_need_to_set.update({"OPENAI_API_KEY"      : args.set_apikey})
    if args.set_timeout:    config_need_to_set.update({"OPENAI_API_TIMEOUT"  : args.set_timeout})
    if args.set_saveperfix: config_need_to_set.update({"CHAT_SAVE_PERFIX"    : args.set_saveperfix})
    if args.set_loglevel:   config_need_to_set.update({"LOG_LEVEL"           : args.set_loglevel})
    if args.set_gentitle:   config_need_to_set.update({"AUTO_GENERATE_TITLE" : args.set_gentitle})
    # 新的语言设置:
    if args.set_lang:       
        config_need_to_set.update({"LANGUAGE": args.set_lang})
        _=set_lang(args.set_lang)
    # here: when set lang is called, set language before printing 'set-successful' messages

    if len(config_need_to_set) == 0:
        return
    # nothing to set
    for key, val in config_need_to_set.items():
        config_ini['DEFAULT'][key] = str(val)
        console.print(_("gpt_term.config_key_to_shell_key",key_word=str(key),val=str(val)))

    write_config(config_ini)
    exit(0)


def main():
    global _, supported_langs
    supported_langs = ["en","zh_CN","jp","de"]
    local_lang = locale.getdefaultlocale()[0]
    if local_lang not in supported_langs:
        local_lang = "en"
    _=set_lang(local_lang)

    # 读取配置文件
    config_ini = ConfigParser()
    config_ini.read(f'{data_dir}/config.ini', encoding='utf-8')
    config = config_ini['DEFAULT']

    # 读取语言配置
    config_lang = config.get("language")
    if config_lang:
        if config_lang in supported_langs:
            _=set_lang(config_lang)
        else:
            console.print(_("gpt_term.lang_config_unsupport", config_lang=config_lang))
        # if lang set in config is not support, print infos and use default local_lang

    parser = argparse.ArgumentParser(description=_("gpt_term.help_description"),add_help=False)
    parser.add_argument('-h', '--help',action='help', help=_("gpt_term.help_help"))
    parser.add_argument('-v','--version', action='version', version=f'%(prog)s v{local_version}',help=_("gpt_term.help_v"))
    parser.add_argument('--load', metavar='FILE', type=str, help=_("gpt_term.help_load"))
    parser.add_argument('--key', type=str, help=_("gpt_term.help_key"))
    parser.add_argument('--model', type=str, help=_("gpt_term.help_model"))
    parser.add_argument('--host', metavar='HOST', type=str, help=_("gpt_term.help_host"))
    parser.add_argument('-m', '--multi', action='store_true', help=_("gpt_term.help_m"))
    parser.add_argument('-r', '--raw', action='store_true', help=_("gpt_term.help_r"))
    ## 新添加的选项：--lang
    parser.add_argument('-l','--lang', type=str, choices=['en', 'zh_CN', 'jp', 'de'], help=_("gpt_term.help_lang"))
    # normal function args

    parser.add_argument('--set-host', metavar='HOST', type=str, help=_("gpt_term.help_set_host"))
    parser.add_argument('--set-apikey', metavar='KEY', type=str, help=_("gpt_term.help_set_key"))
    parser.add_argument('--set-timeout', metavar='SEC', type=int, help=_("gpt_term.help_set_timeout"))
    parser.add_argument('--set-gentitle', metavar='BOOL', type=str, help=_("gpt_term.help_set_gentitle"))
    ## 新添加的选项：--set-lang
    parser.add_argument('--set-lang', type=str, choices=['en', 'zh_CN', 'jp', 'de'], help=_("gpt_term.help_set_lang"))
    parser.add_argument('--set-saveperfix', metavar='PERFIX', type=str, help=_("gpt_term.help_set_saveperfix"))
    parser.add_argument('--set-loglevel', metavar='LEVEL', type=str, help=_("gpt_term.help_set_loglevel")+'DEBUG, INFO, WARNING, ERROR, CRITICAL')
    # Query without parameter
    parser.add_argument("query", nargs="*", help=_("gpt_term.help_direct_query"))
    # setting args
    args = parser.parse_args()

    set_config_by_args(args, config_ini)

    if args.lang:
        _=set_lang(args.lang)
        console.print(_("gpt_term.lang_switch"))

    try:
        log_level = getattr(logging, config.get("LOG_LEVEL", "INFO").upper())
    except AttributeError as e:
        console.print(
            _("gpt_term.log_level_error"))
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
        api_key = prompt(_("gpt_term.input_api_key"))
        if confirm(_("gpt_term.save_api_key"), suffix=" (y/N) "):
            config["OPENAI_API_KEY"] = api_key
            write_config(config_ini)

    api_key_log = api_key[:3] + '*' * (len(api_key) - 7) + api_key[-4:]
    log.debug(f"Loaded API Key: {api_key_log}")

    api_timeout = config.getfloat("OPENAI_API_TIMEOUT", 30)
    log.debug(f"API Timeout set to {api_timeout}")

    chat_save_perfix = config.get("CHAT_SAVE_PERFIX", "./chat_history_")

    chat_gpt = ChatGPT(api_key, api_timeout)
    
    if config.get("OPENAI_HOST"):
        chat_gpt.set_host(config.get("OPENAI_HOST"))

    if not config.getboolean("AUTO_GENERATE_TITLE", True):
        chat_gpt.auto_gen_title_background_enable = False
        log.debug("Auto title generation [bright_red]disabled[/]")

    gen_title_daemon_thread = threading.Thread(
        target=chat_gpt.auto_gen_title_background, daemon=True)
    gen_title_daemon_thread.start()
    log.debug("Title generation daemon thread started")

    if args.host:
        chat_gpt.set_host(args.host)
        console.print(_("gpt_term.host_set", new_host=args.host))

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
                _("gpt_term.load_chat_history",load=args.load), highlight=False)
            
    if args.query:
        query_text = " ".join(args.query)
        log.info(f"> {query_text}")
        is_stdout_tty = os.isatty(sys.stdout.fileno())
        if is_stdout_tty:
            chat_gpt.handle(query_text)
        else:  # Running in pipe/stream mode
            chat_gpt.handle_simple(query_text)
        return
    else:
        console.print(_("gpt_term.welcome"))

    session = PromptSession()

    # 绑定回车事件，达到自定义多行模式的效果
    key_bindings = create_key_bindings()

    while True:
        try:
            message = session.prompt(
                '> ', completer=command_completer, complete_while_typing=True, key_bindings=key_bindings)

            if message.startswith('/'):
                command = message.strip()
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
            console.print(_("gpt_term.exit"))
            break

    log.info(f"Total tokens spent: {chat_gpt.total_tokens_spent}")
    console.print(
        _("gpt_term.spent_token",total_tokens_spent=chat_gpt.total_tokens_spent))
    
    threadlock_remote_version.acquire()
    if remote_version and remote_version > local_version:
        console.print(Panel(Group(
            Markdown(_("gpt_term.upgrade_use_command")),
            Markdown(_("gpt_term.upgrade_see_git"))),
            title=_("gpt_term.upgrade_title",local_version=str(local_version),remote_version=str(remote_version)),
            width=58, style="blue", title_align="left"))
    threadlock_remote_version.release()

if __name__ == "__main__":
    main()

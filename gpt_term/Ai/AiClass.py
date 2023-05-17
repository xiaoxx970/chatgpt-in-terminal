from typing import Dict, List
from rich.markdown import Markdown
from queue import Queue
from rich.console import Console, Group
from datetime import date, datetime, timedelta
from rich.live import Live
from rich import print as rprint
from rich.markdown import Markdown
from typing import Dict, List
from prompt_toolkit.shortcuts import confirm

import sseclient
import os
import time
import requests
import threading
import json
import concurrent
import platform
import sys

class Ai():
    def __init__(self,api_key,console,log,data_dir,Use_tiktoken = 1,) -> None:
        self.api_key = api_key
        self.console = console
        self.Use_tiktoken = Use_tiktoken
        self.log=log
        self.data_dir = data_dir
    def count_token(self,messages: List[Dict[str, str]]):
        '''计算 messages 占用的 token
        `cl100k_base` 编码适用于: gpt-4, gpt-3.5-turbo, text-embedding-ada-002'''
        if self.Use_tiktoken:
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            length = 0
            for message in messages:
                length += len(encoding.encode(str(message)))
            return length
        else:
            return 0
    def print_message(self,message: Dict[str, str]):
        '''打印单条来自 ChatGPT 或用户的消息'''
        role = message["role"]
        content = message["content"]
        if role == "user":
            print(f"> {content}")
        elif role == "assistant":
            self.console.print("ChatGPT: ", end='', style="bold cyan")
            if ChatMode.raw_mode:
                print(content)
            else:
                self.console.print(Markdown(content), new_line_start=True)
    def add_total_tokens(self, tokens: int):
        self.threadlock_total_tokens_spent.acquire()
        self.total_tokens_spent += tokens
        self.threadlock_total_tokens_spent.release()

    def send_request(self, data):
        if self.key_mode == "openai":
            try:
                with self.console.status(f"[bold cyan]ChatGPT is thinking..."):
                    response = requests.post(
                        self.endpoint, headers=self.headers, data=json.dumps(data), timeout=self.timeout, stream=ChatMode.stream_mode)
                # 匹配4xx错误，显示服务器返回的具体原因
                if response.status_code // 100 == 4:
                    error_msg = response.json()['error']['message']
                    self.console.print(f"[red]Error: {error_msg}")
                    self.log.error(error_msg)
                    return None

                response.raise_for_status()
                return response
            except KeyboardInterrupt:
                self.console.print("[bold cyan]Aborted.")
                raise
            except requests.exceptions.ReadTimeout as e:
                self.console.print(
                    f"[red]Error: API read timed out ({self.timeout}s). You can retry or increase the timeout.", highlight=False)
                return None
            except requests.exceptions.RequestException as e:
                self.console.print(f"[red]Error: {str(e)}")
                self.log.exception(e)
                return None
        else:
            for chunk in self.client.send_message("capybara", data, with_chat_break=True):
                pass
            return chunk['text']
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
                self.log.error(error_msg)
                return None

            response.raise_for_status()
            return response
        except requests.exceptions.ReadTimeout as e:
            self.log.error("Automatic generating title failed as timeout")
            return None
        except requests.exceptions.RequestException as e:
            self.log.exception(e)
            return None

    def process_stream_response(self, response: requests.Response):
        reply: str = ""
        client = sseclient.SSEClient(response)
        with Live(console=self.console, auto_refresh=False, vertical_overflow=self.stream_overflow) as live:
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
                self.console.print("Aborted.", style="bold cyan")
            finally:
                return {'role': 'assistant', 'content': reply}

    def process_response(self, response: requests.Response):
        if ChatMode.stream_mode:
            return self.process_stream_response(response)
        else:
            response_json = response.json()
            self.log.debug(f"Response: {response_json}")
            reply_message: Dict[str, str] = response_json["choices"][0]["message"]
            self.print_message(reply_message)
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
            new_tokens = self.count_token(self.messages)
            tokens_saved = self.current_tokens - new_tokens
            self.current_tokens = new_tokens

            self.console.print(
                f"[dim]First question: '{truncated_question}' and it's answer has been deleted, saved tokens: {tokens_saved}")
        else:
            self.console.print("[red]No conversations yet.")
    
    def delete_all_conversation(self):
        del self.messages[1:]
        self.title = None
        # recount current tokens
        self.current_tokens = self.count_token(self.messages)
        os.system('cls' if os.name == 'nt' else 'clear')
        self.console.print("[dim]Current chat cleared.")

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
                    if confirm("Reached tokens limit, do you want me to for the earliest message of current chat?"):
                        self.delete_first_conversation()
                return

            if self.key_mode == "openai":
                reply_message = self.process_response(response)
            elif self.key_mode == "poe":
                reply_message = response
            if reply_message is not None:
                if self.key_mode == "openai":
                    self.log.info(f"ChatGPT: {reply_message['content']}")
                    self.messages.append(reply_message)
                    self.current_tokens = self.count_token(self.messages)
                    self.add_total_tokens(self.current_tokens)

                    if len(self.messages) == 3 and self.auto_gen_title_background_enable:
                        self.gen_title_messages.put(self.messages[1]['content'])

                    if self.tokens_limit - self.current_tokens in range(1, 500):
                        self.console.print(
                            f"[dim]Approaching the tokens limit: {self.tokens_limit - self.current_tokens} tokens left")
                    # approaching tokens limit (less than 500 left), show info
                elif self.key_mode == "poe":
                    self.log.info(f"ChatGPT: {reply_message}")
                    self.messages.append(reply_message)
                    if len(self.messages) == 3 and self.auto_gen_title_background_enable:
                        self.gen_title_messages.put(self.messages)


        except Exception as e:
            self.console.print(
                f"[red]Error: {str(e)}. Check log for more information")
            self.log.exception(e)
            self.save_chat_history_urgent()
            raise EOFError

        return reply_message

    def gen_title(self, force: bool = False):
        # Empty the title if there is only system message left
        if len(self.messages) < 2:
            self.title = None
            return

        try:
            with self.console.status("[bold cyan]Waiting last generationg to finish..."):
                self.gen_title_messages.join()
            if self.title and not force:
                return self.title

            # title not generated, do

            content_this_time = self.messages[1]['content']
            self.gen_title_messages.put(content_this_time)
            with self.console.status("[bold cyan]Generating title... [/](Ctrl-C to skip)"):
                self.gen_title_messages.join()
        except KeyboardInterrupt:
            self.console.print("Skip wait.", style="bold cyan")
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
        self.log.debug(f"Title background silent generated: {self.title}")

        messages.append(reply_message)
        self.add_total_tokens(self.count_token(messages))
        # count title generation tokens cost

        return self.title

    def auto_gen_title_background(self):
        # this is the auto title generation daemon thread main function
        # it SHOULD NOT be triggered or used by any other functions or commands
        while True:
            try:
                content_this_time = self.gen_title_messages.get()
                self.log.debug(f"Title Generation Daemon Thread: Working with message \"{content_this_time}\"")
                new_title = self.gen_title_silent(content_this_time)
                self.gen_title_messages.task_done()
                time.sleep(0.2)
                if not new_title:
                    self.log.error("Background Title auto-generation Failed")
                else:
                    self.change_CLI_title(self.title)
                self.log.debug("Title Generation Daemon Thread: Pause")

            except Exception as e:
                self.console.print(
                    f"[red]Background Title auto-generation Error: {str(e)}. Check log for more information")
                self.log.exception(e)
                self.save_chat_history_urgent()
                while self.gen_title_messages.unfinished_tasks:
                    self.gen_title_messages.task_done()
                continue
                # something went wrong, continue the loop
    def change_CLI_title(self,new_title: str):
        if platform.system() == "Windows":
            os.system(f"title {new_title}")
        else:
            print(f"\033]0;{new_title}\007", end='')
            sys.stdout.flush()
            # flush the stdout buffer in order to making the control sequences effective immediately
        self.log.debug(f"CLI Title changed to '{new_title}'")
    def save_chat_history(self, filename):
        try:
            with open(f"{filename}", 'w', encoding='utf-8') as f:
                json.dump(self.messages, f, ensure_ascii=False, indent=4)
            self.console.print(
                f"[dim]Chat history saved to: [bright_magenta]{filename}", highlight=False)
        except Exception as e:
            self.console.print(
                f"[red]Error: {str(e)}. Check log for more information")
            self.log.exception(e)
            self.save_chat_history_urgent()
            return

    def save_chat_history_urgent(self):
        filename = f'{self.data_dir}/chat_history_backup_{datetime.now().strftime("%Y-%m-%d_%H,%M,%S")}.json'
        with open(f"{filename}", 'w', encoding='utf-8') as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=4)
        self.console.print(
            f"[dim]Chat history urgently saved to: [bright_magenta]{filename}", highlight=False)

    def send_get(self, url, params=None):
        try:
            response = requests.get(
                url, headers=self.headers, timeout=self.timeout, params=params)
        # 匹配4xx错误，显示服务器返回的具体原因
            if response.status_code // 100 == 4:
                error_msg = response.json()['error']['message']
                self.console.print(f"[red]Get {url} Error: {error_msg}")
                self.log.error(error_msg)
                return None
            response.raise_for_status()
            return response
        except KeyboardInterrupt:
            self.console.print("[bold cyan]Aborted.")
            raise
        except requests.exceptions.ReadTimeout as e:
            self.console.print(
                f"[red]Error: API read timed out ({self.timeout}s). You can retry or increase the timeout.", highlight=False)
            return None
        except requests.exceptions.RequestException as e:
            self.console.print(f"[red]Error: {str(e)}")
            self.log.exception(e)
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
            self.console.print("[bold cyan]Aborted.")
            raise
        except Exception as e:
            self.console.print(
                f"[red]Error: {str(e)}. Check log for more information")
            self.log.exception(e)
            self.save_chat_history_urgent()
            raise EOFError
        return True

    def modify_system_prompt(self, new_content: str):
        if self.messages[0]['role'] == 'system':
            old_content = self.messages[0]['content']
            self.messages[0]['content'] = new_content
            self.console.print(
                f"[dim]System prompt has been modified from '{old_content}' to '{new_content}'.")
            self.current_tokens = self.count_token(self.messages)
            # recount current tokens
            if len(self.messages) > 1:
                self.console.print(
                    "[dim]Note this is not a new chat, modifications to the system prompt have limited impact on answers.")
        else:
            self.console.print(
                f"[dim]No system prompt found in messages.")

    def set_stream_overflow(self, new_overflow: str):
        # turn on stream if not
        if not ChatMode.stream_mode:
            ChatMode.toggle_stream_mode()

        if new_overflow == self.stream_overflow:
            self.console.print("[dim]No change.")
            return

        old_overflow = self.stream_overflow
        if new_overflow == 'ellipsis' or new_overflow == 'visible':
            self.stream_overflow = new_overflow
            self.console.print(
                f"[dim]Stream overflow option has been modified from '{old_overflow}' to '{new_overflow}'.")
            if new_overflow == 'visible':
                self.console.print("[dim]Note that in this mode the terminal will not properly clean up off-screen content.")
        else:
            self.console.print(f"[dim]No such Stream overflow option, remain '{old_overflow}' unchanged.")
        

    def set_model(self, new_model: str):
        old_model = self.model
        if not new_model:
            self.console.print(
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
            self.tokens_limit = float('nan')
        self.console.print(
            f"[dim]Model has been set from '{old_model}' to '{new_model}'.")

    def set_timeout(self, timeout):
        try:
            self.timeout = float(timeout)
        except ValueError:
            self.console.print("[red]Input must be a number")
            return
        self.console.print(f"[dim]API timeout set to [green]{timeout}s[/].")

    def set_temperature(self, temperature):
        try:
            new_temperature = float(temperature)
        except ValueError:
            self.console.print("[red]Input must be a number between 0 and 2")
            return
        if new_temperature > 2 or new_temperature < 0:
            self.console.print("[red]Input must be a number between 0 and 2")
            return
        self.temperature = new_temperature
        self.console.print(f"[dim]Randomness set to [green]{temperature}[/].")

class ChatMode():
    console = ''
    raw_mode = False
    multi_line_mode = False
    stream_mode = True
    @classmethod
    def init(cls,console):
        cls.console=console
    @classmethod
    def toggle_raw_mode(cls):
        cls.raw_mode = not cls.raw_mode
        cls.console.print(
            f"[dim]Raw mode {'[green]enabled[/]' if cls.raw_mode else '[bright_red]disabled[/]'}, use `[bright_magenta]/last[/]` to display the last answer.")

    @classmethod
    def toggle_stream_mode(cls):
        cls.stream_mode = not cls.stream_mode
        if cls.stream_mode:
            cls.console.print(
                f"[dim]Stream mode [green]enabled[/], the answer will start outputting as soon as the first response arrives.")
        else:
            cls.console.print(
                f"[dim]Stream mode [bright_red]disabled[/], the answer is being displayed after the server finishes responding.")

    @classmethod
    def toggle_multi_line_mode(cls):
        cls.multi_line_mode = not cls.multi_line_mode
        if cls.multi_line_mode:
            cls.console.print(
                f"[dim]Multi-line mode [green]enabled[/], press [[bright_magenta]Esc[/]] + [[bright_magenta]ENTER[/]] to submit.")
        else:
            cls.console.print(f"[dim]Multi-line mode [bright_red]disabled[/].")

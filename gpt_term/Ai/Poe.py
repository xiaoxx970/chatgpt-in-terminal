from .AiClass import Ai, ChatMode

from queue import Queue
import threading
from datetime import date, datetime, timedelta
from rich.live import Live
from rich.markdown import Markdown
from rich.progress import Progress
from rich import print as rprint
from typing import Dict
import json
import time


class poe_mode(Ai):
    def __init__(self, api_key, console, log, data_dir, timeout, Use_tiktoken=1) -> None:
        super().__init__(api_key, console, log, data_dir, Use_tiktoken)
        import poe

        self.client = poe.Client(api_key)
        self.clear_history_message = True  # 用于第一次会话的时候清除上下文
        self.key_mode = "poe"
        self.message = ''
        # 日志记录到 chat.log，注释下面这行可不记录日志,如果要注释Poe模式下的注释,请到Poe类定义处
        # 重定向log
        # logging.basicConfig(filename=f'{data_dir}/chat.log', format='%(asctime)s %(name)s: %(levelname)-6s %(message)s',
        #            datefmt='[%Y-%m-%d %H:%M:%S]', level=logging.INFO)

        poe.logger = log
        self.messages = [
            {"role": "system", "content": f"You are a helpful assistant.\nKnowledge cutoff: 2021-09\nCurrent date: {datetime.now().strftime('%Y-%m-%d')}"}]
        self.model = 'gpt-3.5-turbo'
        self.tokens_limit = 4096
        # as default: gpt-3.5-turbo has a tokens limit as 4096
        # when model changes, tokens will also be changed
        self.temperature = 1
        self.total_tokens_spent = 0
        self.current_tokens = self.count_token(self.messages)
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

    def handle(self, message):
        rprint("[bold cyan]ChatGPT: ")
        # breakpoint()
        with self.console.status(f"[bold cyan]ChatGPT is thinking..."):
            chunk_first = self.client.send_message(
                "chinchilla", message, with_chat_break=self.clear_history_message)
            for i in chunk_first:
                break
        with Live(console=self.console, auto_refresh=False, vertical_overflow=self.stream_overflow) as live:
            logString = ""
            try:
                for chunk in chunk_first:
                    if ChatMode.raw_mode:
                        rprint(chunk['text_new'], end="", flush=True),
                    else:
                        live.update(Markdown(chunk['text']), refresh=True)
                        logString = chunk['text']
            except KeyboardInterrupt:
                live.stop()
                self.console.print("Aborted.", style="bold cyan")
        if self.clear_history_message:
            self.clear_history_message = False
        self.log.info(f"ChatGPT: {logString}")

    def gen_title_silent(self, content):
        return "Test"

    def process_stream_response(self, response: str):
        reply: str = ""
        with Live(console=self.console, auto_refresh=False, vertical_overflow=self.stream_overflow) as live:
            try:
                rprint("[bold cyan]ChatGPT: ")
                if ChatMode.raw_mode:
                    rprint(response, end="", flush=True),
                else:
                    live.update(Markdown(reply), refresh=True)
            except KeyboardInterrupt:
                live.stop()
                self.console.print("Aborted.", style="bold cyan")
            finally:
                return {'role': 'assistant', 'content': reply}

    def process_response(self, response: str):
        if ChatMode.stream_mode:
            return self.process_stream_response(response)
        else:
            self.log.debug(f"Response: {response}")
            reply_message = response
            self.print_message(reply_message)
            return reply_message

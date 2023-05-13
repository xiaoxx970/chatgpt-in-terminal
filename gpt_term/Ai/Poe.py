from .AiClass import Ai,ChatMode
import poe
import logging
from queue import Queue
import threading
from datetime import date, datetime, timedelta


class poe_mode(Ai):
    def __init__(self, api_key, console, log, data_dir,timeout, Use_tiktoken=1) -> None:
        super().__init__(api_key, console, log, data_dir, Use_tiktoken)
        self.client = poe.Client(api_key)
        self.key_mode = "poe"
        self.message = ''
        # 日志记录到 chat.log，注释下面这行可不记录日志,如果要注释Poe模式下的注释,请到Poe类定义处
        poe.logging.basicConfig(filename=f'{data_dir}/chat.log', format='%(asctime)s %(name)s: %(levelname)-6s %(message)s',
                    datefmt='[%Y-%m-%d %H:%M:%S]', level=logging.INFO)
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
    def handel(self,message):
        for chunk in self.client.send_message("capybara", message, with_chat_break=True):
            print(chunk["text_new"], end="", flush=True)
        return chunk['text']
    def gen_title_silent(self,content):
        return "Test"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import openai
import logging
import readline

api_key = 'sk-xxx'
logging.basicConfig(filename='chat.log', level=logging.DEBUG, encoding="UTF-8")


class GPT:
    def __init__(self, api_key):
        openai.api_key = api_key
        self.messages = [
            {"role": "system", "content": "You are a helpful assistant."}]
        print("Hi, welecome to chat with gpt.")

    def send(self, message):
        self.messages.append({"role": "user", "content": message})
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=self.messages
        )
        logging.info(response)
        reply = response["choices"][0]["message"]
        self.messages.append(reply)
        return reply


chatGPT = GPT(api_key)
while True:
    message = input("> ")
    if message == "":
        continue
    reply = chatGPT.send(message)
    print("ChatGPT: ", reply["content"])
    if message in ['再见', 'bye', '结束', 'end', '退出', 'exit']:
        exit(0)

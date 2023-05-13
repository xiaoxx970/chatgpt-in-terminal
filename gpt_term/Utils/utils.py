import re

from prompt_toolkit.validation import ValidationError, Validator
from typing import Dict, List
from rich.console import Console, Group
from prompt_toolkit import PromptSession, prompt
from rich.markdown import Markdown



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
            raise ValidationError(
                message=f'Input must be at least {self.min_value}')
        if self.max_value is not None and value > self.max_value:
            raise ValidationError(
                message=f'Input must be at most {self.max_value}')

def copy_code(message: Dict[str, str], select_code_idx: int = None,console:Console() = None):
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


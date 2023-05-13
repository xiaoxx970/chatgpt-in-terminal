import i18n
import os


# 设置本地化目录和域
file_path = os.path.abspath(__file__)
mylib_path = os.path.dirname(file_path)
localedir = os.path.join(mylib_path, 'locale')
i18n.load_path.append(localedir)


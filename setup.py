from setuptools import find_packages, setup

with open("VERSION", 'r') as f:
    __version__ = f.read().strip()

with open("README.md", 'r', encoding='utf-8') as f:
    long_description = f.read()

install_requires = [
    "requests",
    "python-dotenv",
    "pyperclip",
    "rich>=13.3.1",
    "prompt_toolkit>=3.0",
    "sseclient-py>=1.7.2",
    "tiktoken"
]

setup(
    name="chatgpt-in-terminal",
    version=__version__,
    packages=find_packages(),
    description="Use ChatGPT in terminal",
    long_description=long_description,
    long_description_content_type="text/markdown",
    install_requires=install_requires,
    license="MIT",
    url="https://github.com/xiaoxx970/chatgpt-in-terminal",
    author="xiaoxx970",
    py_modules=["chat"],
    entry_points={
        "console_scripts": [
            "chatgpt-in-terminal=chat:main"
        ]
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ]
)
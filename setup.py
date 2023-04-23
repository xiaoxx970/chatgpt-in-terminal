from setuptools import find_packages, setup

with open("README.md", 'r', encoding='utf-8') as f:
    long_description = f.read()

install_requires = [
    "requests",
    "pyperclip",
    "rich>=13.3.1",
    "prompt_toolkit>=3.0",
    "sseclient-py>=1.7.2",
    "tiktoken"
]

setup(
    name="gpt-term",
    version="0.9.1",
    author="xiaoxx970",
    description="Use ChatGPT in terminal",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/xiaoxx970/chatgpt-in-terminal",
    license="MIT",

    packages=find_packages(),
    py_modules=["chat"],
    install_requires=install_requires,
    entry_points={
        "console_scripts": [
            "gpt-term=chat:main"
        ]
    },
    data_files=[('', ['config.ini'])],
    python_requires=">=3.8",
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ]
)
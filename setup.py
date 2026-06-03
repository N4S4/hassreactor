"""
hassreactor — Write Home Assistant automations in Python.

Event-driven, WebSocket-native, no YAML required.
"""
from setuptools import setup, find_packages

with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="hassreactor",
    version="0.2.1",
    description="Event-driven Home Assistant automations in Python",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Renato Visaggio",
    author_email="synology.python.api@gmail.com",
    url="https://github.com/N4S4/hassreactor",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "aiohttp>=3.8",
    ],
    entry_points={
        "console_scripts": [
            "hassreactor = hassreactor.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Home Automation",
    ],
)

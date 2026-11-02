#!/usr/bin/env python3
from setuptools import setup, find_packages
import os

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="uhdeploy",
    version="0.1.4",
    author="Abdullah Ahmad",
    url="https://github.com/AbdullahAhmad-0/Universal-Deployer",
    project_urls={
        "Bug Tracker": "https://github.com/AbdullahAhmad-0/Universal-Deployer/issues",
        "Source Code": "https://github.com/AbdullahAhmad-0/Universal-Deployer",
    },
    description="Universal Local-to-VPS automated deployment CLI (SSH/SFTP, FTP, Docker, Local Build Pipelines)",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "pyyaml>=6.0",
        "paramiko>=2.11.0",
        "colorama>=0.4.6",
    ],
    entry_points={
        "console_scripts": [
            "uhdeploy=uhdeploy.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Topic :: System :: Installation/Setup",
        "Topic :: Software Development :: Build Tools",
    ],
)


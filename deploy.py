#!/usr/bin/env python3
"""
Launcher script for backwards compatibility.
You can execute this directly:
    python deploy.py [service]
or use the installed CLI command:
    uhdeploy [service]
"""
import sys
import os

# Ensure local package can be imported if running directly from source checkout
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uhdeploy.cli import main

if __name__ == "__main__":
    main()

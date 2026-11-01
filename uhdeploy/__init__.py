"""
uhdeploy - Universal Local-to-VPS Deployment CLI
=================================================
Automated deployment tool for Docker containers, web applications,
and static websites using SSH/SFTP or FTP.
"""

__version__ = "0.1.0"
__author__ = "Abdullah Ahmad"
__license__ = "MIT"

from .cli import main

__all__ = ["main", "__version__"]


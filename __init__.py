import os, sys, pathlib

import asyncio
import secrets
import getpass
import uuid
import sqlparse
from packaging import version
import win32cred
import win32timezone

modules = list()

#util_path = os.path.dirname(os.path.abspath(__file__))

#for item in os.scandir(util_path):
#    sys.path.append(util_path)
#    modules.append(pathlib.Path(item).stem)
    #for item in os.scandir(util_path): exec(f'import {pathlib.Path(item).stem}', globals())

#__all__ = modules

__all__ = [
    'ub_debug',
    'ub_utility',
    'ub_easy_utils'
]
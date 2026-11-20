import ub_utils.general as general
import ub_utils.database as database
import sys, os, pathlib
import inspect

# To-do: update with similar code to personal sv_utils package.

DEFAULT_ORACLE_CONFIG = database.find_tnsnames()

SELF, SELF_NAME_FILE, SELF_NAME_EXTE, SELF_NAME_FULL, PARENT_DIRECTORY = '','','','', ''

def whoami():
    global SELF
    # Turns the file location into a path object to allow us to do some shenanigans
    SELF = os.path.abspath(inspect.stack()[-1].filename)
    findme()

def findme():
    global SELF, SELF_NAME_FILE, SELF_NAME_EXTE, SELF_NAME_FULL, PARENT_DIRECTORY
    # Said shenanigans.
    SELF_NAME_FILE, SELF_NAME_EXTE = os.path.splitext(os.path.basename(SELF))
    SELF_NAME_FULL = os.path.basename(SELF)
    PARENT_DIRECTORY = os.path.dirname(SELF)

def get_name_from_file(file: str):
    return os.path.splitext(os.path.basename(file))[0]

if __name__ != '__main__': whoami()
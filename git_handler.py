# UB functions for handling github connections.
# Level 1.
# Relies on other utility packages.

import subprocess
import pathlib
import win32cred
import win32timezone

try:
    import ub_utils.logging as logging
    import ub_utils.peoplesoft as peoplesoft
    import ub_utils.general as general
except Exception as e:
    import logging as logging
    import peoplesoft as peoplesoft
    import general as general

def _command_helper(directory: str, command: str, additional_args: list=None):
    # Take in a command as a string and convert it to the list format that run() takes.
    # Then run it.
    true_command = command.split()
    if additional_args:
        true_command.append(additional_args)
    try:
        subprocess.run(true_command, check=True, shell=True, cwd=directory)
    except subprocess.CalledProcessError as e:
        logging.log('error', f'Exeception encountered: {e}')

def git_push_directory(directory: str, branch: str, commit_message: str):
    try:
        _command_helper(directory=directory, command=f'git add .')
        _command_helper(directory=directory, command=f'git commit -m', additional_args=commit_message)
        _command_helper(directory=directory, command=f'git push origin {branch}')
        return True
    except subprocess.CalledProcessError as e:
        logging.log('error', f'Exeception encountered: {e}')
        return False

def git_setup_directory(directory: str, url: str, branch: str):
    general.directory_seatbelt(directory=directory)
    if not any(pathlib.Path(directory).iterdir()):
        try:
            _command_helper(directory=directory, command=f'git clone {url} ./')
            branches = _git_get_branches(directory=directory)
            if branch in branches:
                general.empty_directory(directory=directory)
                _command_helper(directory=directory, command=f'git clone {url} ./ --branch {branch}')
            else:
                _command_helper(directory=directory, command=f'git checkout -b {branch}')
        except subprocess.CalledProcessError as e:
            logging.log('error', f'Exeception encountered: {e}')
            logging.log('warn', f'This can likely be ignored, as it means the folder already exists or has items in it.')

def _git_get_branches(directory: str):
    tree = []

    for i in subprocess.check_output("git branch -a".split(), shell=True, cwd=directory).decode('UTF-8').split('\n'):
        branch = i.strip(' *').replace('remotes/origin/','')
        if (branch not in tree) and (branch != '') and (branch != 'main') and (branch != 'HEAD -> origin/main'):
            tree.append(branch)

    return tree

def git_cred_check():
    try:
        win32cred.CredRead('git:https://github.com', win32cred.CRED_TYPE_GENERIC)
        return True
    except Exception as e:
        logging.log('error', f'Exeception encountered: {e}')
        logging.log('error', f'No saved GitHub credentials found.')
        return False
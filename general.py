import os, sys, pathlib

import hashlib
import re
import stat
import time
import shutil
import glob
from functools import wraps
import asyncio
import secrets
import getpass
from datetime import datetime
from packaging.version import Version

try:
    import ub_utils.logging as logging
    import ub_utils.peoplesoft as peoplesoft
except Exception as e:
    import logging as logging
    import peoplesoft as peoplesoft
    
# ======

# Use as a decoration with @measure_speed to measure the speed of a function. Very nice for testing different methods of doing something.
def measure_speed(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        time_start = time.time()
        function_result = function(*args, **kwargs)
        time_end = time.time()
        print(f'{function.__name__}: {time_end - time_start}')
        return function_result
    return wrapper

# File and Folder Utilities

def directory_fingerprint_build(directory: str):
    local_fingerprint = {}
    directory_fingerprint_helper(directory, local_fingerprint)
    for i in local_fingerprint.keys():
        local_fingerprint[i].sort()
    return local_fingerprint

def directory_fingerprint_helper(directory: any, fingerprint: list):
    fingerprint[str(directory)] = []
    for i in pathlib.Path(directory).iterdir():
        if i.is_dir() and i.name != '.git':
            directory_fingerprint_helper(i, fingerprint=fingerprint)
        elif i.is_file() and i.name != 'CODEOWNERS':
            with open(i, 'rb') as file:
                fingerprint[str(directory)].append((i.name,hashlib.md5(file.read()).hexdigest()))

def compare_fingerprints(fingerprint_src: dict, fingerprint_dest: dict):
    return (fingerprint_src == fingerprint_dest)

def directory_fingerprint_standardize(fingerprint_src: dict, directory_src: str, directory_dest: str):
    safe_src = {}
    for i in fingerprint_src.keys():
        new_key = i.replace(directory_src, directory_dest)
        cleaned_src = directory_src.replace('./','')
        cleaned_dest = directory_dest.replace('./','')
        new_key = new_key.replace(cleaned_src, cleaned_dest)
        new_value = fingerprint_src[i]
        safe_src[new_key] = new_value

    return safe_src

def loop_helper(directory: str, filetree: list):
    logging.log('info', f'Recursive file tree crushing in progress for: {directory}')
    logging.log('info', f'Current filetree: {filetree}')
    for item in pathlib.Path(directory).iterdir():
        logging.log('info', f'Found item in directory: {item}')
        if item.is_dir() and item.name != '.git':
            logging.log('info', f'Item appears to be a directory. Feeding into loop helper function to condense.')
            loop_helper(directory=item, filetree=filetree)
        elif item.is_file() and item.name != 'CODEOWNERS':
            logging.log('info', f'Item appears to be a file. Adding onto file string.')
            try:
                #os.chmod(i, 0o777)
                #with open(i, 'rb') as file:
                filetree.append(str(item))
                logging.log('info', f'Item added successfully.')    
            except Exception as e:
                logging.log('error', f'Item could not be added.')
                logging.log('error', f'Exeception encountered: {e}')


def directory_seatbelt(directory: str):
    # Returns true if the directory needed to be made.
    return_value = False
    try:
        pathlib.Path(directory).mkdir(parents=True, exist_ok=False)
        return_value = True
    except Exception as e:
        logging.log('error', f'Exeception encountered: {e}')
        logging.log('warning', f'There is a chance the above exception can be ignored, as this statement will throw an error if the directory exists.')
        return_value = False

    if return_value: logging.log('warning', f'Folder needed to be created.')

    return return_value

def empty_directory(directory: str):
    # Delete all files and sub-folders from directory.
    logging.log('info', f'Attempting to empty directory: {directory}')
    if not directory_seatbelt(directory=directory):
        logging.log('info', f'Directory exists. Attempting to empty...')
        for root, dirs, files in os.walk(pathlib.Path(directory), topdown=False):
            for i in files:
                logging.log('info', f'Deleting file: {i}...')
                filepath = os.path.join(root, i)
                os.chmod(filepath, stat.S_IWUSR)
                os.remove(filepath)
            for i in dirs:
                logging.log('info', f'Deleting folder: {i}...')
                os.chmod(os.path.join(root, i), stat.S_IWUSR)
                os.rmdir(os.path.join(root, i))

def merge_folders(directory_src: str, directory_dest: str):
    # Alias for copy tree to avoid importing shutil into middle layer libraries. Will ignore git files.
    logging.log('info', f'Attempting to merge {directory_src} into {directory_dest}...')
    try:
        for i in [directory_dest, directory_src]:
            file_locksmith(directory=i, lock_bool=False)
        logging.log('info', f'Files reclaimed. Merging folders.')
        shutil.copytree(directory_src, directory_dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns('*.git*'))
        logging.log('info', f'Successfully merged {directory_src} into {directory_dest}.')
    except Exception as e:
        logging.log('error', f'Exeception encountered: {e}')

def remove_folder(directory: str):
    # Alias for remove directory to avoid importing os into middle layer libraries.
    logging.log('info', f'Attempting to remove {directory}...')
    try:
        os.rmdir(directory)
        logging.log('info', f'Successfully deleted {directory}.')
    except Exception as e:
        logging.log('error', f'Exeception encountered: {e}')

def folder_prune(src: dict, dest: dict):
    # Compare two fingerprints and delete anything that's the same between the two, preserving only the differences.
    for source_key in src.keys():
        if source_key in dest:
            if len(dest[source_key]) > 0:
                for source_entry in src[source_key]:
                    for h in dest[source_key]:
                        if source_entry[0] == h[0] and source_entry[1] == h[1]:
                            file = f'{source_key}{os.sep}{source_entry[0]}'
                            os.chmod(file, stat.S_IWUSR)
                            os.remove(file)   

def folder_contents_check(directory: str):
    # Checks if a folder has anything in it.
    # Returns True if a folder had items in it, False if the folder is empty.
    contents = os.listdir(directory)
    exceptions = ['.git', 'CODEOWNERS']
    for i in exceptions:
        if i in contents: contents.remove(i)
    if len(contents) != 0:
        return True
    else:
        return False

def folder_cleanup(directory: str):
    logging.log('info', f'- Attempting to delete empty folders inside: {directory} -')
    # If a folder is empty, delete it.
    deleted_directories = set()
    for dirpath, dirnames, files in os.walk(directory, topdown=False):
        has_dirnames = False
        # Need to do a little work to make sure we don't leave folders who still exist by virtue of having subdirectories.
        for dirname in dirnames:
            logging.log('info', f'Found subdirectory: {dirname}')
            if os.path.join(dirpath, dirname) not in deleted_directories:
                has_dirnames = True
                break
        
        # You would think it would do this itself by going through 
        if not any(files) and not has_dirnames:
            logging.log('info', f'{dirpath} appears to be empty. No subfolders or files. Attempting to delete...')
            deleted_directories.add(dirpath)
            os.rmdir(dirpath)

def remove_duplicate_entries(list: list):
    # Removes duplicates from a given list.
    logging.log('debug', f'- Starting List Cleaning -')
    logging.log('debug', f'Starting list: {list}')
    cleaned = []
    for i in list:
        logging.log('debug', f'Checking if {i} is already in {cleaned}')
        if i not in cleaned: 
            logging.log('debug', f'{i} is not in {cleaned}, adding to list.')
            cleaned.append(i) 
    logging.log('debug', f'List without duplicates: {cleaned}')
    return cleaned

def remove_all_from_list(input_list: list, entry_to_remove: any):
    # Removes all instances of an item from the given list.
    return [entry for entry in input_list if entry != entry_to_remove]

def file_locksmith(directory: str, lock_bool: bool=True):
    # Attempts to lock or unlock items in a directory.
    logging.log('info', f'Beginning file locksmith process...\n[INFO] - Locking is set to: {lock_bool}')
    exceptions = ['.git', 'CODEOWNERS']
    lock_parameters = ('term', 'permission')

    if lock_bool:
        lock_parameters = ('', 0o444)
    else:
        lock_parameters = ('un', 0o777)

    for root, dirs, files in os.walk(pathlib.Path(directory), topdown=False):
        for i in files:
            if i not in exceptions:
                logging.log('info', f'Attempting to {lock_parameters[0]}lock file: {i}.')
                filepath = os.path.join(root, i)
                os.chmod(filepath, lock_parameters[1])
        for i in dirs:
            if i not in exceptions:
                logging.log('info', f'Attempting to {lock_parameters[0]}lock directory: {i}.')
                filepath = os.path.join(root, i)
                os.chmod(filepath, lock_parameters[1])



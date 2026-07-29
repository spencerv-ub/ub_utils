import types
from functools import wraps
import time
import inspect
import os
import sys
from datetime import datetime
import pathlib

DEFER_PRINT = True
DEBUG_MODE = True
LOG_LEVEL = 0
# Write all of the print statements generated to a text file.
# Makes it easier than passing around the file name to write to.
if DEFER_PRINT:
    pathlib.Path('./logs/').mkdir(parents=True, exist_ok=True)
    filename_builder = f'./logs/LOG - {datetime.now().strftime("%Y-%m-%d -- %H%M")}.txt'
    sys.stdout = open(filename_builder, 'w')

PRINT_LONG_ENTRY = False
READABLE_INDENTS = True

arbitrary_process_id = 0
running_indent = -1

def print_startup(debug_mode):
    if debug_mode:
        print(f'===\nDEBUG MODE IS ACTIVE\n---\nPrint long entries is set to: {PRINT_LONG_ENTRY}\nReadable Indents is set to: {READABLE_INDENTS}\n===\nGUI wrappers will attempt to flag every function for logging now...\n')

def debug_full_info(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        global arbitrary_process_id, running_indent
        arbitrary_process_id = arbitrary_process_id + 1
        local_arbitrary_process_id = arbitrary_process_id
        if READABLE_INDENTS: running_indent = running_indent + 1
        local_indent = running_indent
        preamble = f'{'\t'*local_indent}'

        caller_frame = inspect.stack()
        
        chain_of_command = []
        for i in caller_frame:
            # Due to how wrappers work, we're going to have the debug helper technically calling every function, but we don't want to see that in the log.
            file_name = i.filename.split(os.sep)[-1]
            if (file_name != 'ub_debug.py' and file_name != '__init__.py' and file_name != '__init__.pyc' and file_name != 'ub_debug.pyc') and (file_name not in chain_of_command):
                chain_of_command.insert(0,file_name)
        chain_of_command = ' -> '.join(chain_of_command)

        function_arguments = inspect.signature(function).bind(*args, **kwargs).arguments
        for i in function_arguments:
            if i == 'password':
                function_arguments[i] = f'[PASSWORD REMOVED]'
            elif isinstance(function_arguments[i], dict):
                function_arguments[i] = _dict_to_string(function_arguments[i], indent_string=preamble)
            elif isinstance(function_arguments[i], list):
                function_arguments[i] = _dict_list_check(object_to_check=function_arguments[i], indent_string=preamble)
        function_arguments_string = f'\n{preamble} - '.join(map("{0[0]} = {0[1]}".format, function_arguments.items()))
        print(f'{preamble}\n{preamble} -- Function {local_arbitrary_process_id:05} Pre-Run Information --\n{preamble}Function: {function.__module__}.{function.__qualname__}\n{preamble}Called by file chain: {chain_of_command}\n{preamble}Arguments:\n{preamble} - {function_arguments_string}\n{preamble}Messages associated with function processes follow...\n{preamble}')
        
        time_start = time.time()
        function_result = function(*args, **kwargs)
        time_end = time.time()
        
        if isinstance(function_result, dict):
            function_result_readable = _dict_to_string(function_result, indent_string=preamble)
        elif isinstance(function_result, list):
            function_result_readable = _dict_list_check(object_to_check=function_result, indent_string=preamble)
        elif (f'{function.__module__}.{function.__qualname__}' == 'ub_utility.clean_peoplecode') or f'{function.__module__}.{function.__qualname__}' == 'ub_utility.format_sql':
            function_result_readable = _truncate_string(function_result)
        else:
            function_result_readable = function_result
        print(f'{preamble}\n{preamble} -- Function {local_arbitrary_process_id:05} Post-Run Information --\n{preamble}Function: {function.__module__}.{function.__qualname__}\n{preamble}Run took: {time_end - time_start} seconds.\n{preamble}Returned value: {function_result_readable}')
        if READABLE_INDENTS: running_indent = running_indent - 1
        return function_result
    return wrapper

def debug_measure_speed(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        global arbitrary_process_id, running_indent
        arbitrary_process_id = arbitrary_process_id + 1
        local_arbitrary_process_id = arbitrary_process_id
        if READABLE_INDENTS: running_indent = running_indent + 1
        local_indent = running_indent
        preamble = f'{_build_log_prefix('info')}{'\t'*local_indent}'

        caller_frame = inspect.stack()
        
        chain_of_command = []
        for i in caller_frame:
            # Due to how wrappers work, we're going to have the debug helper technically calling every function, but we don't want to see that in the log.
            file_name = i.filename.split(os.sep)[-1]
            if (file_name != 'ub_debug.py' and file_name != '__init__.py' and file_name != '__init__.pyc' and file_name != 'ub_debug.pyc') and (file_name not in chain_of_command):
                chain_of_command.insert(0,file_name)
        chain_of_command = ' -> '.join(chain_of_command)

        print(f'{preamble}\n{preamble} -- Function {local_arbitrary_process_id:05} Pre-Run Information --\n{preamble}Function: {function.__module__}.{function.__qualname__}\n{preamble}Called by file chain: {chain_of_command}\n{preamble}Messages associated with function processes follow...\n{preamble}')
        
        time_start = time.time()
        function_result = function(*args, **kwargs)
        time_end = time.time()
        
        print(f'{preamble}\n{preamble} -- Function {local_arbitrary_process_id:05} Post-Run Information --\n{preamble}Function: {function.__module__}.{function.__qualname__}\n{preamble}Run took: {time_end - time_start} seconds.')
        if READABLE_INDENTS: running_indent = running_indent - 1
        return function_result
    return wrapper

def debug_decorate_functions(module, decoration):
    for name in dir(module):
        utility_function = getattr(module, name)
        if isinstance(utility_function, types.FunctionType):
            setattr(module, name, decoration(utility_function))

def _dict_to_string(dictionary: dict, indent_string: str):
    string_assembly = f'CONVERTED_DICT ('
    for i in dictionary.keys():
        if ((i == 'SQLTEXT') or (i == 'PCTEXT')):
            string_assembly = f'{string_assembly}\n{indent_string}\t{i}: {_truncate_string(dictionary[i])}'
        else:
            string_assembly = f'{string_assembly}\n{indent_string}\t{i}: {dictionary[i]}'
    string_assembly = f'{string_assembly}\n{indent_string})'
    return string_assembly

def _truncate_string(string: str):
    # If a string is more than 72 characters, truncate it.
    string = string.replace('\n','')
    if (not PRINT_LONG_ENTRY) and (len(string) > 72):
        string = f'{string[:72]}... (Long entry truncated for debug readability. To change this, set PRINT_LONG_ENTRY to True in debug_helper.py)'
    return string 

def _dict_list_check(object_to_check: any, indent_string: str):
    if isinstance(object_to_check, list):
        if len(object_to_check) != 0:
            if isinstance(object_to_check[0], dict):
                dummy_list = 'CONVERTED_DICT_LIST ('
                for i in object_to_check:
                    # Better safe than sorry. Check every entry is a dict before converting.
                    if isinstance(i, dict):
                        dummy_list = f'{dummy_list}\n{indent_string}{_dict_to_string(i, indent_string=indent_string)}'
                dummy_list = f'{dummy_list}\n)'
                return dummy_list
            else:
                return object_to_check
        else:
            return object_to_check
    else:
        return object_to_check
    
def close_log_file():
    sys.stdout.close()

def get_imported_ub_modules():
    module_list = []
    for name, module in sys.modules.items():
        if name.startswith('ub_') and name != 'ub_debug':
            module_list.append(module)
    return module_list


def log(message_type: str, message: str):
    '''
    Available options for message type are:
    - info
    - debug
    - warning
    - error
    '''
    message_type_prefix, message_level = _stamp_log_prefix_level(message_type=message_type)

    if DEBUG_MODE:
        # Level 0, only print errors, warnings, or unknowns
        # Level 1, print errors, warnings, unknowns, and general info
        # Level 2, print debug info, errors, warnings, unknowns, and general info

        # Be careful where you are reading for logs, as with multi-threaded processes these logs get messy very quickly.
        if LOG_LEVEL >= message_level:
            message_prefix = f'[{_stamp_log_prefix_time()}] - [{message_type_prefix}]: '
            full_message = f'{message_prefix}{message}'
            print(full_message)

def _build_log_prefix(message_type: str):
    message_type_prefix, message_level = _stamp_log_prefix_level(message_type=message_type)
    message_prefix = f'[{_stamp_log_prefix_time()}] - [{message_type_prefix}]: '

    return message_prefix

def _stamp_log_prefix_time():
    message_time_prefix = f'{datetime.now().strftime("%Y-%m-%d - %H:%M:%S")}'

    return message_time_prefix

def _stamp_log_prefix_level(message_type: str):
    message_level = 2
    message_type_prefix = ''
    match message_type.lower():
        case 'info':
            message_type_prefix = 'INFO'
            message_level = 1
        case 'debug':
            message_type_prefix = 'DEBG'
            message_level = 2
        case 'warning':
            message_type_prefix = 'WARN'
            message_level = 0
        case 'error':
            message_type_prefix = 'ERR_'
            message_level = 0
        case _:
            message_type_prefix = 'UNKN'
            message_level = 0
    
    return message_type_prefix, message_level


def broken_log(message_type: str, message: str):
    message_type_prefix, message_level = _stamp_log_prefix_level(message_type=message_type)

    if DEBUG_MODE:
        # Level 0, only print errors, warnings, or unknowns
        # Level 1, print errors, warnings, unknowns, and general info
        # Level 2, print debug info, errors, warnings, unknowns, and general info

        # Be careful where you are reading for logs, as with multi-threaded processes these logs get messy very quickly.
        if LOG_LEVEL >= message_level:
            message_prefix = f'[{_stamp_log_prefix_time()}] - [{message_type_prefix}]: '
            full_message = f'{message_prefix}{message}'
            print(full_message)
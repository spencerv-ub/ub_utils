import hashlib
import pathlib
import os
import oracledb
from oracledb import exceptions
import re
import sqlparse
import uuid
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

import ub_debug

# Big Variables

debug = True

# For record keeping, these lists are included and may not be referenced.

# General PeopleSoft ID table.
ID_LIST = {
0 : 'NULL',
1 : 'Record',
2 : 'Field',
3 : 'Menu',
4 : 'Bar Name',
5 : 'Item Name',
9 : 'Page',
10 : 'Component',
12 : 'Event',
20 : 'Database Type',
21 : 'Effective Date',
39 : 'Market',
60 : 'Message',
66 : 'Application Engine Program',
74 : 'Component Interface',
77 : 'Section',
78 : 'Step',
87 : 'Subscription',
104 : 'Application Package',
105 : 'Class',
106 : 'Class',
107 : 'Class'
}

# SQL type translation.
SQL_TYPE_LIST = {
0 : 'SQL Object referenced from elsewhere',
1 : 'Application Engine Step',
2 : 'SQL View',
5 : 'Queries for DDDAUDIT and SYSAUDIT',
6 : 'Application Engine Step XSLT'
}

INVERTED_SQL_TYPE_LIST = dict((value,key) for key,value in SQL_TYPE_LIST.items())

PEOPLECODE_TYPE_TO_ID_LIST = {
    'Record Level Field PeopleCode': [1, 2, 12],
    'Component PeopleCode': [10, 39, 12],
    'Component Level Record PeopleCode': [10, 39, 1, 12],
    'Component Level Record Field PeopleCode': [10, 39, 1, 2, 12],
    'Page PeopleCode': [9, 12],
    'App Package PeopleCode': [104, 107, 12],
    'App Package Within Class and Sub Class PeopleCode': [104, 105, 106, 107, 12],
    'App Package Within Class PeopleCode': [104, 105, 107, 12],
    'App Engine PeopleCode and SQL': [66, 77, 39, 20, 21, 78, 12]
}

# SQL Database type translation.
SQL_DB_LIST = {
0 : 'SQL Base',
1 : 'DB2',
2 : 'Oracle',
3 : 'Informix',
4 : 'DB2-UNIX',
5 : 'AllBase',
6 : 'Sybase',
7 : 'Microsoft',
8 : 'DB2-400'
}

INVERTED_SQL_DB_LIST = dict((value,key) for key,value in SQL_DB_LIST.items())

# Type list used by app designer for project definitions.
APP_DESIGNER_TYPE_LIST = {
0 : 'Record',
1 : 'Indexes',
2 : 'Fields',
3 : 'Field Formats',
4 : 'Translates',
5 : 'Pages',
6 : 'Menus',
7 : 'Components',
8 : 'Record PeopleCode',
9 : 'Menu PeopleCode',
10 : 'Queries',
11 : 'Tree Structures',
12 : 'Trees',
13 : 'Access Groups',
14 : 'Colours',
15 : 'Styles',
17 : 'Business Processes',
18 : 'Activities',
19 : 'Roles',
20 : 'Process Definitions',
21 : 'Server Definitions',
22 : 'Process Type Definitions',
23 : 'Job Definitions',
24 : 'Recurrence Definitions',
25 : 'Message Catalog Entries',
26 : 'Dimension Definition',
27 : 'Cube Definition',
28 : 'Cube Instance Definition',
29 : 'Business Interlink',
30 : 'SQL',
31 : 'File Layout Definitions',
32 : 'Component Interfaces',
33 : 'Application Engine Programs',
34 : 'Application Engine Sections',
35 : 'Message Nodes',
36 : 'Message Channels',
37 : 'Message Definitions',
38 : 'Approval Rule Set',
39 : 'Message PeopleCode',
40 : 'Subscription PeopleCode',
42 : 'Comp. Interface PeopleCode',
43 : 'Application Engine PeopleCode',
44 : 'Page PeopleCode',
46 : 'Component PeopleCode',
47 : 'Component Record PeopleCode',
48 : 'Component Rec Fld PeopleCode',
49 : 'Images',
52 : 'File References',
53 : 'Permission Lists',
54 : 'Portal Registry Definitions',
55 : 'Portal Registry Structures',
56 : 'URL Definitions',
57 : 'Application Packages',
58 : 'Application Package PeopleCode',
60 : 'Analytic Types',
62 : 'XSLT',
64 : 'Mobile Pages',
68 : 'File References',
69 : 'File Type Codes',
72 : 'Dignostic Plug Ins',
73 : 'Analytic Models',
79 : 'Service',
80 : 'Service Operation',
81 : 'Service Operation Handler',
82 : 'Service Operation Version',
83 : 'Service Operation Routing',
84 : 'IB Queues',
85 : 'XLMP Template Definition',
86 : 'XLMP Report Definition',
87 : 'XMLP File Definition',
88 : 'XMPL Data Source Definition'
}

INVERTED_APP_DESIGNER_TYPE_LIST = dict((value.upper(),key) for key,value in APP_DESIGNER_TYPE_LIST.items())

ACCEPTABLE_IDS = ','.join(str(i) for i in ID_LIST.keys())
'''
Compile a list of acceptable PeopleCode object types.
This list is used multiple places in the system, and
in this case we're looking for all combinations of
these IDs. Such as Component Level Record PeopleCode
having the IDs
'''

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

def build_query_base(columns: list, table: str, distinct: bool=None):
    return 'select' + (' distinct ' if distinct else ' ') + ', '.join(str(i) for i in columns) + ' from ' + table

def get_columns(table: str, connection_cursor: oracledb.Connection):
    column_list = []
    '''
    According to Oracle, you should avoid using variables in a 
    string when writing SQL to the database. So we're building
    the SQL here and then subbing it in below.
    '''
    query = f'select * from {table} WHERE 0=1'
    for column in run_query(query=query, query_cursor=connection_cursor).description: column_list.append(column[0])
    return column_list

def format_peoplecode(row: dict):
    '''
    This is mostly unnecessary, it was imported from the STAT 
    extractor, but doesn't seem to remove anything from the 
    database entry PeopleCode. However, I'm leaving it in
    because I don't see any harm in it, if it's not removing
    anything. And, if by some miracle it *is* triggered,
    it's better to have the characters that would cause
    problems be filtered out. Having said that, I'm not
    willing to die on this hill, if I'm told to remove it, I will.
    '''
    peoplecode = row['PCTEXT']
    formatting_character_list = ('n','t')
    for character in formatting_character_list: peoplecode = re.sub(r'\\'+character,'\\'+character,peoplecode)
    peoplecode_cleaned = re.sub(r'\\\"','\"',peoplecode)
    return peoplecode_cleaned

def format_sql(sql_string: str):
    # Alias for SQL Formatter for debug tracking.
    return sqlparse.format(sql_string, reindent=True, comma_first=True)

def build_fingerprint(directory: str):
    local_fingerprint = {}
    fingerprint_helper(directory, local_fingerprint)
    for i in local_fingerprint.keys():
        local_fingerprint[i].sort()
    return local_fingerprint

def fingerprint_helper(directory: any, fingerprint: list):
    fingerprint[str(directory)] = []
    for i in pathlib.Path(directory).iterdir():
        if i.is_dir() and i.name != '.git':
            fingerprint_helper(i, fingerprint=fingerprint)
        elif i.is_file() and i.name != 'CODEOWNERS':
            with open(i, 'rb') as file:
                fingerprint[str(directory)].append((i.name,hashlib.md5(file.read()).hexdigest()))

def compare_fingerprints(fingerprint_src: dict, fingerprint_dest: dict):
    return (fingerprint_src == fingerprint_dest)

def standardize_fingerprint(fingerprint_src: dict, directory_src: str, directory_dest: str):
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
    ub_debug.log('info', f'Recursive file tree crushing in progress for: {directory}\n[INFO] - Current filetree: {filetree}')
    for i in pathlib.Path(directory).iterdir():
        ub_debug.log('info', f'Found item in directory: {i}')
        if i.is_dir() and i.name != '.git':
            ub_debug.log('info', f'Item appears to be a directory. Feeding into loop helper function to condense.')
            loop_helper(directory=i, filetree=filetree)
        elif i.is_file() and i.name != 'CODEOWNERS':
            ub_debug.log('info', f'Item appears to be a file. Adding onto file string.')
            try:
                #os.chmod(i, 0o777)
                #with open(i, 'rb') as file:
                filetree.append(str(i))
                ub_debug.log('info', f'Item added successfully.')    
            except Exception as e:
                ub_debug.log('error', f'Item could not be added.')
                ub_debug.log('error', f'Exeception encountered: {e}')


def file_to_row(filepath: str, connection_cursor: oracledb.Connection):
    ub_debug.log('info', f'Attempting to convert file: {filepath} to a row.')    
    file_path_object = pathlib.Path(filepath)
    file_extension = file_path_object.suffix
    file_name = file_path_object.stem
    file_path = str(file_path_object.parents[0]).replace(f'{str(file_path_object.parents[-2])}{os.sep}','')
    file = f'{file_path}{os.sep}{file_name}'.split(f'{os.sep}')
    file_type = file.pop(0)

    # Always wear your seatbelt.
    for i in file: 
        if i in PEOPLECODE_TYPE_TO_ID_LIST: file_type = i
    
    ub_debug.log('info', f'Sum of the parts:\n\tRaw Path: {filepath}\n\tPath: {file_path}\n\tName: {file_name}\n\tObject: {file_path_object}\n\tExtension: {file_extension}\n\tExtension: {file_type}')

    # Baton Pass
    if file_extension == '.sql':
        query = sql_file_to_row(file=file, file_name=file_name, file_path=file_path, file_type=file_type, connection_cursor=connection_cursor)
    else:
        query = peoplecode_file_to_row(file=file, file_name=file_name, file_path=file_path, file_type=file_type, connection_cursor=connection_cursor)

    return query

def easy_export_handler(directory: str, file: dict):
    local_filename = file['RESERVED_FOR_EXPORT_FILENAME']
    directory_seatbelt(directory)
    local_filename = f'{directory}{os.sep}{local_filename}'

    pathlib.Path(local_filename).parent.mkdir(parents=True, exist_ok=True)

    if file['RESERVED_FOR_EXPORT_SHALLOW_OBJECT_TYPE'] == 'PeopleCode':
        contents = format_peoplecode(file)
        file_extension = 'ppl'
    elif file['RESERVED_FOR_EXPORT_SHALLOW_OBJECT_TYPE'] == 'SQL':
        contents = format_sql(file['SQLTEXT'])
        file_extension = 'sql'
    else:
        contents = 'Unknown object type found.'
        file_extension = 'txt'
    
    try:
        os.chmod(f'{local_filename}.{file_extension}', 0o777)
    except Exception as e:
        ub_debug.log('error', f'Exeception encountered: {e}')
        ub_debug.log('warning', f'There is a chance the above exception can be ignored, as this statement will throw an error if the file does not exist.')

    with open(f'{local_filename}.{file_extension}', 'w') as output_file:
        output_file.write(contents)
        output_file.close()
    
    os.chmod(f'{local_filename}.{file_extension}', 0o444)

def sql_file_to_row(file: str, file_name: str, file_type: str, file_path: str, connection_cursor: oracledb.Connection):
    # Need to rebuild SQLID from the file name.
    query_base = f'{build_query_base(columns=get_columns(table='PSSQLTEXTDEFN', connection_cursor=connection_cursor),table='PSSQLTEXTDEFN')} where 1=1'
    if file_type == 'App Engine PeopleCode and SQL':
        sqlid = []
        # App Engine SQL names are stored like so: {app_engine_name}/{app_engine_sect}/{app_engine_step}
        # App Engine names can be 12 characters long, sections can be 8, and steps can be 8
        # So we need to rebuild that with spaces to build the "SQLID" the database stores
        sqlid.append(file[0].ljust(12,' '))
        sqlid.append(file[1].ljust(8,' '))
        sqlid.append(file[2].ljust(8,' '))
        query_base = query_base + f' AND SQLID like \'{''.join(sqlid)}%\''
    else:
        # We set the file name pattern, so we can work backwards from that.
        pattern = r"(.+?)\s-\s(.+?)\sfor\s(.+?)\sdatabase"
        file_values = re.search(pattern=pattern, string=file_name, flags=re.MULTILINE)

        sql_type = file_values.group(1)
        sql_name = file_values.group(2)
        sql_base = file_values.group(3)

        sql_type_value = INVERTED_SQL_TYPE_LIST[sql_type]
        sql_base_value = INVERTED_SQL_DB_LIST[sql_base]

        if sql_type_value != 0: query_base + f' AND SQLTYPE = {sql_type_value}'
        if sql_base_value != 0: sql_base_value = f' AND DBTYPE = {sql_base_value}'

        query_base = query_base + f' AND SQLID = \'{sql_name}\''

    query_results = run_query(query=query_base, query_cursor=connection_cursor)
    query_dict = query_to_dict(query_cursor=query_results)
    
    if len(query_dict) != 0:
        result_list = process_sql_dict_list(dictionary_list=query_dict, connection_cursor=connection_cursor) 
        return result_list
    else:
        return []

def peoplecode_file_to_row(file: str, file_name: str, file_type: str, file_path: str, connection_cursor: oracledb.Connection):
    id_list = PEOPLECODE_TYPE_TO_ID_LIST[file_type]
    match id_list:
            # OBJECT number and OBJECT value tuples.
            # So now the first spot is the object number and the second is the ID that it has to be.
            case [1, 2, 12]:
                id_map = [(1,1), (2,2)]
            case [10, 39, 12]:
                id_map = [(1,1), (3,39)]
            case [10, 39, 1, 12]:
                id_map = [(1,10), (3,1)]
            case [10, 39, 1, 2, 12]:
                id_map = [(1,10), (3,1), (4,2)]
            case [9, 12]:
                id_map = [(1, 9)]
            case [104, 107, 12]:
                id_map = [(1,104), (2,107)]
            case [104, 105, 106, 107, 12]:
                id_map = [(1,104), (2,105), (3,106)]
            case [104, 105, 107, 12]:
                id_map = [(1,104), (2,105), (3,107)]
            case [66, 77, 39, 20, 21, 78, 12]:
                id_map = [(1, 66), (2, 77), (6,78)]
    query_clause = ''
    if file_type != 'App Engine PeopleCode and SQL':
        for idx, i in enumerate(id_map):
            query_clause = f'{query_clause} and OBJECTID{i[0]} = {i[1]} and OBJECTVALUE{i[0]} = \'{file[idx]}\''
        if id_list != [10, 39, 12]:
            query_clause = f'{query_clause} and OBJECTID{len(id_list)} = {id_list[-1]} AND OBJECTVALUE{len(id_list)} = \'{file[-1]}\''
    else:
        query_clause = f'{query_clause} and OBJECTID1 = {id_list[0]} and OBJECTVALUE1 = \'{file[0]}\''
        query_clause = f'{query_clause} and OBJECTID2 = {id_list[1]} and OBJECTVALUE2 = \'{file[1]}\''
        query_clause = f'{query_clause} and OBJECTID6 = {id_list[-2]} and OBJECTVALUE6 = \'{file[2]}\''
    query_base = f'{build_query_base(columns=get_columns(table='PSPCMTXT', connection_cursor=connection_cursor),table='PSPCMTXT')} where 1=1{query_clause}'

    query_results = run_query(query=query_base, query_cursor=connection_cursor)
    query_dict = query_to_dict(query_cursor=query_results)

    if len(query_dict) != 0:
        result_list = process_peoplecode_dict_list(dictionary_list=query_dict) 
        return result_list
    else:
        return []
    
def get_trigger_event(row: dict, id_list: list):
    id_number = list(row.keys())[list(row.values()).index(id_list[-1])]
    field_to_check = 'OBJECTVALUE'+id_number.removeprefix('OBJECTID')
    event_trigger = row[field_to_check]
    return event_trigger

def build_backup_filename(id_list: list, dictionary: dict):
    full_file_name = ''
    for i in id_list:
        id_number = list(dictionary.keys())[list(dictionary.values()).index(i)]
        field_to_check = 'OBJECTVALUE'+id_number.removeprefix('OBJECTID')
        full_file_name = f'{dictionary[field_to_check]}{os.sep}{full_file_name}'
    if full_file_name[-1] == f'{os.sep}':
        full_file_name = full_file_name[:-1]
    return full_file_name

def process_peoplecode_dict_list(dictionary_list: list):
    condense_list = {}

    for i in dictionary_list:
        if i['PROGSEQ'] != 0:
            condense_list[f'{i['HASH_SIGNATURE']} 0'] = []
            for j in dictionary_list:
                if (i['HASH_SIGNATURE'] == j['HASH_SIGNATURE']):
                    condense_list[f'{i['HASH_SIGNATURE']} 0'].append((j['PROGSEQ'],j))

    for i in condense_list.keys():
        k = list(sorted(condense_list[i], key=lambda e: e[0]))
        for j in k:
            if j[0] != 0:
                k[0][1]['PCTEXT'] = k[0][1]['PCTEXT'] + j[1]['PCTEXT']
                dictionary_list.remove(j[1])
        condense_list[i] = k[0][1]
        
    for i in dictionary_list:
        for j in condense_list.values():
            if (i['HASH_SIGNATURE'] == j['HASH_SIGNATURE']) and (j['PROGSEQ'] == i['PROGSEQ']):
                i = j

    dictionary_list = remove_duplicate_entries(dictionary_list)

    # Now process everything.
    for i in dictionary_list:
        id_list = get_id_list_from_dict(i)
        i['RESERVED_FOR_EXPORT_SHALLOW_OBJECT_TYPE'] = 'PeopleCode'
        i['RESERVED_FOR_EXPORT_ID_LIST'] = id_list
        i['RESERVED_FOR_EXPORT_EASYNAME'] = i['OBJECTVALUE1']
        # Added 2026 - 06 - 01 to make processing between databases easier.
        peoplecode_key_list = []
        peoplecode_key_structure = ''
        for object_number in range(1,8):
            peoplecode_key_list.append(str(i[f'OBJECTID{object_number}']))
            peoplecode_key_list.append(str(i[f'OBJECTVALUE{object_number}']))        
        peoplecode_key_structure = '||'.join(peoplecode_key_list)
        i['RESERVED_FOR_EXPORT_PEOPLECODE_KEY'] = peoplecode_key_structure
        match id_list:
            case [1, 2, 12]:
                # Record Field Peoplecode
                i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE'] = 'Record Level Field PeopleCode'
                i['RESERVED_FOR_EXPORT_EASYNAME'] = f'{i['OBJECTVALUE1']} > {i['OBJECTVALUE2']}'
                i['RESERVED_FOR_EXPORT_FILENAME'] = f'{i['OBJECTVALUE1']}{os.sep}{i['OBJECTVALUE2']}{os.sep}{get_trigger_event(i, id_list)}'
            case [10, 39, 12]:
                # Component Peoplecode
                i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE'] = 'Component PeopleCode'
                i['RESERVED_FOR_EXPORT_FILENAME'] = f'{i['OBJECTVALUE1']}{os.sep}{get_trigger_event(i, id_list)}'
            case [10, 39, 1, 12]:
                # Component Level Record Peoplecode
                i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE'] = 'Component Level Record PeopleCode'
                i['RESERVED_FOR_EXPORT_EASYNAME'] = f'{i['OBJECTVALUE1']} > {i['OBJECTVALUE3']}'
                i['RESERVED_FOR_EXPORT_FILENAME'] = f'{i['OBJECTVALUE1']}{os.sep}{i['OBJECTVALUE3']}{os.sep}{get_trigger_event(i, id_list)}'
            case [10, 39, 1, 2, 12]:
                # Component Level Record Field Peoplecode
                i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE'] = 'Component Level Record Field PeopleCode'
                i['RESERVED_FOR_EXPORT_EASYNAME'] = f'{i['OBJECTVALUE1']} > {i['OBJECTVALUE2']} > {i['OBJECTVALUE3']} > {i['OBJECTVALUE4']}'
                i['RESERVED_FOR_EXPORT_FILENAME'] = f'{i['OBJECTVALUE1']}{os.sep}{i['OBJECTVALUE3']}{os.sep}{i['OBJECTVALUE4']}{os.sep}{get_trigger_event(i, id_list)}'
            case [9, 12]:
                # Page Peoplecode
                i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE'] = 'Page PeopleCode'
                i['RESERVED_FOR_EXPORT_FILENAME'] = f'{i['OBJECTVALUE1']}{os.sep}{get_trigger_event(i, id_list)}'
            case [104, 107, 12]:
                # App Package Peoplecode
                i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE'] = 'App Package PeopleCode'
                i['RESERVED_FOR_EXPORT_FILENAME'] = f'{i['OBJECTVALUE1']}{os.sep}{i['OBJECTVALUE2']}{os.sep}{get_trigger_event(i, id_list)}'
                i['RESERVED_FOR_EXPORT_EASYNAME'] = f'{i['OBJECTVALUE1']} > {i['OBJECTVALUE2']}'
            case [104, 105, 106, 107, 12]:
                # App Package Peoplecode Within Class And Sub Class
                i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE'] = 'App Package Within Class and Sub Class PeopleCode'
                i['RESERVED_FOR_EXPORT_FILENAME'] = f'{i['OBJECTVALUE1']}{os.sep}{i['OBJECTVALUE2']}{os.sep}{i['OBJECTVALUE3']}{os.sep}{i['OBJECTVALUE4']}{os.sep}{get_trigger_event(i, id_list)}'
                i['RESERVED_FOR_EXPORT_EASYNAME'] = f'{i['OBJECTVALUE1']} > {i['OBJECTVALUE2']} > {i['OBJECTVALUE3']} > {i['OBJECTVALUE4']}'
            case [104, 105, 107, 12]:
                # App Package Peoplecode Within Class
                i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE'] = 'App Package Within Class PeopleCode'
                i['RESERVED_FOR_EXPORT_FILENAME'] = f'{i['OBJECTVALUE1']}{os.sep}{i['OBJECTVALUE2']}{os.sep}{i['OBJECTVALUE3']}{os.sep}{get_trigger_event(i, id_list)}'
                i['RESERVED_FOR_EXPORT_EASYNAME'] = f'{i['OBJECTVALUE1']} > {i['OBJECTVALUE2']} > {i['OBJECTVALUE3']}'
            case [66, 77, 39, 20, 21, 78, 12]:
                # App Engine Program (the reason I wrote all this)
                i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE'] = 'App Engine PeopleCode and SQL'
                # Removed from below after object value 2: {(f'{i['OBJECTVALUE4']}{os.sep}' if (i['OBJECTVALUE4'] != 'default') else f'')}
                i['RESERVED_FOR_EXPORT_FILENAME'] = f'{i['OBJECTVALUE1']}{os.sep}{i['OBJECTVALUE2']}{os.sep}{i['OBJECTVALUE6']}{(f'{os.sep}' + get_trigger_event(i, id_list) if (get_trigger_event(i, id_list) != 'OnExecute') else f"")}'
                i['RESERVED_FOR_EXPORT_EASYNAME'] = f'{i['OBJECTVALUE1']} - Section: {i['OBJECTVALUE2']}, Step: {i['OBJECTVALUE6']}'
            case _:
                # Anything else.
                i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE'] = 'Generic PeopleCode'
                i['RESERVED_FOR_EXPORT_FILENAME'] = build_backup_filename(id_list=id_list, dictionary=i)
        i['RESERVED_FOR_EXPORT_FILENAME'] = f'{i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE']}{os.sep}{i['RESERVED_FOR_EXPORT_FILENAME']}'
        i['RESERVED_FOR_EXPORT_UUID'] = str(uuid.uuid4())
    return dictionary_list

def process_sql_dict_list(dictionary_list: list, connection_cursor: oracledb.Connection):
    '''
    It's also viable to sort the original database results, but in the speed tests this performed faster for smaller data sets.
    And I feel that would be more valuable to the user experience than the SQL method.
    Both methods performed identically for larger data sets.
    # dictionary_list = list(sorted(dictionary_list, key=lambda d: d['SEQNUM']))
    '''
    condense_list = {}

    if 'SEQNUM' in dictionary_list[0]:
        for i in dictionary_list:
            if i['SEQNUM'] != 0:
                dummy_i = i.copy()
                dummy_i.pop('SQLTEXT')
                dummy_i.pop('SEQNUM')
                construct_key = ''
                for k in dummy_i.keys():
                    construct_key = f'{construct_key} {dummy_i[k]}'
                construct_key = f'{construct_key} 0'
                condense_list[construct_key] = []
                for j in dictionary_list:
                    dummy_j = j.copy()
                    dummy_j.pop('SQLTEXT')
                    dummy_j.pop('SEQNUM')
                    if dummy_i == dummy_j:
                        condense_list[construct_key].append((j['SEQNUM'],j))

        for i in condense_list.keys():
            k = list(sorted(condense_list[i], key=lambda e: e[0]))
            for j in k:
                if j[0] != 0:
                    k[0][1]['SQLTEXT'] = k[0][1]['SQLTEXT'] + j[1]['SQLTEXT']
                    dictionary_list.remove(j[1])
            condense_list[i] = k[0][1]
        
        for i in dictionary_list:
            for j in condense_list.values():
                dummy_i = i.copy()
                dummy_i.pop('SQLTEXT')
                dummy_j = j.copy()
                dummy_j.pop('SQLTEXT')
                if dummy_i == dummy_j:
                    i = j
    
    dictionary_list = remove_duplicate_entries(dictionary_list)
    # Now process everything.
    
    for i in dictionary_list:
        # Easy check to see if we're using the standard SQL format.
        if 'DBTYPE' in i:
            if i['DBTYPE'] == ' ':
                i['DBTYPE'] = 0
            else:
                i['DBTYPE'] = int(i['DBTYPE'])

        i['RESERVED_FOR_EXPORT_SHALLOW_OBJECT_TYPE'] = 'SQL'
        if 'SQLTYPE' in i:
            if int(i['SQLTYPE']) == 1:
                '''
                App Engine SQL definitions are finicky.
                The database stores the actual data as VARCHARS
                with limited lengths, then fills in every remaining 
                character with spaces before concatenating name to
                section to step. This results in a varying number
                of spaces between each value, from 11 to 0... But, 
                this does enable us to separate the fields by character
                index ranges then remove excess spaces to get the 
                proper App Engine ID, Step, and Section.
                '''
                app_engine_name = i['SQLID'][:12].strip()
                app_engine_sect = i['SQLID'][12:20].strip()
                app_engine_step = i['SQLID'][20:28].strip()
                fetch_app_engine_info_query = build_query_base(get_columns(table='PSAESTEPDEFN', connection_cursor=connection_cursor), 'PSAESTEPDEFN') + ' where 1=1 AND AE_APPLID = :bind1 AND AE_STEP = :bind2'
                query_cursor = run_query(query=fetch_app_engine_info_query, query_cursor=connection_cursor, bind1=app_engine_name, bind2=app_engine_step)
                results = query_to_dict(query_cursor)
                results = results[0]
                i['RESERVED_FOR_EXPORT_EASYNAME'] = f'{app_engine_name} - Section: {app_engine_sect}, Step: {app_engine_step}'
                i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE'] = 'App Engine PeopleCode and SQL'
                i['RESERVED_FOR_EXPORT_FILENAME'] = f'App Engine PeopleCode and SQL{os.sep}{results['AE_APPLID']}{os.sep}{results['AE_SECTION']}{os.sep}{results['AE_STEP']}'
            else:
                i['RESERVED_FOR_EXPORT_EASYNAME'] = i['SQLID']
                i['RESERVED_FOR_EXPORT_FILENAME'] = SQL_TYPE_LIST[int(i['SQLTYPE'])] + ' - ' + i['SQLID'] + ' for ' + SQL_DB_LIST[i['DBTYPE']] + ' database'
        elif i['RESERVED_FOR_EXPORT_DEEP_OBJECT_TYPE'] == 'SUNYIR_DATA':
            i['RESERVED_FOR_EXPORT_FILENAME'] = f'{i['UB_SUNY_PRCS_TYPE']}{os.sep}{i['RECNAME']}'
        else:
            # Catch specifically designed for SUNYIR exporting. Meant to be fairly fault tolerant instead 
            # of specific to SUNYIR in case of weird happenings in the database or further uses of the SUNYIR method.
            dummy_i = i.copy()
            columns_to_remove = ['SQLTEXT','UB_SUNY_INST']
            for j in columns_to_remove:
                dummy_i.pop(j)
            filename = ''
            for idj, j in enumerate(dummy_i.keys()):
                if idj > 0:
                    if str(dummy_i[j]).strip() == '':
                        filename = f'{filename} - {str(j)}'
                    else:
                        filename = f'{filename} - {str(dummy_i[j])}'
                else:
                    filename = f'{str(dummy_i[j])}'
            i['RESERVED_FOR_EXPORT_FILENAME'] = filename 
        i['RESERVED_FOR_EXPORT_UUID'] = str(uuid.uuid4())

    return dictionary_list
    
def get_id_list_from_dict(dictionary: dict):
    id_list = []
    for i in dictionary:
        if ('OBJECTID' in i) & (dictionary[i] != 0):
            id_list.append(dictionary[i])
    return id_list

'''
Oracle has their own way they recommend doing this.
However, after testing: it's not great.
It more or less boils down to doing the same as these two functions *and* the run_query helper function.
Then using lambda to make a "row factory" so every row fetched has a function executed on it.
Also this is faster. Might be confirmation bias, but also we're not using lambda which should help.
(Python is notoriously slow when it comes to using Lambda functions.)
'''
def row_to_dict(query_cursor: oracledb.Connection, row: tuple):
    column_names = []
    for column in query_cursor.description:
        column_names.append(column[0])
    temp_dict = {}
    for i in range(len(column_names)):
        temp_dict[column_names[i]] = row[i]
    return temp_dict

def query_to_dict(query_cursor: oracledb.Connection):
    results = []
    column_names = []
    
    try:
        for column in query_cursor.description:
            column_names.append(column[0])

        for row in query_cursor:
            temp_dict = {}
            for i in range(len(column_names)):
                temp_dict[column_names[i]] = row[i]
            results.append(temp_dict)
    except Exception as e:
        ub_debug.log('error', f'Exeception encountered: {e}')
        
    return results

def directory_seatbelt(directory: str):
    # Returns true if the directory needed to be made.
    try:
        pathlib.Path(directory).mkdir(parents=True, exist_ok=False)
        return True
    except Exception as e:
        ub_debug.log('error', f'Exeception encountered: {e}')
        ub_debug.log('warning', f'There is a chance the above exception can be ignored, as this statement will throw an error if the directory exists.')
        return False

def empty_directory(directory: str):
    ub_debug.log('info', f'Attempting to empty directory: {directory}')
    if not directory_seatbelt(directory=directory):
        ub_debug.log('info', f'Directory exists. Attempting to empty...')
        for root, dirs, files in os.walk(pathlib.Path(directory), topdown=False):
            for i in files:
                ub_debug.log('info', f'Deleting file: {i}...')
                filepath = os.path.join(root, i)
                os.chmod(filepath, stat.S_IWUSR)
                os.remove(filepath)
            for i in dirs:
                ub_debug.log('info', f'Deleting folder: {i}...')
                os.chmod(os.path.join(root, i), stat.S_IWUSR)
                os.rmdir(os.path.join(root, i))

def merge_folders(directory_src: str, directory_dest: str):
    # Alias for copy tree to avoid importing shutil into middle layer libraries. Will ignore git files.
    ub_debug.log('info', f'Attempting to merge {directory_src} into {directory_dest}...')
    try:
        for i in [directory_dest, directory_src]:
            file_locksmith(directory=i, lock_bool=False)
        ub_debug.log('info', f'Files reclaimed. Merging folders.')
        shutil.copytree(directory_src, directory_dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns('*.git*'))
        ub_debug.log('info', f'Successfully merged {directory_src} into {directory_dest}.')
    except Exception as e:
        ub_debug.log('error', f'Exeception encountered: {e}')

def remove_folder(directory: str):
    # Alias for remove directory to avoid importing os into middle layer libraries.
    ub_debug.log('info', f'Attempting to remove {directory}...')
    try:
        os.rmdir(directory)
        ub_debug.log('info', f'Successfully deleted {directory}.')
    except Exception as e:
        ub_debug.log('error', f'Exeception encountered: {e}')

def folder_prune(src: dict, dest: dict):
    # Compare two fingerprints and delete anything that's the same between the two, preserving only the differences.
    for i in src.keys():
        if i in dest:
            if len(dest[i]) > 0:
                for j in src[i]:
                    for h in dest[i]:
                        if j[0] == h[0] and j[1] == h[1]:
                            file = f'{i}{os.sep}{j[0]}'
                            os.chmod(file, stat.S_IWUSR)
                            os.remove(file)   

def folder_contents_check(directory: str):
    contents = os.listdir(directory)
    exceptions = ['.git', 'CODEOWNERS']
    for i in exceptions:
        if i in contents: contents.remove(i)
    if len(contents) != 0:
        return True
    else:
        return False

def folder_cleanup(directory: str):
    ub_debug.log('info', f'- Attempting to delete empty folders inside: {directory} -')
    # If a folder is empty, delete it.
    deleted_directories = set()
    for dirpath, dirnames, files in os.walk(directory, topdown=False):
        has_dirnames = False
        # Need to do a little work to make sure we don't leave folders who still exist by virtue of having subdirectories.
        for dirname in dirnames:
            ub_debug.log('info', f'Found subdirectory: {dirname}')
            if os.path.join(dirpath, dirname) not in deleted_directories:
                has_dirnames = True
                break
        
        # You would think it would do this itself by going through 
        if not any(files) and not has_dirnames:
            ub_debug.log('info', f'{dirpath} appears to be empty. No subfolders or files. Attempting to delete...')
            deleted_directories.add(dirpath)
            os.rmdir(dirpath)

def remove_duplicate_entries(list: list):
    # Remove duplicates from the list.
    ub_debug.log('debug', f'- Starting List Cleaning -')
    ub_debug.log('debug', f'Starting list: {list}')
    cleaned = []
    for i in list:
        ub_debug.log('debug', f'Checking if {i} is already in {cleaned}')
        if i not in cleaned: 
            ub_debug.log('debug', f'{i} is not in {cleaned}, adding to list.')
            cleaned.append(i) 
    ub_debug.log('debug', f'List without duplicates: {cleaned}')
    return cleaned

def run_query(query: str, query_cursor: oracledb.Connection, bind1: str=None, bind2: str=None):
    ub_debug.log('info', f'- Attempting to run query -')
    ub_debug.log('info', f'Query Cursor: {query_cursor}')
    ub_debug.log('info', f'Query: {query}')
    if query_cursor:
        if (bind1 == None) & (bind2 == None):
            ub_debug.log('info', f'No additional binds.')
            query_cursor.execute(query)
        elif (bind1 == None) & (bind2 != None):
            ub_debug.log('info', f'Query Bind 2: {bind2}')
            query_cursor.execute(query, bind2 = bind2)
        elif (bind1 != None) & (bind2 == None):
            ub_debug.log('info', f'Query Bind 1: {bind1}')
            query_cursor.execute(query, bind1 = bind1)
        else:
            ub_debug.log('info', f'Query Bind 2: {bind2}')
            query_cursor.execute(query, bind1 = bind1, bind2 = bind2)
        return query_cursor

def build_database_connection(username: str, password: str, database: str):
    ub_debug.log('info', f'- Attempting to build database connection -')
    connection_object = oracledb.connect(
                user=username,
                password=password,
                dsn=f'cs{database}eas.buffalo.edu')
    ub_debug.log('info', f'Connection object created.')
    ub_debug.log('info', f'Attempting to create cursor object...')
    connection_cursor = connection_object.cursor()
    ub_debug.log('info', f'Cursor object created.')
    ub_debug.log('info', f'Attempting to set schema...')
    connection_cursor.execute('ALTER SESSION SET current_schema=SYSADM')
    ub_debug.log('info', f'Schema successfully set to SYSADM.')
    ub_debug.log('info', f'Returning cursor object.')
    return connection_cursor
    

def database_handshake(connection_cursor: oracledb.Connection, table_list: list):
    return_list = []
    ub_debug.log('info', f'Beginning access check for tables: {table_list}')
    for i in table_list:
        try:
            ub_debug.log('info', f'Attempting to fetch list of columns from table: {i}')
            get_columns(table=i, connection_cursor=connection_cursor)
        except oracledb.DatabaseError as e:    
            ub_debug.log('warning', f'Exeception encountered: {e}')
            ub_debug.log('warning', f'Could not access: {i}')
            ub_debug.log('warning', f'Adding \'{i}\' to list of returned tables.')
            ub_debug.log('warning', f'This is likely a permission error.')
            return_list.append(i)
        except Exception as e:
            ub_debug.log('error', f'Exeception encountered: {e}')
            ub_debug.log('error', f'Unexpected error encountered trying to access table: {i}')
    return return_list

def file_locksmith(directory: str, lock_bool: bool=True):
    ub_debug.log('info', f'Beginning file locksmith process...\n[INFO] - Locking is set to: {lock_bool}')
    exceptions = ['.git', 'CODEOWNERS']
    lock_parameters = ('term', 'permission')

    if lock_bool:
        lock_parameters = ('', 0o444)
    else:
        lock_parameters = ('un', 0o777)

    for root, dirs, files in os.walk(pathlib.Path(directory), topdown=False):
        for i in files:
            if i not in exceptions:
                ub_debug.log('info', f'Attempting to {lock_parameters[0]}lock file: {i}.')
                filepath = os.path.join(root, i)
                os.chmod(filepath, lock_parameters[1])
        for i in dirs:
            if i not in exceptions:
                ub_debug.log('info', f'Attempting to {lock_parameters[0]}lock directory: {i}.')
                filepath = os.path.join(root, i)
                os.chmod(filepath, lock_parameters[1])

def get_oracle_version(oracle_root: pathlib.Path):
    oracle_root = oracle_root.glob('*/')
    oracle_versions = []
    for i in oracle_root: 
        oracle_versions.append(i.name)
    sorted_versions = sorted(oracle_versions, key=Version)
    if len(sorted_versions) != 0:
        max_version = sorted_versions[-1]
    else:
        max_version = -1
    return max_version

def find_tnsnames(drive_letter: str=None):
    try:
        if not drive_letter: drive_letter = 'C'
        oracle_root = pathlib.Path(f'{drive_letter}:{os.sep}oracle{os.sep}product{os.sep}')
        oracle_version = get_oracle_version(oracle_root=oracle_root)
        if oracle_version != -1:
            tnsnames_path = list(pathlib.Path(f'{oracle_root}{os.sep}{oracle_version}{os.sep}').glob('**/*[!sample]*/*TNSNAMES.ORA'))
            if (len(tnsnames_path) == 0):
                return ''
            else:
                single_path = str(tnsnames_path[0].parent)
                return single_path
        else:
            return ''
    except Exception as e:
        ub_debug.log('error', e)
        return ''
    

def run_query_to_dict(query: str, query_cursor: oracledb.Connection, bind1: str=None, bind2: str=None):
    ub_debug.log('debug', f'Attempting to run query: {query}')
    query_results = run_query(query=query, query_cursor=query_cursor, bind1=bind1, bind2=bind2)
    ub_debug.log('debug', f'Query fetch appears to be complete.')
    ub_debug.log('debug', f'Attempting to convert to dictionary.')
    query_dict = query_to_dict(query_results)
    ub_debug.log('debug', f'Dictionary conversion appears to be complete.')
    ub_debug.log('debug', f'Returning dictionary object.')
    return query_dict

def remove_all_from_list(input_list: list, entry_to_remove: any):
    return [entry for entry in input_list if entry != entry_to_remove]

def close_connection(connection_cursor: oracledb.Connection):
    # Last call. Don't gotta go home, but ya can't stay here.
    try:
        connection_cursor.close()
    except oracledb.InterfaceError as e:
            ub_debug.log('warning',f'Tried to close connection that does not exist. - {e}')

def connection_last_call():
    for i in dir():
        if type(i) == oracledb.Cursor:
            close_connection(connection_cursor=i)

    for i in globals().keys():
        if type(globals()[i]) == oracledb.Cursor:
            close_connection(connection_cursor=globals()[i])
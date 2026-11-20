# UB functions for handling database connections.
# Level 1.
# Relies on other utility packages.

import hashlib
import pathlib
import os
import oracledb
from oracledb import exceptions
import re
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

try:
    import ub_utils.logging as logging
    import ub_utils.peoplesoft as peoplesoft
    import ub_utils.general as general
except Exception as e:
    import logging as logging
    import peoplesoft as peoplesoft
    import general as general

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

def file_to_row(filepath: str, connection_cursor: oracledb.Connection):
    logging.log('info', f'Attempting to convert file: {filepath} to a row.')    
    file_path_object = pathlib.Path(filepath)
    file_extension = file_path_object.suffix
    file_name = file_path_object.stem
    file_path = str(file_path_object.parents[0]).replace(f'{str(file_path_object.parents[-2])}{os.sep}','')
    file = f'{file_path}{os.sep}{file_name}'.split(f'{os.sep}')
    file_type = file.pop(0)

    # Always wear your seatbelt.
    for i in file: 
        if i in peoplesoft.PEOPLECODE_TYPE_TO_ID_LIST: file_type = i
    
    logging.log('info', f'Sum of the parts:\n\tRaw Path: {filepath}\n\tPath: {file_path}\n\tName: {file_name}\n\tObject: {file_path_object}\n\tExtension: {file_extension}\n\tExtension: {file_type}')

    # Baton Pass
    if file_extension == '.sql':
        query = sql_file_to_row(file=file, file_name=file_name, file_path=file_path, file_type=file_type, connection_cursor=connection_cursor)
    else:
        query = peoplecode_file_to_row(file=file, file_name=file_name, file_path=file_path, file_type=file_type, connection_cursor=connection_cursor)

    return query

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

        sql_type_value = peoplesoft.INVERTED_SQL_TYPE_LIST[sql_type]
        sql_base_value = peoplesoft.INVERTED_SQL_DB_LIST[sql_base]

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
    id_list = peoplesoft.PEOPLECODE_TYPE_TO_ID_LIST[file_type]
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

def row_to_dict(query_cursor: oracledb.Connection, row: tuple):
    '''
    Oracle has their own way they recommend doing this.
    However, after testing: it's not great.
    It more or less boils down to doing the same as these two functions *and* the run_query helper function.
    Then using lambda to make a "row factory" so every row fetched has a function executed on it.
    Also this is faster. Might be confirmation bias, but also we're not using lambda which should help.
    (Python is notoriously slow when it comes to using Lambda functions.)
    '''
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
        logging.log('error', f'Exeception encountered: {e}')
        
    return results

def run_query(query: str, query_cursor: oracledb.Connection, bind1: str=None, bind2: str=None):
    logging.log('info', f'- Attempting to run query -')
    logging.log('info', f'Query Cursor: {query_cursor}')
    logging.log('info', f'Query: {query}')
    if query_cursor:
        if (bind1 == None) & (bind2 == None):
            logging.log('info', f'No additional binds.')
            query_cursor.execute(query)
        elif (bind1 == None) & (bind2 != None):
            logging.log('info', f'Query Bind 2: {bind2}')
            query_cursor.execute(query, bind2 = bind2)
        elif (bind1 != None) & (bind2 == None):
            logging.log('info', f'Query Bind 1: {bind1}')
            query_cursor.execute(query, bind1 = bind1)
        else:
            logging.log('info', f'Query Bind 2: {bind2}')
            query_cursor.execute(query, bind1 = bind1, bind2 = bind2)
        return query_cursor

def build_database_connection(username: str, password: str, database: str):
    logging.log('info', f'- Attempting to build database connection -')
    connection_object = oracledb.connect(
                user=username,
                password=password,
                dsn=f'cs{database}eas.buffalo.edu')
    logging.log('info', f'Connection object created.')
    logging.log('info', f'Attempting to create cursor object...')
    connection_cursor = connection_object.cursor()
    logging.log('info', f'Cursor object created.')
    logging.log('info', f'Attempting to set schema...')
    connection_cursor.execute('ALTER SESSION SET current_schema=SYSADM')
    logging.log('info', f'Schema successfully set to SYSADM.')
    logging.log('info', f'Returning cursor object.')
    return connection_cursor
    

def database_handshake(connection_cursor: oracledb.Connection, table_list: list):
    return_list = []
    logging.log('info', f'Beginning access check for tables: {table_list}')
    for i in table_list:
        try:
            logging.log('info', f'Attempting to fetch list of columns from table: {i}')
            get_columns(table=i, connection_cursor=connection_cursor)
        except oracledb.DatabaseError as e:    
            logging.log('warning', f'Exeception encountered: {e}')
            logging.log('warning', f'Could not access: {i}')
            logging.log('warning', f'Adding \'{i}\' to list of returned tables.')
            logging.log('warning', f'This is likely a permission error.')
            return_list.append(i)
        except Exception as e:
            logging.log('error', f'Exeception encountered: {e}')
            logging.log('error', f'Unexpected error encountered trying to access table: {i}')
    return return_list



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
        logging.log('error', e)
        return ''

def run_query_to_dict(query: str, query_cursor: oracledb.Connection, bind1: str=None, bind2: str=None):
    logging.log('debug', f'Attempting to run query: {query}')
    query_results = run_query(query=query, query_cursor=query_cursor, bind1=bind1, bind2=bind2)
    logging.log('debug', f'Query fetch appears to be complete.')
    logging.log('debug', f'Attempting to convert to dictionary.')
    query_dict = query_to_dict(query_results)
    logging.log('debug', f'Dictionary conversion appears to be complete.')
    logging.log('debug', f'Returning dictionary object.')
    return query_dict

def close_connection(connection_cursor: oracledb.Connection):
    try:
        connection_cursor.close()
    except oracledb.InterfaceError as e:
            logging.log('warning',f'Tried to close connection that does not exist. - {e}')

def connection_last_call():
    # Last call. Don't gotta go home, but ya can't stay here.
    for i in dir():
        if type(i) == oracledb.Cursor:
            close_connection(connection_cursor=i)

    for i in globals().keys():
        if type(globals()[i]) == oracledb.Cursor:
            close_connection(connection_cursor=globals()[i])

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

    # De-dupe list immediately as sometimes the queries can return multiple rows for the same PeopleCode
    # Especially in the case of nested classes/packs.
    dictionary_list = ub_utils.general.remove_duplicate_entries(dictionary_list)

    logging.log('debug', 'Beginning attempt to condense PeopleCode Dict List.')

    # Loop through the provided list, make a collection of every peoplecode object by hash and store the rows associated with it.
    for row in dictionary_list:
        if f'{row['HASH_SIGNATURE']}' not in condense_list.keys():
            condense_list[f'{row['HASH_SIGNATURE']}'] = []
        if (row['PROGSEQ'],row) not in condense_list[f'{row['HASH_SIGNATURE']}']:
            logging.log('debug', f'Found entry for hash {row['HASH_SIGNATURE']} that was not in list to condense, progseq is: {row['PROGSEQ']}.')
            condense_list[f'{row['HASH_SIGNATURE']}'].append((row['PROGSEQ'],row))

    if logging.DEBUG_MODE:
        for log_entry in condense_list.keys():
            logging.log('debug', f'Need to sequence: {log_entry}, number of entries: {len(condense_list[log_entry])}')

    # For every entry in the created list:
    # 1. Sort the rows by progseq
    # 2. Loop through the collected rows
    #  2a. Append the peoplecode contents of the row to a running string.
    #  2b. Remove the row from the original dict list.
    # 3. Set the entry in the condense list to the running string.
    for entry_to_condense in condense_list.keys():
        rows_to_condense = list(sorted(condense_list[entry_to_condense], key=lambda row: row[0]))
        peoplecode_text = ''
        for entry in rows_to_condense:
            logging.log('debug', f'Attempting to append progseq {entry[0]} for hash value: {entry_to_condense}')
            peoplecode_text = f'{peoplecode_text}{entry[1]['PCTEXT']}'
            logging.log('debug', f'Attempting to remove row from running dictionary list: {logging.easy_dict_print(entry[1])}')
            # Why is this so important?
            if entry[0] != 0:
                dictionary_list.remove(entry[1])
            logging.log('debug', f'Dictionary list is now {len(dictionary_list)} entries long.')
        condense_list[entry_to_condense] = peoplecode_text

    # Now that we have a list of hashes with compiled peoplecode, we need to find the entries with those hash values.
    # Loop through the list to find where the hash value matches an entry in the condense list and the progseq is 0.
    for running_process_list_entry in dictionary_list:
        for condense_list_entry in condense_list.keys():
            if (running_process_list_entry['HASH_SIGNATURE'] == condense_list_entry): 
                logging.log('debug', f'Hash values match between these two entries:')
                logging.log('debug', f'{logging.easy_dict_print(running_process_list_entry)}')
                logging.log('debug', f'{condense_list_entry}')
                running_process_list_entry['PCTEXT'] = condense_list[condense_list_entry]

    # De-dupe list just to be safe.
    dictionary_list = ub_utils.general.remove_duplicate_entries(dictionary_list)

    # Show if there are any duplicate rows after de-duping
    if logging.DEBUG_MODE:
        dummy_compare_list = []
        for entry in dictionary_list:
            keys_to_ignore = ['PROGSEQ','PCTEXT']
            dummy_compare_entry = entry.copy()
            for key in keys_to_ignore:
                if key in dummy_compare_entry.keys():
                    del dummy_compare_entry[key]
            
            if dummy_compare_entry not in dummy_compare_list:
                logging.log('debug', f'Found new entry: {logging.easy_dict_print(dummy_compare_entry)}')
                dummy_compare_list.append(dummy_compare_entry)
            else:
                logging.log('debug', f'Found missed duplicate entry: {logging.easy_dict_print(dummy_compare_entry)}')
                        

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
    
    dictionary_list = general.remove_duplicate_entries(dictionary_list)
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
import hashlib
import pathlib
import os
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

try:
    import ub_utils.logging as logging
    import ub_utils.general as general
except Exception as e:
    import logging as logging
    import general as general

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

def format_peoplecode(peoplecode_string: str):
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
    peoplecode = peoplecode_string
    formatting_character_list = ('n','t')
    for character in formatting_character_list: peoplecode = re.sub(r'\\'+character,'\\'+character,peoplecode)
    peoplecode_cleaned = re.sub(r'\\\"','\"',peoplecode)
    return peoplecode_cleaned

def format_sql(sql_string: str):
    # Alias for SQL Formatter for debug tracking.
    return sqlparse.format(sql_string, reindent=True, comma_first=True)

def easy_export_handler(directory: str, file: dict):
    # Given an exported database row/object dict, exports the file.
    local_filename = file['RESERVED_FOR_EXPORT_FILENAME']
    general.directory_seatbelt(directory)
    local_filename = f'{directory}{os.sep}{local_filename}'

    pathlib.Path(local_filename).parent.mkdir(parents=True, exist_ok=True)

    if file['RESERVED_FOR_EXPORT_SHALLOW_OBJECT_TYPE'] == 'PeopleCode':
        contents = format_peoplecode(file['PCTEXT'])
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
        logging.log('error', f'Exeception encountered: {e}')
        logging.log('warning', f'There is a chance the above exception can be ignored, as this statement will throw an error if the file does not exist.')

    with open(f'{local_filename}.{file_extension}', 'w') as output_file:
        output_file.write(contents)
        output_file.close()
    
    os.chmod(f'{local_filename}.{file_extension}', 0o444)
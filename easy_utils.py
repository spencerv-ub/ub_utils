import re
from multiprocessing import Pool

def easy_regex(string: str, regex: str, group_bool: bool=None):
    results = list()
    matches = re.finditer(regex, string, re.MULTILINE | re.IGNORECASE)
    if group_bool:
        for i in matches: results.append(i.group(1))
    else:
        for i in matches: results.append(i)
    return results

def easy_threadpool(process: any, values: list):
    '''
    Merc with a mouth.
    '''
    with Pool(processes=4) as pool:
        weave = pool.map(process, values)
        weave = list(filter(None, weave))
        return weave
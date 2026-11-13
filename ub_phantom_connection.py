import ub_utils.ub_git_handler as ub_git_handler
import ub_utils.ub_utility as ub_utility
import oracledb
import ub_utils.ub_debug as ub_debug

if ub_utility.debug:
    for i in ub_debug.get_imported_ub_modules():
        ub_debug.debug_decorate_functions(module=i, decoration=ub_debug.debug_measure_speed)

def ghost_folder(source_filepath: str, destination_filepath: str, connection_cursor: oracledb.Connection, git_branch: str, git_url: str, git_commit_message: str):
    filetree_to_crush = []
    list_of_queries = []

    ub_utility.empty_directory(directory=destination_filepath)
    ub_utility.remove_folder(directory=destination_filepath)

    ub_git_handler.git_setup_directory(directory=destination_filepath, branch=git_branch, url=git_url)

    # Check the folders. If the output (exported files) folder is different than parity (our github dummy folder for comparison)
    # We want to do something
    # If they are the same
    # We can leave it as is and delete the parity folder's contents

    git_fingerprint = ub_utility.build_fingerprint(directory=destination_filepath)
    src_fingerprint = ub_utility.build_fingerprint(directory=source_filepath)
    if git_fingerprint != src_fingerprint:
        ub_utility.loop_helper(directory=source_filepath, filetree=filetree_to_crush)
        for file in filetree_to_crush:
            list_of_queries = list_of_queries + ub_utility.file_to_row(filepath=file, connection_cursor=connection_cursor)
        for i in list_of_queries:
            ub_utility.easy_export_handler(directory=destination_filepath, file=i)
    
        folder_prep(directory_src=source_filepath, directory_dest=destination_filepath)

        try:
            if ub_utility.folder_contents_check(directory=destination_filepath):
                ub_git_handler.git_push_directory(directory=destination_filepath, branch=git_branch, commit_message='Copy from PRD for safety.')
            ub_utility.merge_folders(directory_src=source_filepath, directory_dest=destination_filepath)
            ub_git_handler.git_push_directory(directory=destination_filepath, branch=git_branch, commit_message=git_commit_message)
            ub_utility.empty_directory(directory=destination_filepath)
            ub_utility.empty_directory(directory=source_filepath)
            ub_git_handler.git_setup_directory(directory=source_filepath, url=git_url, branch=git_branch)
            ub_utility.remove_folder(directory=destination_filepath)
            return True
        except Exception as e:
            print(e)
            return False

def folder_prep(directory_src: str, directory_dest: str):
    directory_src = f'./{directory_src}'
    dest = ub_utility.build_fingerprint(directory=directory_dest)
    src = ub_utility.build_fingerprint(directory=directory_src)
    safe_src = ub_utility.standardize_fingerprint(fingerprint_src=src, directory_src=directory_src, directory_dest=directory_dest)

    ub_utility.folder_prune(src=safe_src, dest=dest)
    ub_utility.folder_cleanup(directory=directory_dest)       
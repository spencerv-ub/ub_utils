import pathlib
import json

def setup_config(config_filepath: str, default_config: dict):
    if not (pathlib.Path(config_filepath).exists()):
        set_config(config_filepath=config_filepath, config_dict=default_config)
    
    config_loaded = _read_config(config_filepath=config_filepath)
    
    if config_loaded.keys() != default_config.keys():
        dummy_loaded_keys = config_loaded.keys()
        dummy_default_keys = default_config.keys()

        keys_to_add = dummy_default_keys - dummy_loaded_keys
        for i in keys_to_add:
            config_loaded[i] = default_config[i]
        
        keys_to_remove = dummy_loaded_keys - dummy_default_keys
        for i in keys_to_remove:
            config_loaded.pop(i)
        
        set_config(config_filepath=config_filepath, config_dict=config_loaded)
        config_loaded = _read_config(config_filepath=config_filepath)

    return config_loaded

def _read_config(config_filepath: str):
    with open(config_filepath, 'r') as config_file:
        config_loaded = json.load(fp=config_file)
        return config_loaded

def set_config(config_filepath: str, config_dict: dict):
    json_object = json.dumps(obj=config_dict, indent=4)
    with open(config_filepath, 'w') as config_file:
        config_file.write(json_object)
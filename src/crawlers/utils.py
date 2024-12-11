import os
import yaml
import logging

def load_yaml_config(file_path):
    """
    Load a YAML configuration file.

    Args:
        file_path (str): Path to the YAML file.

    Returns:
        dict: Parsed YAML content as a dictionary.
    """
    with open(file_path, "r") as ymlfile:
        return yaml.safe_load(ymlfile)

def get_current_directory():
    """
    Get the current working directory.

    Returns:
        str: Current working directory path.
    """
    return os.getcwd()

def load_all_configs(config_files):
    """
    Load multiple YAML configurations based on a dictionary of file paths.

    Args:
        config_files (dict): A dictionary where keys are config names and values are relative file paths.

    Returns:
        dict: A dictionary containing loaded configurations keyed by their names.
    """
    current_directory = get_current_directory()
    return {
        key: load_yaml_config(os.path.join(current_directory, path))
        for key, path in config_files.items()
    }

def api_collector_decorator(api_name):
    """
    Decorator to handle logging and exception management for API collectors.
    
    Args:
        api_name (str): The name of the API being collected.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            logging.info(f"-------{api_name} Collection Process Started-------")
            try:
                func(*args, **kwargs)
                logging.info(f"{api_name} Collection Completed Successfully.")
            except Exception as e:
                logging.error(f"{api_name} Collection Failed: {str(e)}")
        return wrapper
    return decorator
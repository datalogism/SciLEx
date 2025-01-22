#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 10 10:57:49 2023

@author: cringwal
         aollagnier

@version: 1.0.1
"""
from collector_collection import CollectCollection
from aggregate import *
import logging
from datetime import datetime
from utils import load_all_configs


# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,  # Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(levelname)s - %(message)s',  # Log message format
    datefmt='%Y-%m-%d %H:%M:%S'  # Date format
)

# Define the configuration files to load
config_files = {
    "main_config": "scilex.config.yml",
    "api_config": "api.config.yml",
}
print("HEY")
# Load configurations
configs = load_all_configs(config_files)

# Access individual configurations
main_config = configs["main_config"]
api_config = configs["api_config"]

print("HEY")
# Extract values from the main configuration
output_dir = main_config['output_dir']
collect = main_config['collect']
aggregate = main_config['aggregate']
years = main_config['years']
keywords = main_config['keywords']
apis = main_config['apis']


# Use the configuration values
if collect:
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

        # saving the config
        with open(os.path.join(output_dir, "config_used.yml"), "w") as f:
            yaml.dump(main_config, f)

    path = output_dir


# Print to check the loaded values
print(f"Output Directory: {output_dir}")
print(f"Collect: {collect}")
print(f"Aggregate: {aggregate}")
print(f"Years: {years}")
print(f"Keywords: {keywords}")
print(f"APIS: {apis}")


if __name__ == "__main__":
    # Log the overall process with timestamps
    logging.info(f"Systematic review search started at {datetime.now()}")
    logging.info("================BEGIN Systematic Review Search================")

    colle_col = CollectCollection(main_config, api_config)
    colle_col.create_collects_jobs()

    logging.info("================END Systematic Review Search================")

    logging.info(f"Systematic review search ended at {datetime.now()}")

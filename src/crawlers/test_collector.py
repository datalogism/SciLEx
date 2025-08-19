#!/usr/bin/env python3
"""
@author: CyprienMD
"""
#
# Test script to test only a specific collector (removing one layer of try which makes debuging more difficult)
#

import logging
import os

import yaml
from aggregate import *
from collectors_old0 import *

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,  # Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(levelname)s - %(message)s",  # Log message format
    datefmt="%Y-%m-%d %H:%M:%S",  # Date format
)


############
# SCRIPT FOR RUNNING COLLECT
############


# Get the current working directory
current_directory = os.getcwd()

# Construct the full path to the YAML file
yaml_file_path = os.path.join(current_directory, "src/scilex.config.yml")

# Load configuration from YAML file
with open(yaml_file_path) as ymlfile:
    config = yaml.safe_load(ymlfile)

# Extract values from the YAML configuration
output_dir = config["output_dir"]
collect = config["collect"]
aggregate = config["aggregate"]
years = config["years"]
keywords = config["keywords"]

if not os.path.isdir(output_dir):
    os.makedirs(output_dir)

path = output_dir

# Print to check the loaded values
print("Output Directory:", output_dir)
print("Collect:", collect)
print("Aggregate:", aggregate)
print("Years:", years)
print("Keywords:", keywords)


filter_params = Filter_param(years, keywords, "")


semschol = SemanticScholar_collector(
    filter_params, 0, path
)  # Initialize Semantic Scholar collector
semschol.runCollect()  # Run the Semantic Scholar data collection

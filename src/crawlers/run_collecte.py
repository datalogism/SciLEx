#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 10 10:57:49 2023

@author: cringwal
         aollagnier

@version: 1.0.1
"""

from collectors_V2  import *
from aggregate import *
import logging
from datetime import datetime
<<<<<<< HEAD
from utils import load_all_configs, api_collector_decorator
=======
import os
>>>>>>> 40b0e51 (Corrected SemanticScholar collector and aggregator + slight adjustments)

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,  # Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(levelname)s - %(message)s',  # Log message format
    datefmt='%Y-%m-%d %H:%M:%S'  # Date format
)

# Define the configuration files to load
config_files = {
    "main_config": "src/scilex.config.yml",
    "api_config": "src/api.config.yml",
}

# Load configurations
configs = load_all_configs(config_files)

# Access individual configurations
main_config = configs["main_config"]
api_config = configs["api_config"]

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
            yaml.dump(config, f)

    path = output_dir


# Print to check the loaded values
print(f"Output Directory: {output_dir}")
print(f"Collect: {collect}")
print(f"Aggregate: {aggregate}")
print(f"Years: {years}")
print(f"Keywords: {keywords}")
print(f"APIS: {apis}")

def run_systematic_review_search():
    """
    Runs the systematic review search process, collecting data from various APIs.
    Logs the progress and any errors encountered during the process.
    """
    logging.info("================BEGIN Systematic Review Search================")
    
    # Log starting the configuration of filter parameters
    logging.info("Initializing Filter Parameters")
    filter_params = Filter_param(years, keywords, "")

    # API-to-collector mapping
    api_collectors = {
        "DBLP": DBLP_collector,
        "Arxiv": Arxiv_collector,
        "Elsevier": Elsevier_collector,
        "IEEE": IEEE_collector,
        "Springer": Springer_collector,
        "Semantic Scholar": SemanticScholar_collector,
        "OpenAlex": OpenAlex_collector,
        "HAL": HAL_collector,
        "ISTEX": Istex_collector,
        "Google Scholar": GoogleScholarCollector,
    }

    # Dynamically run collections with decorators
    for api in apis:
        if api in api_collectors:  # Check if the API is in the mapping
            collector_class = api_collectors[api]  # Get the collector class for the API
            
            @api_collector_decorator(api)
            def collect_data():
                collector = collector_class(filter_params, 0, path)  # Initialize collector
                collector.runCollect()  # Run the data collection

            collect_data()  # Execute the decorated function
        else:
            logging.warning(f"API '{api}' is not recognized and will be skipped.")


    logging.info("================END Systematic Review Search================")

def aggregate_results(output_dir):
    """
    Aggregates results from various collectors and saves them into a CSV file.
    Args:
        output_dir (str): The directory where collected data is stored.
    """
    filter_ = ["relation"]

    # Check if collect_dir exists, otherwise create it
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    collect_dict = os.path.join(output_dir, "collect_dict.json")

    ############################## BEGIN 
    if os.path.exists(collect_dict):
        with open(collect_dict) as json_file:
            data_coll = json.load(json_file)
    else:
        data_coll = {}

    all_data = []
    for k in data_coll.keys():
        coll = data_coll[k]
        current_api = coll["API"]
        print(current_api, "-", k)

        current_API_dir = os.path.join(output_dir, coll["API"])
        current_collect_dir = os.path.join(current_API_dir, str(k))

        if int(coll["complete"]) == 1:
            try:
                for path in os.listdir(current_collect_dir):
                    # Check if current path is a file
                    if os.path.isfile(os.path.join(current_collect_dir, path)):
                        with open(os.path.join(current_collect_dir, path)) as json_file:
                            current_page_data = json.load(json_file)

                        for row in current_page_data["results"]:
                            if (current_api + 'toZoteroFormat') in dir():
                                # Use eval carefully; ideally, avoid it if possible.
                                res = eval(current_api + 'toZoteroFormat(row)')
                                all_data.append(res)
                            else:
                                pass
                                #print("Function not yet implemented for >", current_api)
            except FileNotFoundError:
                print("Directory not found:", current_collect_dir)

    # Create DataFrame and save aggregated results
    df = pd.DataFrame(all_data)
    df_clean = deduplicate(df)
    df_clean.reset_index(drop=True, inplace=True)  # Reset index after deduplication

    # Save to CSV
    df_clean.to_csv(os.path.join(output_dir, "results_aggregated.csv"), sep=";", quotechar='"', quoting=csv.QUOTE_NONNUMERIC)

if __name__ == "__main__":
    # Log the overall process with timestamps
    logging.info(f"Systematic review search started at {datetime.now()}")
    run_systematic_review_search()
    logging.info(f"Systematic review search ended at {datetime.now()}")

    # Aggregation of results after collection
    if aggregate:
        logging.info(f"Aggregation started at {datetime.now()}")
        aggregate_results(output_dir)
        logging.info(f"Aggregation  ended at {datetime.now()}")
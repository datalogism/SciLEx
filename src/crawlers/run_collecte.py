#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 10 10:57:49 2023

@author: cringwal
         aollagnier

@version: 1.0.1
"""

from collectors  import *
from aggregate import *
import yaml
import logging
from datetime import datetime

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,  # Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(levelname)s - %(message)s',  # Log message format
    datefmt='%Y-%m-%d %H:%M:%S'  # Date format
)



############ 
# SCRIPT FOR RUNNING COLLECT
############


# Get the current working directory
current_directory = os.getcwd()

# Construct the full path to the YAML file
yaml_file_path = os.path.join(current_directory, "src/scilex.config.yml")

# Load configuration from YAML file
with open(yaml_file_path, "r") as ymlfile:
    config = yaml.safe_load(ymlfile)

# Extract values from the YAML configuration
output_dir = config['output_dir']
collect = config['collect']
aggregate = config['aggregate']
years = config['years']
keywords = config['keywords'] 

# Use the configuration values
if collect:
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    path = output_dir

# Print to check the loaded values
print("Output Directory:", output_dir)
print("Collect:", collect)
print("Aggregate:", aggregate)
print("Years:", years)
print("Keywords:", keywords)

def run_systematic_review_search():
    """
    Runs the systematic review search process, collecting data from DBLP, Arxiv, Elsevier, IEEE, Springer, Semantic Scholar, OpenAlex, HAL, and ISTEX APIs.
    Logs the progress and any errors encountered during the process.
    """
    logging.info("================BEGIN Systematic Review Search================")
    
    # Log starting the configuration of filter parameters
    logging.info("Initializing Filter Parameters")
    filter_params = Filter_param(years, keywords, "")
    
    # # DBLP collection
    logging.info("-------DBLP Collection Process Started-------")
    dbpl = DBLP_collector(filter_params, 0, path)
    
    try:
        dbpl.runCollect()  # Run the DBLP data collection
        logging.info("DBLP Collection Completed Successfully.")
    except Exception as e:
        logging.error(f"DBLP Collection Failed: {str(e)}")

    # # Arxiv collection
    logging.info("-------Arxiv Collection Process Started-------")
    arxiv = Arxiv_collector(filter_params, 0, path)
    
    try:
        arxiv.runCollect()  # Run the Arxiv data collection
        logging.info("Arxiv Collection Completed Successfully.")
    except Exception as e:
        logging.error(f"Arxiv Collection Failed: {str(e)}")

    # # Elsevier collection
    logging.info("-------Elsevier Collection Process Started-------")
    elsevier = Elsevier_collector(filter_params, 0, path)
    
    try:
        elsevier.runCollect()  # Run the Elsevier data collection
        logging.info("Elsevier Collection Completed Successfully.")
    except Exception as e:
        logging.error(f"Elsevier Collection Failed: {str(e)}")

    # # IEEE collection
    logging.info("-------IEEE Collection Process Started-------")
    ieee = IEEE_collector(filter_params, 0, path)
    
    try:
        ieee.runCollect()  # Run the IEEE data collection
        logging.info("IEEE Collection Completed Successfully.")
    except Exception as e:
        logging.error(f"IEEE Collection Failed: {str(e)}")

    # # Springer collection
    logging.info("-------Springer Collection Process Started-------")
    springer = Springer_collector(filter_params, 0, path)
    
    try:
        springer.runCollect()  # Run the Springer data collection
        logging.info("Springer Collection Completed Successfully.")
    except Exception as e:
        logging.error(f"Springer Collection Failed: {str(e)}")
    
    # # Semantic Scholar collection
    logging.info("-------Semantic Scholar Collection Process Started-------")
    try:
        semschol = SemanticScholar_collector(filter_params, 0, path)  # Initialize Semantic Scholar collector
        semschol.runCollect()  # Run the Semantic Scholar data collection
        logging.info("Semantic Scholar Collection Completed Successfully.")
    except Exception as e:
        logging.error(f"Semantic Scholar Collection Failed: {str(e)}")
    
    # OpenAlex collection
    logging.info("-------OpenAlex Collection Process Started-------")
    try:
        openalex = OpenAlex_collector(filter_params, 0, path)  # Initialize OpenAlex collector
        openalex.runCollect()  # Run the OpenAlex data collection
        logging.info("OpenAlex Collection Completed Successfully.")
    except Exception as e:
        logging.error(f"OpenAlex Collection Failed: {str(e)}")
    
    # HAL collection
    logging.info("-------HAL Collection Process Started-------")
    try:
        hal = HAL_collector(filter_params, 0, path)  # Initialize HAL collector
        hal.runCollect()  # Run the HAL data collection
        logging.info("HAL Collection Completed Successfully.")
    except Exception as e:
        logging.error(f"HAL Collection Failed: {str(e)}")

    # ISTEX collection
    logging.info("-------ISTEX Collection Process Started-------")
    try:
        istex = Istex_collector(filter_params, 0, path)  # Initialize ISTEX collector
        istex.runCollect()  # Run the ISTEX data collection
        logging.info("ISTEX Collection Completed Successfully.")
    except Exception as e:
        logging.error(f"ISTEX Collection Failed: {str(e)}")

    # Google Scholar collection
    logging.info("-------Google Scholar Collection Process Started-------")
    try:
        google_scholar = GoogleScholarCollector(filter_params, 0, path)  # Initialize Google Scholar collector
        google_scholar.runCollect()  # Run the Google Scholar data collection
        logging.info("Google Scholar Collection Completed Successfully.")
    except Exception as e:
        logging.error(f"Google Scholar Collection Failed: {str(e)}")

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
    # if aggregate:
    #     aggregate_results(output_dir)
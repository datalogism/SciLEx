import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

import src.citations.citations_tools as cit_tools
from src.crawlers.aggregate import *
from src.crawlers.utils import load_all_configs

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,  # Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(levelname)s - %(message)s',  # Log message format
    datefmt='%Y-%m-%d %H:%M:%S'  # Date format
)

config_files = {
    "main_config": "scilex.config.yml",
    "api_config": "api.config.yml"
}
print("HEY")
# Load configurations
configs = load_all_configs(config_files)
# Access individual configurations
main_config = configs["main_config"]
api_config = configs["api_config"]

if __name__ == "__main__":
    txt_filters=main_config["aggregate_txt_filter"]
    get_citation=main_config["aggregate_get_citations"]
    dir_collect=os.path.join(main_config['output_dir'], main_config['collect_name'])
    state_path = os.path.join(dir_collect, "state_details.json")
    print("START",state_path)
    all_data = []
    if os.path.isfile(state_path):
        print("HEY")
        with open(state_path, mode="r", encoding="utf-8") as read_file:
            state_details = json.load(read_file)

            #if(state_details["global"]==1):
            for api_ in state_details["details"].keys():
                api_data=state_details["details"][api_]
                for index in api_data["by_query"].keys():
                    KW=api_data["by_query"][index]["keyword"]
                    current_collect_dir=os.path.join(dir_collect,api_,index)
                    if not os.path.exists(current_collect_dir):
                        continue
                    for path in os.listdir(current_collect_dir):
                        # Check if current path is a file
                        if os.path.isfile(os.path.join(current_collect_dir, path)):
                            with open(os.path.join(current_collect_dir, path)) as json_file:
                                current_page_data = json.load(json_file)
                                print("read >",json_file)
                                for row in current_page_data["results"]:
                                    if (api_ + 'toZoteroFormat') in dir():
                                        # Use eval carefully; ideally, avoid it if possible.
                                        res = eval(api_ + 'toZoteroFormat(row)')
                                        if(txt_filters):
                                            found_smth=False
                                            for kw in KW:
                                                if str(res["abstract"]) != "NA":
                                                    if(type(res["abstract"])==dict):
                                                        if(kw in res["title"].lower() or kw in " ".join(res["abstract"]["p"]).lower()):
                                                            found_smth = True
                                                    elif(kw in res["title"].lower() or kw in res["abstract"].lower()):

                                                        found_smth = True
                                                        break
                                                else:
                                                    if(kw in res["title"].lower()):
                                                        found_smth=True
                                                        break
                                            found_smth = True
                                            if found_smth:
                                                all_data.append(res)
                                        else:
                                            all_data.append(res)
                    # Create DataFrame and save aggregated results
            df = pd.DataFrame(all_data)
            df_clean = deduplicate(df)
            df_clean.reset_index(drop=True, inplace=True)  # Reset index after deduplication
            if(get_citation):
                df_clean["extra"] =""
                df_clean["nb_cited"] = ""
                df_clean["nb_citation"] = ""
                for index, row in df_clean.iterrows():
                    doi=str(row['DOI'])
                    print(doi)
                    if(doi and doi!="NA"):
                        citations=cit_tools.getRefandCitFormatted(doi)
                        df_clean.loc[index,["extra"]]=str(citations)
                        nb_=cit_tools.countCitations(citations)
                        df_clean.loc[index,["nb_cited"]]=nb_["nb_cited"]
                        df_clean.loc[index,["nb_citation"]]=nb_["nb_citations"]

            # Save to CSV
            df_clean.to_csv(os.path.join(dir_collect, "FileAggreg.csv"), sep=";", quotechar='"',
                            quoting=csv.QUOTE_NONNUMERIC)







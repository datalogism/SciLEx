import json
import logging
import multiprocessing
import os
import time
from itertools import product

import yaml

from .collectors import *

api_collectors = {
    "DBLP": DBLP_collector,
    "Arxiv": Arxiv_collector,
    "Elsevier": Elsevier_collector,
    "IEEE": IEEE_collector,
    "Springer": Springer_collector,
    "SemanticScholar": SemanticScholar_collector,
    "OpenAlex": OpenAlex_collector,
    "HAL": HAL_collector,
    "ISTEX": Istex_collector,
    "GoogleScholar": GoogleScholarCollector,
}

global lock
lock = multiprocessing.Lock()


class Filter_param:
    def __init__(self, year, keywords, focus):
        # Initialize the parameters
        self.year = year
        # Keywords is now a list of lists to support multiple sets
        self.keywords = keywords
        self.focus = focus

    def get_dict_param(self):
        # Return the instance's dictionary representation
        return self.__dict__

    def get_year(self):
        return self.year

    def get_keywords(self):
        return self.keywords

    def get_focus(self):
        return self.focus


class CollectCollection:
    def __init__(self, main_config, api_config):
        print("INIT COLLECTION")
        self.main_config = main_config
        self.api_config = api_config
        self.state_details = {}
        self.state_details = {"global": -1, "details": {}}
        self.init_collection_collect()

    def job_collect(self, collector):
        res = collector.runCollect()
        self.update_state_details(collector.api_name, str(collector.collectId), res)

    def run_job_collects(self, collect_list):
        for idx in range(len(collect_list)):
            is_last = idx == len(collect_list) - 1
            coll = collect_list[idx]
            data_query = coll["query"]
            collector = api_collectors[coll["api"]]
            api_key = None
            if coll["api"] in self.api_config:
                api_key = self.api_config[coll["api"]]["api_key"]

            repo = self.get_current_repo()
            current_coll = collector(data_query, repo, api_key)
            res = current_coll.runCollect()
            self.update_state_details(
                current_coll.api_name, str(current_coll.collectId), res
            )

            if not is_last:
                time.sleep(2)

    def get_current_repo(self):
        return os.path.join(
            self.main_config["output_dir"], self.main_config["collect_name"]
        )

    def queryCompositor(self):
        """
        Generates all potential combinations of keyword groups, years, APIs, and fields.
            list: A list of dictionaries, each representing a unique combination.
        """

        # Generate all combinations of keywords from two different groups
        keyword_combinations = []
        two_list_k = False
        #### CASE EVERYTHING OK
        if (
            len(self.main_config["keywords"]) == 2
            and len(self.main_config["keywords"][0]) != 0
            and len(self.main_config["keywords"][1]) != 0
        ):
            two_list_k = True
            keyword_combinations = [
                list(pair)
                for pair in product(
                    self.main_config["keywords"][0], self.main_config["keywords"][1]
                )
            ]
        #### CASE ONLY ONE LIST
        elif (
            len(self.main_config["keywords"]) == 2
            and len(self.main_config["keywords"][0]) != 0
            and len(self.main_config["keywords"][1]) == 0
        ) or (
            len(self.main_config["keywords"]) == 1
            and len(self.main_config["keywords"][0]) != 0
        ):
            keyword_combinations = self.main_config["keywords"][0]

        print("==========================")
        print(keyword_combinations)
        print("==========================")
        # Generate all combinations using Cartesian product
        ### ADD LETTER FIELDS
        # combinations = product(keyword_combinations, self.years, self.apis, self.fields)
        combinations = product(
            keyword_combinations, self.main_config["years"], self.main_config["apis"]
        )

        # Create a list of dictionaries with the combinations
        if two_list_k:
            queries = [
                {"keyword": keyword_group, "year": year, "api": api}
                for keyword_group, year, api in combinations
            ]
        else:
            queries = [
                {"keyword": [keyword_group], "year": year, "api": api}
                for keyword_group, year, api in combinations
            ]
        print(queries)
        queries_by_api = {}
        for query in queries:
            if query["api"] not in queries_by_api:
                queries_by_api[query["api"]] = []
            queries_by_api[query["api"]].append(
                {"keyword": query["keyword"], "year": query["year"]}
            )

        return queries_by_api

    def load_state_details(self):
        repo = self.get_current_repo()
        state_path = os.path.join(repo, "state_details.json")
        if os.path.isfile(state_path):
            with open(state_path, encoding="utf-8") as read_file:
                self.state_details = json.load(read_file)
        else:
            logging.warning("Missing state details file")

    def update_state_details(self, api, idx, state_data):
        repo = self.get_current_repo()
        state_path = os.path.join(repo, "state_details.json")
        if os.path.isfile(state_path):
            with open(state_path, encoding="utf-8") as read_file:
                state_orig = json.load(read_file)

                for k in state_data:
                    state_orig["details"][api]["by_query"][str(idx)][k] = state_data[k]

                finished_local = True
                for k in state_orig["details"][api]["by_query"]:
                    q = state_orig["details"][api]["by_query"][k]
                    if q["state"] != 1:
                        finished_local = False

                if finished_local:
                    state_orig["details"][api]["state"] = 1
                else:
                    state_orig["details"][api]["state"] = 0

                finished_global = True
                for api_ in state_orig["details"]:
                    if state_orig["details"][api_]["state"] != 1:
                        finished_global = False

                if finished_global:
                    state_orig["global"] = 1
                else:
                    state_orig["global"] = 0

                self.state_details = state_orig

                with lock:
                    self.save_state_details()
        else:
            logging.warning("Missing state details file")

    def init_state_details(self, queries_by_api):
        """
        Init. state details files used to follow the collect history
        """
        self.state_details["global"] = 0
        self.state_details["details"] = {}
        for api in queries_by_api:
            if api not in self.state_details["details"]:
                self.state_details["details"][api] = {}
                self.state_details["details"][api]["state"] = -1
                self.state_details["details"][api]["by_query"] = {}
                queries = queries_by_api[api]
                for idx in range(len(queries)):
                    self.state_details["details"][api]["by_query"][idx] = {}
                    self.state_details["details"][api]["by_query"][idx]["state"] = -1
                    self.state_details["details"][api]["by_query"][idx][
                        "id_collect"
                    ] = idx
                    self.state_details["details"][api]["by_query"][idx]["last_page"] = 0
                    self.state_details["details"][api]["by_query"][idx]["total_art"] = 0
                    self.state_details["details"][api]["by_query"][idx]["coll_art"] = 0
                    self.state_details["details"][api]["by_query"][idx][
                        "update_date"
                    ] = str(date.today())
                    for k in queries[idx]:
                        if k not in self.state_details["details"][api]["by_query"][idx]:
                            self.state_details["details"][api]["by_query"][idx][k] = (
                                queries[idx][k]
                            )

    def save_state_details(self):
        repo = self.get_current_repo()
        state_path = os.path.join(repo, "state_details.json")
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(self.state_details, f, ensure_ascii=False, indent=4)

    def init_collection_collect(self):
        repo = self.get_current_repo()
        if not os.path.isdir(repo):
            os.makedirs(repo)
            with open(os.path.join(repo, "config_used.yml"), "w") as f:
                yaml.dump(self.main_config, f)
            print("ICI")
            queries_by_api = self.queryCompositor()

            self.init_state_details(queries_by_api)

            self.save_state_details()

        self.load_state_details()

    def create_collects_jobs(self):
        """
        Create the collection of jobs depending of the history and run it in parallel
        """
        jobs_list = []
        n_coll = 0
        if self.state_details["global"] == 0 or self.state_details["global"] == -1:
            for api in self.state_details["details"]:
                current_api_job = []
                if (
                    self.state_details["details"][api]["state"] == -1
                    or self.state_details["details"][api]["state"] == 0
                ):
                    for k in self.state_details["details"][api]["by_query"]:
                        query = self.state_details["details"][api]["by_query"][k]
                        if query["state"] != 1:
                            current_api_job.append({"query": query, "api": api})
                            n_coll += 1
                    if len(current_api_job) > 0:
                        jobs_list.append(current_api_job)
        print("JOB LIST")
        print(jobs_list)
        logging.info("Number of collect to conduct:" + str(n_coll))
        num_cores = multiprocessing.cpu_count()
        if len(jobs_list) < num_cores:
            num_cores = len(jobs_list)
        else:
            num_cores = multiprocessing.cpu_count()

        logging.info("Number of collects to run:" + str(len(jobs_list)))
        logging.info("Number of parallel processes:" + str(num_cores))
        pool = multiprocessing.Pool(processes=num_cores)
        result = pool.map_async(self.run_job_collects, jobs_list)
        result.wait()

        # FIRST ATTEMPT > not ordered by api > could lead to ratelimit overload
        # random.shuffle(jobs_list)
        # coll_coll=[]
        # for job in jobs_list:
        #    data_query=job["query"]
        #    collector=api_collectors[job["api"]]
        #    api_key=None
        #    if(job["api"] in self.api_config.keys()):
        #        api_key = self.api_config[job["api"]]["api_key"]
        #    repo=self.get_current_repo()
        #    coll_coll.append(collector(data_query, repo,api_key))

        # result=pool.map_async(self.job_collect, coll_coll)

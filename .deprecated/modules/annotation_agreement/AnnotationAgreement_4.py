import logging
import random
import string

import pandas as pd
import requests

from src.crawlers.utils import load_all_configs


# Set up logging configuration
def returnExpoVal(data):
    expo = [
        item["tag"].upper()
        for item in data["data"]["tags"]
        if "NB" in item["tag"] and "10" in item["tag"]
    ]
    expo_val = []
    for ex in expo:
        sp = ex.split(":")
        expo_val.append(sp[1])
    return expo_val


def gather_by_dim(anot_res):
    dict_res = {}
    for tag in anot_res:
        splitted = tag.split(":")
        dim = splitted[0]
        val = splitted[1]
        if dim not in dict_res:
            dict_res[dim] = [val]
        else:
            dict_res[dim].append(val)
    return dict_res


def Finished(anot):
    tags = [item["tag"].upper() for item in anot["data"]["tags"]]
    if "DONE" in tags:
        return True
    else:
        return False


def getAnnotAll(anot):
    return set(list(anot["added"]) + list(anot["updated"]) + list(anot["same"]))


def cleanTags(tag_list):
    clean_list = []
    for t in tag_list:
        if ":" in t:
            splitted = t.split(":")
            dim = splitted[0]
            val = splitted[1].strip()
            t2 = t
            if "^" in t:
                splitted = t.split("^")
                t2 = splitted[0]
                if "^0" in t:
                    t2 = t2 + "u\2080"
                elif "^1" in t:
                    t2 = t2 + "u\2081"
                elif "^2" in t:
                    t2 = t2 + "u\2082"
                elif "^3" in t:
                    t2 = t2 + "u\2083"
                elif "^4" in t:
                    t2 = t2 + "u\2084"
                elif "^5" in t:
                    t2 = t2 + "u\2085"
                elif "^6" in t:
                    t2 = t2 + "u\2086"
                elif "^7" in t:
                    t2 = t2 + "u\2087"
                elif "^8" in t:
                    t2 = t2 + "u\2088"
                elif "^9" in t:
                    t2 = t2 + "u\2089"
            elif "10" in t:
                if val == "10°":
                    t2 = dim + ":10" + "u\2080"
                if val == "10⁰":
                    t2 = dim + ":10" + "u\2080"
                if val == "10¹":
                    t2 = dim + ":10" + "u\2081"
                if val == "10²" or val == "10^2":
                    t2 = dim + ":10" + "u\2082"
                if val == "10³" or val == "10^3":
                    t2 = dim + ":10" + "u\2083"
                if val == "10⁴" or val == "10^4":
                    t2 = dim + ":10" + "u\2084"
                if val == "10⁵" or val == "10^5":
                    t2 = dim + ":10" + "u\2085"
                if val == "10⁶" or val == "10^6":
                    t2 = dim + ":10" + "u\2086"
                if val == "10⁷" or val == "10^7":
                    t2 = dim + ":10" + "u\2087"
            else:
                if splitted[1].strip() != "":
                    if (
                        "?" in splitted[1]
                        or "NSP" in splitted[1].upper()
                        or "NONE" in splitted[1].upper()
                    ):
                        t2 = splitted[0] + ":?"
            clean_list.append(t2)
    return set(clean_list)


def compareWithInit(init, annot):
    init_tags_set = cleanTags(
        [
            item["tag"].upper()
            for item in init["data"]["tags"]
            if item["tag"].upper().strip() != ""
        ]
    )
    new_tags_set = cleanTags(
        [
            item["tag"].upper()
            for item in annot["data"]["tags"]
            if item["tag"].upper().strip() != ""
        ]
    )

    # print("len ini >",len(init_tags_set))

    # print("len anot >",len(new_tags_set))
    intersect_set = init_tags_set.intersection(new_tags_set)

    new_tags = new_tags_set.difference(init_tags_set)
    deleted_tags = init_tags_set.difference(new_tags_set)

    # print("--------------------------- NOT CHANGED > ",len(intersect_set))
    new_tags_base = set([t.split(":")[0] for t in new_tags_set])

    updated_tags = []
    deleted2 = []
    added = []

    for t in list(deleted_tags):
        splitted = t.split(":")
        if ":" in t:
            if "?" in splitted[1] and splitted[0].strip() in new_tags_base:
                for new in new_tags_set:
                    if splitted[0].strip() in new:
                        updated_tags.append(new)
            else:
                deleted2.append(t)

    for add in new_tags:
        if add not in updated_tags and "?" not in add:
            added.append(add)

    added = set(added)
    deleted2 = set(deleted2)
    updated_tags = set(updated_tags)

    # print("--------------------------- NEW TAGS > ",len(added))
    # print(added)
    # print("--------------------------- FILLED TAGS > ",len(updated_tags))
    # print(updated_tags)
    # print("--------------------------- DELETED TAGS > ",len(deleted2))
    # print(deleted2)
    return {
        "added": added,
        "updated": updated_tags,
        "deleted": deleted2,
        "same": set(intersect_set),
    }


logging.basicConfig(
    level=logging.INFO,  # Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(levelname)s - %(message)s",  # Log message format
    datefmt="%Y-%m-%d %H:%M:%S",  # Date format
)

# Define the configuration files to load
config_files = {
    "main_config": "../scilex.config.yml",
    "api_config": "../api.config.yml",
}
print("HEY")
# Load configurations
configs = load_all_configs(config_files)

# Access individual configurations
main_config = configs["main_config"]
api_config = configs["api_config"]


def getWriteToken():
    return "".join(
        random.choices(string.ascii_uppercase + string.ascii_lowercase, k=32)
    )


if __name__ == "__main__":
    # Log the overall process with timestamps
    logging.info("================BEGIN Annotation Agreements================")

    user_id = api_config["Zotero"]["user_id"]
    user_role = api_config["Zotero"]["user_mode"]
    api_key = api_config["Zotero"]["api_key"]

    selected_libs = ["datasets_subset", "models_subset", "surveys_subset"]

    # sys.exit()
    print("DONE")
    # as such, all entries are considered to be relevant
    templates_dict = {}

    libs = "/collections"
    lib_list = {}
    lib_ids = {}

    # users / "+str(user_id)+"
    # url="https://api.zotero.org/users/"+str(user_id)+libs
    headers = {"Zotero-API-Key": api_key}
    current_col_key = None
    if user_role == "group":
        url = "https://api.zotero.org/groups/" + str(user_id) + "/collections"
    elif user_role == "user":
        url = "https://api.zotero.org/users/" + str(user_id) + "/collections"
    if user_role == "group":
        url2 = "https://api.zotero.org/groups/" + str(user_id) + "/"
    elif user_role == "user":
        url2 = "https://api.zotero.org/users/" + str(user_id) + "/"
    print("BEFORE")

    found_parent_id = {}
    r_collections = requests.get(url + "?limit=1000?start=0", headers=headers)
    print(">>>>>>>>>>>>>>>>>>>>>>> GET COLLECTIONS DATA")
    if r_collections.status_code == 200:
        data_collections = r_collections.json()
        found_parent = False
        # print(data_collections.keys())

        # nb_res = int(r_items.headers["Total-Results"])
        # prin()
        papers_by_coll = {}
        exits_url = []
        lib = None
        for d in data_collections:
            # print(d["data"])
            if d["data"]["name"] in selected_libs:
                #  print("FOUND current Collection >", d["data"]["name"])
                found_parent_id[d["data"]["key"]] = d["data"]["name"]
                key = d["key"]
                lib_list[d["data"]["name"]] = {"init": d}
                lib_ids[key] = d["data"]["name"]
    print("FOUND PARENTS")
    print(lib_list)
    if len(found_parent_id.keys()) == len(selected_libs):
        # print(found_parent_id)

        print(">>>>>>>>>>>>>>>>>>>>>>> ART BY SUB COLL")
        for d in data_collections:
            z_key = d["key"]

            # print(d["data"].keys())
            if "parentCollection" in d["data"]:
                id_parent = d["data"]["parentCollection"]
                if id_parent in found_parent_id:
                    name_ = d["data"]["name"]
                    print(">", name_)
                    print(found_parent_id[id_parent])
                    anot_name = d["data"]["name"]
                    parent_name = found_parent_id[id_parent]
                    lib_list[parent_name][anot_name] = d
                    lib_ids[z_key] = anot_name
            # sys.exit()
            # if (d["data"]["key"] in found_parent_id.keys()):
            # papers_by_coll[]
            # print("FOUND current Collection >", d["data"]["name"])
    print("==============================")
    print(lib_ids)
    print(">>>>>>>>>>>>>>> GET ARTICLES ITEMS")
    dict_papers = {}
    for lib in lib_list:
        print(">>>>>>", lib)

        dict_papers[lib] = {}
        for coll in lib_list[lib]:
            print(coll)
            dict_papers[lib][coll] = {}

            name = lib_list[lib][coll]["data"]["name"]
            nb_items = lib_list[lib][coll]["meta"]["numItems"]
            key = lib_list[lib][coll]["key"]
            print(name, "-", key)
            dict_papers[lib][coll] = {
                "key": key,
                "nbItems": nb_items,
                "name": name,
                "items": [],
            }
            print(dict_papers[lib][coll])
            start = 0
            apicurl = url + "/" + key + "/items?limit=100&start=" + str(start)
            r_items = requests.get(apicurl, headers=headers)

            if r_items.status_code == 200:
                dict_papers[lib][coll]["items"] = r_items.json()
                print("FOUND ITEMS")
                nb_res = int(r_items.headers["Total-Results"])
                ### CHECK IF IT WORKS BECAUSE I UPDATED IT
                while nb_res > start + 100:
                    print(start)
                    if start != 0:
                        apicurl = (
                            url + "/" + key + "/items?limit=100&start=" + str(start)
                        )
                        r_items = requests.get(apicurl, headers=headers)
                        if r_items.status_code == 200:
                            dict_papers[lib][coll]["items"] = (
                                dict_papers[lib][coll]["items"] + r_items.json()
                            )
                    start += 100

            # sleep(3)
    print(dict_papers.keys())
    print(dict_papers)
    print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
    ################# RECONSTRUCT A DICTIONNARY BASED on COLL > PAPERS > ANNOT
    dict_papers_2 = {}
    expo_all = []
    for k1 in dict_papers:
        print(">", k1)
        if k1 not in dict_papers_2:
            dict_papers_2[k1] = {}
        for k2 in dict_papers[k1]:
            print(">", k2)
            for item in dict_papers[k1][k2]["items"]:
                print(item["data"])
                if "url" in item["data"]:
                    if "contentType" not in item["data"]:
                        url = item["data"]["url"]
                        if url not in dict_papers_2[k1]:
                            dict_papers_2[k1][url] = {}
                        dict_papers_2[k1][url][k2] = item
                        expo_all += returnExpoVal(item)
    # print(dict_papers_2)
    print(">>>>>>>>>>>>>>>>>>>>>> COMPUTE FLEISS KAPPA")

    fleiss_by_type_by_dim = {}
    cohen_by_type_by_dim = {}
    nb_annot = 3

    for k1 in dict_papers_2:
        # k1 = "models_subset"
        fleiss_by_type_by_dim[k1] = {}
        print("============================================ COLLECTION>", k1)
        dim_taken_in_account = []
        updates_by_annot_corrected = {}
        for url in dict_papers_2[k1]:
            nb_annot = len(dict_papers_2[k1][url].keys())
            if nb_annot > 3:
                ok = True
                print("------ url:", url)
                print(dict_papers_2[k1][url].keys())
                init = dict_papers_2[k1][url]["init"]
                updates_by_annot = {}
                for k2 in dict_papers_2[k1][url]:
                    if k2 != "init" and k2 != "resolution":
                        current = dict_papers_2[k1][url][k2]
                        updates_by_annot[k2] = compareWithInit(init, current)
                        done = Finished(current)
                        # if done==False:
                        #    print("NOT FINISHED", k2)
                        #    ok=False

                if ok:
                    print("OK> ", url)
                    for kA in updates_by_annot:
                        if kA not in ["init", "resolution"]:
                            anot = updates_by_annot[kA]
                            anot_added = getAnnotAll(anot)
                            gathered = gather_by_dim(anot_added)
                            ############## WE LOST HERE THE ANNOTATOR
                            if url not in updates_by_annot_corrected:
                                updates_by_annot_corrected[url] = []

                            updates_by_annot_corrected[url].append(gathered)
                            dim_taken_in_account += list(gathered.keys())
            print("DIM TAKEN IN ACCOUNT")
            print(dim_taken_in_account)
            print("UPDATE MADE BY ANNOT")
            print(updates_by_annot_corrected)
            print(">>>>>>>>>>>>>>>>>>> FLEISS KAPPA")
        dim_taken_in_account = set(dim_taken_in_account)
        for dim in dim_taken_in_account:
            matrix_fleiss = []
            ensembles = []
            ensembles_dict = {}

            ############## GET POSSIBLE ENSEMBLES
            for url in updates_by_annot_corrected:
                for anot in updates_by_annot_corrected[url]:
                    if dim in anot:
                        if len(anot[dim]) > 0:
                            anot1 = set(anot[dim])
                            anot_1_txt = ";".join([dim + ":" + t for t in list(anot1)])

                        else:
                            anot_1_txt = dim + ":" + "?"
                    else:
                        anot_1_txt = dim + ":" + "?"

                    if anot_1_txt not in ensembles:
                        ensembles.append(anot_1_txt)
                        ensembles_dict[anot_1_txt] = 0

            if dim == "SOURCE":
                print(ensembles_dict)

            ############## FILL WITH  FLEISS AGGREMENT
            for url in updates_by_annot_corrected:
                current_dict = ensembles_dict.copy()
                for anot in updates_by_annot_corrected[url]:
                    if dim in anot:
                        if len(anot[dim]) > 0:
                            anot1 = set(anot[dim])
                            anot_1_txt = ";".join([dim + ":" + t for t in list(anot1)])

                        else:
                            anot_1_txt = dim + ":" + "?"
                    else:
                        anot_1_txt = dim + ":" + "?"

                    current_dict[anot_1_txt] += 1

                matrix_fleiss.append(list(current_dict.values()))
            if dim == "SOURCE":
                print(current_dict)
            fleiss_by_type_by_dim[k1][dim] = {
                "data": matrix_fleiss,
                "cat": list(current_dict.keys()),
            }

print("COMPUTE AGREEMENT BY DIM TYPE")
from statsmodels.stats import inter_rater as irr

aggr_dim_table = []
for k1 in fleiss_by_type_by_dim:
    print("============================================ COLLECTION>", k1)
    for dim in fleiss_by_type_by_dim[k1]:
        print(dim)
        print(fleiss_by_type_by_dim[k1][dim]["data"])
        print(fleiss_by_type_by_dim[k1][dim]["cat"])
        # agg2 = irr.aggregate_raters(fleiss_by_type_by_dim[k1][dim]["data"])
        res = None
        try:
            res = irr.fleiss_kappa(
                fleiss_by_type_by_dim[k1][dim]["data"], method="fleiss"
            )
            if res < 0:
                det = "Poor agreement"
            if res > 0 and res <= 0.2:
                det = "Slight agreement"
            if res > 0.2 and res <= 0.4:
                det = "Fair agreement"
            if res > 0.4 and res <= 0.6:
                det = "Moderate agreement"
            if res > 0.6 and res <= 0.8:
                det = "Substantial agreement"
            if res >= 0.8:
                det = "Almost perfect agreement"

            row = {"doc_type": k1, "dim": dim, "aggr": res, "detail": det}
            aggr_dim_table.append(row)
        except:
            print("PB with ", dim)

results = pd.DataFrame(aggr_dim_table)
results.to_csv("/user/cringwal/home/Desktop/Fleiss_by_dim_type.csv", index=True)

print(fleiss_by_type_by_dim)

print(">>>>>>>>>>>>>>>>>>>>>> COMPUTE COHEN KAPPA")
from sklearn.metrics import cohen_kappa_score

cohen_by_type_by_paper = {}
nb_annot = 3

couple_dict = {}
for k1 in dict_papers_2:
    print("============================================ COLLECTION>", k1)
    cohen_by_type_by_paper[k1] = {}
    dim_taken_in_account = []
    updates_by_annot_corrected = {}
    for url in dict_papers_2[k1]:
        nb_annot = len(dict_papers_2[k1][url].keys())
        if nb_annot > 3:
            ok = True
            print("------ url:", url)
            init = dict_papers_2[k1][url]["init"]
            updates_by_annot = {}

            for k2 in dict_papers_2[k1][url]:
                if k2 != "init" and k2 != "resolution":
                    current = dict_papers_2[k1][url][k2]
                    updates_by_annot[k2] = compareWithInit(init, current)
                    done = Finished(current)
                    if not done:
                        print("NOT FINISHED")
                        ok = False

            if ok:
                for kA in updates_by_annot:
                    anot = updates_by_annot[kA]
                    anot_added = set(list(anot["updated"]) + list(anot["added"]))
                    gathered = gather_by_dim(anot_added)
                    if kA not in updates_by_annot_corrected:
                        updates_by_annot_corrected[kA] = {}
                    ############## WE LOST HERE THE ANNOTATOR
                    if url not in updates_by_annot_corrected:
                        updates_by_annot_corrected[kA][url] = []

                    updates_by_annot_corrected[kA][url] = gathered
                    dim_taken_in_account += list(gathered.keys())

    dim_taken_in_account = set(dim_taken_in_account)
    values_by_dim = {}
    for dim in dim_taken_in_account:
        values_by_dim[dim] = []

        ############## GET POSSIBLE ENSEMBLES
        for kA in updates_by_annot_corrected:
            for url in updates_by_annot_corrected[kA]:
                anot = updates_by_annot_corrected[kA][url]
                if dim in anot:
                    if len(anot[dim]) > 0:
                        anot1 = set(anot[dim])
                        anot_1_txt = ";".join([dim + ":" + t for t in list(anot1)])

                    else:
                        anot_1_txt = dim + ":" + "?"
                else:
                    anot_1_txt = dim + ":" + "?"
                if anot_1_txt not in values_by_dim[dim]:
                    values_by_dim[dim].append(anot_1_txt)

    ############## FILL WITH  FLEISS AGGREMENT

    dict__byurl_by_annot = {}
    for kA in updates_by_annot_corrected:
        for url in updates_by_annot_corrected[kA]:
            if url not in dict__byurl_by_annot:
                dict__byurl_by_annot[url] = {}
            dict__byurl_by_annot[url][kA] = []
            for dim in dim_taken_in_account:
                if dim in updates_by_annot_corrected[kA][url]:
                    anot = updates_by_annot_corrected[kA][url]
                    if len(anot[dim]) > 0:
                        anot1 = set(anot[dim])
                        anot_1_txt = ";".join([dim + ":" + t for t in list(anot1)])

                    else:
                        anot_1_txt = dim + ":" + "?"

                else:
                    anot_1_txt = dim + ":" + "?"
                idx_chosen = list(values_by_dim[dim]).index(anot_1_txt)

                dict__byurl_by_annot[url][kA].append(idx_chosen)
    for url in dict__byurl_by_annot:
        cohen_by_type_by_paper[k1][url] = {}
        done = []
        for kA1 in dict__byurl_by_annot[url]:
            for kA2 in dict__byurl_by_annot[url]:
                if kA2 != kA1 and (kA1, kA2) not in done and (kA2, kA1) not in done:
                    print(">>>>>>>>>>>>>> AGREMENT BETWEEN " + kA1 + " and " + kA2)
                    if kA1 + "&" + kA2 not in couple_dict:
                        couple_dict[kA1 + "&" + kA2] = kA1 + "&" + kA2
                        couple_dict[kA2 + "&" + kA1] = kA1 + "&" + kA2
                    done.append((kA1, kA2))
                    done.append((kA2, kA1))
                    score = cohen_kappa_score(
                        dict__byurl_by_annot[url][kA1], dict__byurl_by_annot[url][kA2]
                    )
                    cohen_by_type_by_paper[k1][url][kA1 + "&" + kA2] = score

results = pd.DataFrame(cohen_by_type_by_paper)
results.to_csv("/user/cringwal/home/Desktop/Cohen_by_type_papers.csv", index=True)

aggr_all = {"type": {}, "paper": {}, "anot": {}}
init = {"sum": 0, "n": 0}
for k1 in cohen_by_type_by_paper:
    aggr_all["type"][k1] = init.copy()
    for url in cohen_by_type_by_paper[k1]:
        aggr_all["paper"][url] = init.copy()
        for c in cohen_by_type_by_paper[k1][url]:
            score = cohen_by_type_by_paper[k1][url][c]
            c_uniq = couple_dict[c]
            aggr_by_annot = aggr_all["anot"]
            if c_uniq not in aggr_by_annot:
                aggr_by_annot[c_uniq] = init.copy()
            aggr_all["anot"][c_uniq]["n"] += 1
            aggr_all["anot"][c_uniq]["sum"] += score
            aggr_all["paper"][url]["n"] += 1
            aggr_all["paper"][url]["sum"] += score
            aggr_all["type"][k1]["n"] += 1
            aggr_all["type"][k1]["sum"] += score

for k in aggr_all:
    print(">>>>>>>>>>>>>>>>>>>>> LEVEL ", k)
    for k2 in aggr_all[k]:
        mean = aggr_all[k][k2]["sum"] / aggr_all[k][k2]["n"]
        aggr_all[k][k2]["mean"] = mean
        print("- MEAN AGGR FOR ", k2, " > ", mean)

results = pd.DataFrame(aggr_all)
results.to_csv("/user/cringwal/home/Desktop/aggr_all.csv", index=True)
#### basics stats

############# CHECK TYPE BY DIM
stats_all = {
    "act_by_papers": {},
    "act_by_user": {},
    "act_by_type": {},
    "tags_by_type": {},
    "tags_by_dim": {},
    "tags_by_papers": {},
    "ambigus_dim": {},
    "multi_by_dim": {},
    "deleted_tags_by_dim": {},
}
for k1 in dict_papers_2:
    stats_all["act_by_type"][k1] = init.copy()
    stats_all["tags_by_type"][k1] = init.copy()

    for url in dict_papers_2[k1]:
        stats_all["act_by_papers"][url] = init.copy()
        stats_all["tags_by_papers"][url] = init.copy()

        init_data = dict_papers_2[k1][url]["init"]

        for kA in dict_papers_2[k1][url]:
            if kA != "init":
                if kA not in stats_all["act_by_user"]:
                    stats_all["act_by_user"][kA] = init.copy()

                current = dict_papers_2[k1][url][kA]
                anot = compareWithInit(init_data, current)
                nb_act = len(
                    set(
                        list(anot["updated"])
                        + list(anot["added"])
                        + list(anot["deleted"])
                    )
                )
                nb_tags = len(set(list(anot["updated"]) + list(anot["added"])))

                if len(anot["deleted"]) > 0:
                    gathered = gather_by_dim(anot["deleted"])
                    for dim in gathered:
                        if len(gathered[dim]) > 0:
                            print("HEY")
                            if dim not in stats_all["deleted_tags_by_dim"]:
                                stats_all["deleted_tags_by_dim"][dim] = 0
                            stats_all["deleted_tags_by_dim"][dim] += 1

                stats_all["act_by_papers"][url]["n"] += 1
                stats_all["act_by_papers"][url]["sum"] += nb_act
                stats_all["act_by_user"][kA]["n"] += 1
                stats_all["act_by_user"][kA]["sum"] += nb_act
                stats_all["act_by_type"][k1]["n"] += 1
                stats_all["act_by_type"][k1]["sum"] += nb_act

                anot_added = set(list(anot["updated"]) + list(anot["added"]))
                anot_notFILL = set(
                    list(anot["updated"]) + list(anot["added"]) + list(anot["same"])
                )

                gathered = gather_by_dim(anot_added)
                for dim in gathered:
                    if len(gathered[dim]) > 1:
                        if dim not in stats_all["multi_by_dim"]:
                            stats_all["multi_by_dim"][dim] = 0
                        stats_all["multi_by_dim"][dim] += 1
                    for anot in gathered[dim]:
                        if dim not in stats_all["tags_by_dim"]:
                            stats_all["tags_by_dim"][dim] = init.copy()

                        stats_all["tags_by_papers"][url]["n"] += 1
                        stats_all["tags_by_dim"][dim]["n"] += 1
                        stats_all["tags_by_type"][k1]["n"] += 1
                        stats_all["tags_by_papers"][url]["sum"] += 1
                        stats_all["tags_by_dim"][dim]["sum"] += 1
                        stats_all["tags_by_type"][k1]["sum"] += 1

                gathered = gather_by_dim(anot_notFILL)
                for dim in gathered:
                    if (
                        "NSP" in gathered[dim]
                        or "?" in gathered[dim]
                        or "NONE" in gathered[dim]
                        or "None" in gathered[dim]
                        or "none" in gathered[dim]
                    ):
                        if dim not in stats_all["ambigus_dim"]:
                            stats_all["ambigus_dim"][dim] = 0
                        stats_all["ambigus_dim"][dim] += 1

print(stats_all)

#!/usr/bin/env python3
"""
Created on Fri Feb 10 10:57:49 2023

@author: cringwal
         aollagnier

@version: 1.0.1
"""

from pandas.core.dtypes.inference import is_dict_like


def safe_get(obj, key, default=None):
    """Safely get a value from a dictionary-like object, filtering out empty strings."""
    if isinstance(obj, dict) and key in obj and obj[key] != "":
        return obj[key]
    return default


def safe_has_key(obj, key):
    """Safely check if an object has a key."""
    return isinstance(obj, dict) and key in obj


import pandas as pd

############
# FUNCTION FOR AGGREGATIONS OF DATA
############


def isNaN(num):
    return num != num


def getquality(df_row, column_names):
    quality = 0
    for col in column_names:
        if df_row[col] != "NA" and not isNaN(df_row[col]):
            quality += 1
    return quality


def filter_data(df_input, filter_):
    return df_input[df_input["abstract"].str.contains("triple", case=False, na=False)]


def deduplicate(df_input):
    df_output = df_input.copy()
    check_columns = ["DOI", "title"]
    column_names = list(df_output.columns.values)

    for col in check_columns:
        if col in df_output.columns:
            df2 = df_output[df_output[col] != "NA"]
            df2 = df2.groupby([col])[col].count()
            val_duplicate = df2[df2 > 1].index

            if len(val_duplicate) > 0:
                print("FOUND DUPLICATES")
                for val in val_duplicate:
                    myDict = {key: [] for key in column_names}
                    duplicates_temp = df_output[df_output[col] == val]
                    quality_list = []
                    archive_list = []

                    for i in range(len(duplicates_temp)):
                        idx = duplicates_temp.index[i]
                        archive_list.append(str(df_output.loc[idx]["archive"]))
                        qual = getquality(df_output.loc[idx], column_names)
                        quality_list.append(qual)

                        for k in column_names:
                            value = df_output.loc[idx, k]
                            myDict[k].append("NA" if isNaN(value) else value)

                    max_value = max(quality_list)
                    index_value = quality_list.index(max_value)
                    archive_chosen = str(duplicates_temp.iloc[index_value]["archive"])

                    archive_str = ";".join(archive_list)
                    archive_str = archive_str.replace(
                        archive_chosen, archive_chosen + "*"
                    )

                    print("archive retained", archive_chosen)
                    toAdd_temp = duplicates_temp.iloc[index_value].copy()

                    for k in column_names:
                        if isNaN(toAdd_temp[k]):
                            toAdd_temp[k] = "NA"
                        if toAdd_temp[k] == "NA":
                            for val in myDict[k]:
                                if not isNaN(val) and val != "NA":
                                    toAdd_temp[k] = val
                                    break
                    toAdd_temp["archive"] = archive_str
                    df_output = df_output.drop(duplicates_temp.index)
                    df_output = pd.concat(
                        [df_output, toAdd_temp.to_frame().T], ignore_index=True
                    )

    return df_output


def SemanticScholartoZoteroFormat(row):
    # print(">>SemanticScholartoZoteroFormat")
    # bookSection?
    zotero_temp = {
        "title": "NA",
        "publisher": "NA",
        "itemType": "NA",
        "authors": "NA",
        "language": "NA",
        "abstract": "NA",
        "archiveID": "NA",
        "archive": "NA",
        "date": "NA",
        "DOI": "NA",
        "url": "NA",
        "rights": "NA",
        "pages": "NA",
        "journalAbbreviation": "NA",
        "volume": "NA",
        "serie": "NA",
        "issue": "NA",
    }
    zotero_temp["archive"] = "SemanticScholar"
    #### publicationTypes is a list Zotero only take one value

    if (
        "publicationTypes" in row
        and row["publicationTypes"] != ""
        and row["publicationTypes"] is not None
    ):
        if len(row["publicationTypes"]) == 1:
            if row["publicationTypes"][0] == "JournalArticle":
                zotero_temp["itemType"] = "journalArticle"
            elif (
                row["publicationTypes"][0] == "Conference"
                or row["publicationTypes"][0] == "Conferences"
            ):
                zotero_temp["itemType"] = "conferencePaper"
            elif row["publicationTypes"][0] == "Book":
                zotero_temp["itemType"] = "book"

                # print("NEED TO ADD FOLLOWING TYPE >",row["publicationTypes"][0])

        if len(row["publicationTypes"]) > 1:
            if "Book" in row["publicationTypes"]:
                zotero_temp["itemType"] = "book"
            elif "Conference" in row["publicationTypes"]:
                zotero_temp["itemType"] = "conferencePaper"
            elif "JournalArticle" in row["publicationTypes"]:
                zotero_temp["itemType"] = "journalArticle"
            else:
                pass
                # print("NEED TO ADD FOLLOWING TYPES >",row["publicationTypes"])

    if safe_get(row, "venue"):
        venue_type = safe_get(row["venue"], "type")
        venue_name = safe_get(row["venue"], "name")
        if venue_type:
            if venue_type == "journal":
                zotero_temp["itemType"] = "journalArticle"
                if venue_name:
                    zotero_temp["journalAbbreviation"] = venue_name
            if venue_type == "conference":
                zotero_temp["itemType"] = "conferencePaper"
                if venue_name:
                    zotero_temp["conferenceName"] = venue_name

    if safe_get(row, "journal"):
        journal_pages = safe_get(row["journal"], "pages")
        journal_name = safe_get(row["journal"], "name")
        journal_volume = safe_get(row["journal"], "volume")

        if journal_pages:
            zotero_temp["pages"] = journal_pages
            if zotero_temp["itemType"] == "book":
                zotero_temp["itemType"] = "bookSection"
        if zotero_temp["itemType"] == "NA":
            # if the journal field is defined but we dont know the itemType yet (for ex Reviews), we assume it's journal article
            zotero_temp["itemType"] = "journalArticle"
        if journal_name:
            zotero_temp["journalAbbreviation"] = journal_name
        if journal_volume:
            zotero_temp["volume"] = journal_volume

    if zotero_temp["itemType"] == "NA":
        # default to Manuscript type to make sure there is a type, otherwise the push to Zotero doesn't work
        zotero_temp["itemType"] = "Manuscript"

    if row["title"]:
        zotero_temp["title"] = row["title"]
    auth_list = []
    for auth in row["authors"]:
        if auth["name"] != "" and auth["name"] is not None:
            auth_list.append(auth["name"])
    if len(auth_list) > 0:
        zotero_temp["authors"] = ";".join(auth_list)

    if safe_get(row, "abstract"):
        zotero_temp["abstract"] = row["abstract"]

    paper_id = safe_get(row, "paper_id")
    if paper_id:
        zotero_temp["archiveID"] = paper_id

    if safe_get(row, "publication_date"):
        zotero_temp["date"] = row["publication_date"]

    if safe_get(row, "DOI"):
        zotero_temp["DOI"] = row["DOI"]

    if safe_get(row, "url"):
        zotero_temp["url"] = row["url"]

    if safe_get(row, "open_access_pdf"):
        zotero_temp["rights"] = row["open_access_pdf"]

    return zotero_temp


def IstextoZoteroFormat(row):
    zotero_temp = {
        "title": "NA",
        "publisher": "NA",
        "itemType": "NA",
        "authors": "NA",
        "language": "NA",
        "abstract": "NA",
        "archiveID": "NA",
        "archive": "NA",
        "date": "NA",
        "DOI": "NA",
        "url": "NA",
        "rights": "NA",
        "pages": "NA",
        "journalAbbreviation": "NA",
        "volume": "NA",
        "serie": "NA",
        "issue": "NA",
    }
    # Genre pas clair
    zotero_temp["archive"] = "Istex"
    if row["genre"] != "" and len(row["genre"]) == 1:
        if row["genre"][0] == "research-article":
            zotero_temp["itemType"] = "journalArticle"
        if row["genre"][0] == "conference":
            zotero_temp["itemType"] = "conferencePaper"
        if row["genre"][0] == "article":
            zotero_temp["itemType"] = "bookSection"

    if row["title"] != "" and row["title"] is not None:
        zotero_temp["title"] = row["title"]
    auth_list = []
    for auth in row["author"]:
        if auth["name"] != "" and auth["name"] is not None:
            auth_list.append(auth["name"])

    if len(auth_list) > 0:
        zotero_temp["authors"] = ";".join(auth_list)

    # NO ABSTRACT ?
    if "abstract" in row and row["abstract"] != "" and row["abstract"] is not None:
        zotero_temp["abstract"] = row["abstract"]

    if row["arkIstex"] != "" and row["arkIstex"] is not None:
        zotero_temp["archiveID"] = row["arkIstex"]

    if row["publicationDate"] != "" and row["publicationDate"] is not None:
        zotero_temp["date"] = row["publicationDate"]

    if ("doi" in row) and (len(row["doi"]) > 0):
        list_doi = []
        for doi in row["doi"]:
            list_doi.append(doi)
        zotero_temp["DOI"] = ";".join(list_doi)

    if ("language" in row) and (len(row["language"]) == 1):
        zotero_temp["language"] = row["language"][0]
    if "series" in row and len(row["series"].keys()) > 0:
        zotero_temp["series"] = row["series"]["title"]
    if "host" in row:
        if "volume" in row["host"]:
            zotero_temp["volume"] = row["host"]["volume"]

        if "issue" in row["host"]:
            zotero_temp["issue"] = row["host"]["issue"]

        if "title" in row["host"]:
            zotero_temp["journalAbbreviation"] = row["host"]["title"]

        if "pages" in row["host"]:
            if (
                len(row["host"]["pages"].keys()) > 0
                and "fist" in row["host"]["pages"]
                and "last" in row["host"]["pages"]
                and row["host"]["pages"]["first"] != ""
                and row["host"]["pages"]["last"] != ""
            ):
                p = row["host"]["pages"]["first"] + "-" + row["host"]["pages"]["last"]
                zotero_temp["pages"] = p
        if "publisherId" in row["host"] and len(row["host"]["publisherId"]) == 1:
            zotero_temp["publisher"] = row["host"]["publisherId"][0]
    # NO URL ?
    if "url" in row and row["url"] != "" and row["url"] is not None:
        zotero_temp["url"] = row["url"]

    if "accessCondition" in row:
        if row["accessCondition"] != "" and row["accessCondition"] is not None:
            if (
                row["accessCondition"]["contentType"] != ""
                and row["accessCondition"]["contentType"] is not None
            ):
                zotero_temp["rights"] = row["accessCondition"]["contentType"]

    return zotero_temp


def ArxivtoZoteroFormat(row):
    zotero_temp = {
        "title": "NA",
        "publisher": "NA",
        "itemType": "NA",
        "authors": "NA",
        "language": "NA",
        "abstract": "NA",
        "archiveID": "NA",
        "archive": "NA",
        "date": "NA",
        "DOI": "NA",
        "url": "NA",
        "rights": "NA",
        "pages": "NA",
        "journalAbbreviation": "NA",
        "volume": "NA",
        "serie": "NA",
        "issue": "NA",
    }
    # Genre pas clair
    zotero_temp["archive"] = "Arxiv"
    zotero_temp["rights"] = "True"
    zotero_temp["itemType"] = "Manuscript"
    if row["abstract"] != "" and row["abstract"] is not None:
        zotero_temp["abstract"] = row["abstract"]
    if row["authors"] != "" and row["authors"] is not None:
        zotero_temp["authors"] = ";".join(row["authors"])
    if row["doi"] != "" and row["doi"] is not None:
        zotero_temp["DOI"] = row["doi"]
    if row["title"] != "" and row["title"] is not None:
        zotero_temp["title"] = row["title"]
    if row["id"] != "" and row["id"] is not None:
        zotero_temp["archiveID"] = row["id"]
    if row["published"] != "" and row["published"] is not None:
        zotero_temp["date"] = row["published"]
    if row["journal"] != "" and row["journal"] is not None:
        zotero_temp["journalAbbreviation"] = row["journal"]

    return zotero_temp


def DBLPtoZoteroFormat(row):
    zotero_temp = {
        "title": "NA",
        "publisher": "NA",
        "itemType": "NA",
        "authors": "NA",
        "language": "NA",
        "abstract": "NA",
        "archiveID": "NA",
        "archive": "NA",
        "date": "NA",
        "DOI": "NA",
        "url": "NA",
        "rights": "NA",
        "pages": "NA",
        "journalAbbreviation": "NA",
        "volume": "NA",
        "serie": "NA",
        "issue": "NA",
    }
    zotero_temp["archiveID"] = row["@id"]
    row = row["info"]
    if row["title"] != "" and row["title"] is not None:
        zotero_temp["title"] = row["title"]
    zotero_temp["archive"] = "DBLP"
    zotero_temp["title"] = row["title"]
    zotero_temp["date"] = row["year"]
    auth_list = []
    if "authors" in row:
        if type(row["authors"]["author"]) is dict:
            auth_list.append(row["authors"]["author"]["text"])
        else:
            for auth in row["authors"]["author"]:
                if auth["text"] != "" and auth["text"] is not None:
                    auth_list.append(auth["text"])
    # auth_list.append(row["authors"]["author"]["text"] )
    if len(auth_list) > 0:
        zotero_temp["authors"] = ";".join(auth_list)
    if "doi" in row:
        zotero_temp["DOI"] = row["doi"]
    if "pages" in row:
        zotero_temp["pages"] = row["pages"]

    if ("access" in row) and (row["access"] != "" and row["access"] is not None):
        zotero_temp["rights"] = row["access"]
    zotero_temp["url"] = row["url"]

    if row["type"] == "Journal Articles":
        zotero_temp["itemType"] = "journalArticle"
        if "venue" in row:
            zotero_temp["journalAbbreviation"] = row["venue"]
    if row["type"] == "Conference and Workshop Papers":
        zotero_temp["itemType"] = "conferencePaper"
        if "venue" in row:
            zotero_temp["conferenceName"] = row["venue"]
    if row["type"] == "Informal Publications":
        zotero_temp["itemType"] = "Manuscript"
    if row["type"] == "Informal and Other Publications":
        zotero_temp["itemType"] = "Manuscript"

        # print("NEED TO ADD FOLLOWING TYPE >",row["type"][0])
    return zotero_temp


def HALtoZoteroFormat(row):
    zotero_temp = {
        "title": "NA",
        "publisher": "NA",
        "itemType": "NA",
        "authors": "NA",
        "language": "NA",
        "abstract": "NA",
        "archiveID": "NA",
        "archive": "NA",
        "date": "NA",
        "DOI": "NA",
        "url": "NA",
        "rights": "NA",
        "pages": "NA",
        "journalAbbreviation": "NA",
        "volume": "NA",
        "serie": "NA",
        "issue": "NA",
    }
    zotero_temp["archiveID"] = row["halId_s"]
    zotero_temp["archive"] = "HAL"
    zotero_temp["title"] = row["title_s"][0]
    if "abstract_s" in row:
        if row["abstract_s"] != "" and row["abstract_s"] is not None:
            zotero_temp["abstract"] = row["abstract_s"][0]

    if "bookTitle_s" in row:
        zotero_temp["series"] = row["bookTitle_s"]

    if "doiId_id" in row:
        zotero_temp["DOI"] = row["doiId_id"]
    if "conferenceTitle_s" in row:
        zotero_temp["conferenceName"] = row["conferenceTitle_s"]

    if "journalTitle_t" in row:
        zotero_temp["journalAbbreviation"] = row["journalTitle_t"]

    zotero_temp["date"] = row["submittedDateY_i"]
    if row["docType_s"] == "ART":
        zotero_temp["itemType"] = "journalArticle"
        if "venue" in row:
            zotero_temp["journalAbbreviation"] = row["venue"]
    if row["docType_s"] == "COMM":
        zotero_temp["itemType"] = "conferencePaper"
    if row["docType_s"] == "PROCEEDINGS":
        zotero_temp["itemType"] = "conferencePaper"
    if row["docType_s"] == "Informal Publications":
        zotero_temp["itemType"] = "Manuscript"

    return zotero_temp


# Abstract must be recomposed...
def OpenAlextoZoteroFormat(row):
    zotero_temp = {
        "title": "NA",
        "publisher": "NA",
        "itemType": "NA",
        "authors": "NA",
        "language": "NA",
        "abstract": "NA",
        "archiveID": "NA",
        "archive": "NA",
        "date": "NA",
        "DOI": "NA",
        "url": "NA",
        "rights": "NA",
        "pages": "NA",
        "journalAbbreviation": "NA",
        "volume": "NA",
        "serie": "NA",
        "issue": "NA",
    }

    zotero_temp["archive"] = "OpenAlex"
    zotero_temp["archiveID"] = row["id"]
    zotero_temp["DOI"] = row["doi"]
    zotero_temp["title"] = row["title"]
    zotero_temp["date"] = row["publication_date"]

    if (
        row["open_access"] != ""
        and row["open_access"] is not None
        and "is_oa" in row["open_access"]
    ):
        zotero_temp["rights"] = row["open_access"]["is_oa"]

    auth_list = []
    for auth in row["authorships"]:
        # Maybe not null !
        if "display_name" in auth["author"]:
            if (
                auth["author"]["display_name"] != ""
                and auth["author"]["display_name"] is not None
            ):
                auth_list.append(auth["author"]["display_name"])
        if len(auth_list) > 0:
            zotero_temp["authors"] = ";".join(auth_list)

    if row["type"] == "journal-article":
        zotero_temp["itemType"] = "journalArticle"
    if row["type"] == "article":
        zotero_temp["itemType"] = "journalArticle"
    if row["type"] == "book":
        zotero_temp["itemType"] = "book"
    if row["type"] == "book-chapter":
        zotero_temp["itemType"] = "bookSection"
    if row["type"] == "proceedings-article":
        zotero_temp["itemType"] = "conferencePaper"
    # if row["type"] == "preprint":

    # print("NEED TO ADD FOLLOWING TYPE >",row["type"])

    if "biblio" in row:
        if row["biblio"]["volume"] and row["biblio"]["volume"] != "":
            zotero_temp["volume"] = row["biblio"]["volume"]
        if row["biblio"]["issue"] and row["biblio"]["issue"] != "":
            zotero_temp["issue"] = row["biblio"]["issue"]
        if (
            row["biblio"]["first_page"]
            and row["biblio"]["first_page"] != ""
            and row["biblio"]["last_page"]
            and row["biblio"]["last_page"] != ""
        ):
            zotero_temp["pages"] = (
                row["biblio"]["first_page"] + "-" + row["biblio"]["last_page"]
            )

    if "host_venue" in row:
        if "publisher" in row["host_venue"]:
            row["publisher"] = row["host_venue"]["publisher"]

        if "display_name" in row["host_venue"] and "type" in row["host_venue"]:
            if row["host_venue"]["type"] == "conference":
                zotero_temp["itemType"] = "conferencePaper"
                zotero_temp["conferenceName"] = row["host_venue"]["display_name"]

            elif row["host_venue"]["type"] == "journal":
                zotero_temp["journalAbbreviation"] = row["host_venue"]["display_name"]
                zotero_temp["itemType"] = "journalArticle"
            else:
                pass

            # print("NEED TO ADD FOLLOWING TYPE >",row["host_venue"]["type"])
    return zotero_temp


def IEEEtoZoteroFormat(row):
    zotero_temp = {
        "title": "NA",
        "publisher": "NA",
        "itemType": "NA",
        "authors": "NA",
        "language": "NA",
        "abstract": "NA",
        "archiveID": "NA",
        "archive": "NA",
        "date": "NA",
        "DOI": "NA",
        "url": "NA",
        "rights": "NA",
        "pages": "NA",
        "journalAbbreviation": "NA",
        "volume": "NA",
        "serie": "NA",
        "issue": "NA",
    }

    zotero_temp["archive"] = "IEEE"
    zotero_temp["archiveID"] = row["article_number"]

    if (
        "publication_date" in row
        and row["publication_date"] != ""
        and row["publication_date"] is not None
    ):
        zotero_temp["date"] = row["publication_date"]
    elif (
        "publication_year" in row
        and row["publication_year"] != ""
        and row["publication_year"] is not None
    ):
        zotero_temp["date"] = row["publication_year"]
    if row["title"] != "" and row["title"] is not None:
        zotero_temp["title"] = row["title"]
    if row["abstract"] != "" and row["abstract"] is not None:
        zotero_temp["abstract"] = row["abstract"]
    if ("html_url" in row) and (row["html_url"] != "" and row["html_url"] is not None):
        zotero_temp["url"] = row["html_url"]
    if row["access_type"] != "" and row["access_type"] is not None:
        zotero_temp["rights"] = row["access_type"]
    if "doi" in row:
        zotero_temp["DOI"] = row["doi"]
    if "publisher" in row:
        zotero_temp["publisher"] = row["publisher"]
    if ("volume" in row) and (row["volume"] != "" and row["volume"] is not None):
        zotero_temp["volume"] = row["volume"]
    if "issue" in row and row["issue"] != "" and row["issue"] is not None:
        zotero_temp["issue"] = row["issue"]

    if "publication_title" in row:
        if row["publication_title"] != "" and row["publication_title"] is not None:
            zotero_temp["journalAbbreviation"] = row["publication_title"]
    auth_list = []
    if isinstance(row["authors"], list):
        for auth in row["authors"]:
            if auth["full_name"] != "" and auth["full_name"] is not None:
                auth_list.append(auth["full_name"])
            if len(auth_list) > 0:
                zotero_temp["authors"] = ";".join(auth_list)
    elif is_dict_like(row["authors"]):
        for auth in row["authors"]["authors"]:
            if auth["full_name"] != "" and auth["full_name"] is not None:
                auth_list.append(auth["full_name"])
            if len(auth_list) > 0:
                zotero_temp["authors"] = ";".join(auth_list)
    if "start_page" in row:
        if (
            row["start_page"]
            and row["start_page"] != ""
            and row["end_page"]
            and row["end_page"] != ""
        ):
            zotero_temp["pages"] = row["start_page"] + "-" + row["end_page"]
    if row["content_type"] == "Journals":
        zotero_temp["itemType"] = "journalArticle"
    if row["content_type"] == "Conferences":
        zotero_temp["itemType"] = "conferencePaper"

        # print("NEED TO ADD FOLLOWING TYPE >",row["content_type"])

    return zotero_temp


def SpringertoZoteroFormat(row):
    zotero_temp = {
        "title": "NA",
        "publisher": "NA",
        "itemType": "NA",
        "authors": "NA",
        "language": "NA",
        "abstract": "NA",
        "archiveID": "NA",
        "archive": "NA",
        "date": "NA",
        "DOI": "NA",
        "url": "NA",
        "rights": "NA",
        "pages": "NA",
        "journalAbbreviation": "NA",
        "volume": "NA",
        "serie": "NA",
        "issue": "NA",
    }

    zotero_temp["archive"] = "Springer"
    zotero_temp["archiveID"] = row["identifier"]

    if (
        "publicationDate" in row
        and row["publicationDate"] != ""
        and row["publicationDate"] is not None
    ):
        zotero_temp["date"] = row["publicationDate"]
    if row["title"] != "" and row["title"] is not None:
        zotero_temp["title"] = row["title"]
    if row["abstract"] != "" and row["abstract"] is not None:
        zotero_temp["abstract"] = row["abstract"]
    # if(row["url"][""]!="" and row["html_url"] is not None):
    #   zotero_temp["url"]=row["html_url"]
    if "openaccess" in row:
        if row["openaccess"] != "" and row["openaccess"] is not None:
            zotero_temp["rights"] = row["openaccess"]
    if "doi" in row:
        zotero_temp["DOI"] = row["doi"]
    if "publisher" in row:
        zotero_temp["publisher"] = row["publisher"]
    # if("volume" in row.keys()):
    #   if(row["volume"]!="" and row["volume"] is not None):
    #      zotero_temp["volume"]=row["volume"]
    # if("issue" in row.keys() and row["issue"]!="" and row["issue"] is not None):
    #   zotero_temp["issue"]=row["issue"]

    if row["publicationName"] != "" and row["publicationName"] is not None:
        zotero_temp["journalAbbreviation"] = row["publicationName"]
    auth_list = []
    for auth in row["creators"]:
        if auth["creator"] != "" and auth["creator"] is not None:
            auth_list.append(auth["creator"])
        if len(auth_list) > 0:
            zotero_temp["authors"] = ";".join(auth_list)

    if "startingPage" in row and "endingPage" in row:
        if row["startingPage"] != "" and row["endingPage"] != "":
            zotero_temp["pages"] = row["startingPage"] + "-" + row["endingPage"]

    if "Conference" in row["contentType"]:
        zotero_temp["itemType"] = "conferencePaper"
    elif "Article" in row["contentType"]:
        zotero_temp["itemType"] = "journalArticle"
    elif "Chapter" in row["contentType"]:
        zotero_temp["itemType"] = "bookSection"
    # if("Conference" in  row["content_type"]):
    #    zotero_temp["itemType"]="conferencePaper"
    # elif("Article" in  row["content_type"]):
    #     zotero_temp["itemType"]="journalArticle"
    # elif("Chapter" in  row["content_type"]):
    #     zotero_temp["itemType"]="bookSection"

    else:
        pass
        # print("NEED TO ADD FOLLOWING TYPE >",row["content_type"])

    return zotero_temp


def ElseviertoZoteroFormat(row):
    zotero_temp = {
        "title": "NA",
        "publisher": "NA",
        "itemType": "NA",
        "authors": "NA",
        "language": "NA",
        "abstract": "NA",
        "archiveID": "NA",
        "archive": "NA",
        "date": "NA",
        "DOI": "NA",
        "url": "NA",
        "rights": "NA",
        "pages": "NA",
        "journalAbbreviation": "NA",
        "volume": "NA",
        "serie": "NA",
        "issue": "NA",
    }

    zotero_temp["archive"] = "Elsevier"
    if "source-id" in row:
        zotero_temp["archiveID"] = row["source-id"]

    if (
        "prism:coverDate" in row
        and row["prism:coverDate"] != ""
        and row["prism:coverDate"] is not None
    ):
        zotero_temp["date"] = row["prism:coverDate"]
    if "dc:title" in row and row["dc:title"] != "" and row["dc:title"] is not None:
        zotero_temp["title"] = row["dc:title"]
    #  if(row["abstract"]!="" and row["abstract"] is not None):
    #     zotero_temp["abstract"]=row["abstract"]
    if row["prism:url"] != "" and row["prism:url"] is not None:
        zotero_temp["url"] = row["prism:url"]
    if row["openaccess"] != "" and row["openaccess"] is not None:
        zotero_temp["rights"] = row["openaccess"]
    if "prism:doi" in row:
        zotero_temp["DOI"] = row["prism:doi"]
    if "publisher" in row:
        zotero_temp["publisher"] = row["publisher"]
    if "prism:volume" in row:
        if row["prism:volume"] != "" and row["prism:volume"] is not None:
            zotero_temp["volume"] = row["prism:volume"]
    if (
        "prism:issueIdentifier" in row
        and row["prism:issueIdentifier"] != ""
        and row["prism:issueIdentifier"] is not None
    ):
        zotero_temp["issue"] = row["prism:issueIdentifier"]

    if (
        "prism:publicationName" in row
        and row["prism:publicationName"] != ""
        and row["prism:publicationName"] is not None
    ):
        zotero_temp["journalAbbreviation"] = row["prism:publicationName"]
    # auth_list=[]
    # for auth in row["creators"]:
    #    if(auth["creator"]!="" and auth["creator"] is not None):
    #         auth_list.append( auth["creator"])
    #    if(len(auth_list)>0):
    #     zotero_temp["authors"]=";".join(auth_list)
    if ("dc:creator" in row) and (row["dc:creator"] and row["dc:creator"] != ""):
        zotero_temp["authors"] = row["dc:creator"]
    if row["prism:pageRange"] and row["prism:pageRange"] != "":
        zotero_temp["pages"] = row["prism:pageRange"]

    if (
        "subtypeDescription" in row
        and row["subtypeDescription"] is not None
        and row["subtypeDescription"] != ""
    ):
        if "Conference" in row["subtypeDescription"]:
            zotero_temp["itemType"] = "conferencePaper"
        elif "Article" in row["subtypeDescription"]:
            zotero_temp["itemType"] = "journalArticle"
        elif "Chapter" in row["subtypeDescription"]:
            zotero_temp["itemType"] = "bookSection"
        else:
            pass
            # print("NEED TO ADD FOLLOWING TYPE >",row["subtypeDescription"])

    return zotero_temp

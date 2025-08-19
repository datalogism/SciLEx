import requests
from ratelimit import limits, sleep_and_retry

api_citations = "https://opencitations.net/index/coci/api/v1/citations/"
api_references = "https://opencitations.net/index/coci/api/v1/references/"


@sleep_and_retry
@limits(calls=10, period=1)
def getCitations(doi):
    print("REQUEST citations -doi :", doi)
    resp = None
    try:
        resp = requests.get(api_citations + doi)
    except:
        print("PB AFTER REQUEST")
    return resp


@sleep_and_retry
@limits(calls=10, period=1)
def getReferences(doi):
    print("REQUEST ref -doi :", doi)
    resp = None
    try:
        resp = requests.get(api_references + doi)
    except:
        print("PB AFTER REQUEST")
    return resp


def getRefandCitFormatted(doi_str):
    # doi_str="10.18653/v1/2022.findings-acl.67"
    citation = getCitations(doi_str.replace("https://doi.org/", ""))
    reference = getReferences(doi_str.replace("https://doi.org/", ""))
    citations = {"citing": [], "cited": []}
    try:
        resp_cit = citation.json()
        if len(resp_cit) > 0:
            for cit in resp_cit:
                citations["citing"].append(cit["citing"])

    except:
        print("ERROR API opencitations")

        return citations
        # print(citations)

    try:
        resp_ref = reference.json()
        if len(resp_ref) > 0:
            for ref in resp_ref:
                citations["cited"].append(ref["cited"])

            print("-", len(citations["cited"]), " ref")
    except:
        print("ERROR API REF")

        return citations

    return citations


def countCitations(citations):
    return {
        "nb_citations": len(citations["citing"]),
        "nb_cited": len(citations["cited"]),
    }

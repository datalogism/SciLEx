"""First/last author h-index via Semantic Scholar batch endpoints (mocked)."""

from unittest.mock import MagicMock

import pandas as pd

from scilex.pipeline.author_metrics import (
    enrich_with_author_hindex,
    extract_first_last_author_ids,
)


def test_extract_first_last():
    record = {"authors": [{"authorId": "1"}, {"authorId": "2"}, {"authorId": "3"}]}
    assert extract_first_last_author_ids(record) == ("1", "3")
    assert extract_first_last_author_ids(None) == (None, None)


def test_enrich_end_to_end():
    session = MagicMock()

    def post(url, params=None, json=None, headers=None, timeout=None):
        response = MagicMock()
        if "/paper/batch" in url:
            response.json.return_value = [
                {"authors": [{"authorId": "A"}, {"authorId": "B"}]},
                None,
            ]
        else:
            assert json["ids"] == ["A", "B"]
            response.json.return_value = [{"hIndex": 12}, {"hIndex": 30}]
        return response

    session.post.side_effect = post
    df = pd.DataFrame({"DOI": ["10.1/a", "10.1/b", "NA"]})
    out = enrich_with_author_hindex(df, api_key="k", session=session, pause_seconds=0)
    assert out["first_author_hindex"].tolist()[0] == 12
    assert out["last_author_hindex"].tolist()[0] == 30
    assert out["first_author_hindex"].isna().tolist() == [False, True, True]
    assert session.post.call_args.kwargs["headers"] == {"x-api-key": "k"}

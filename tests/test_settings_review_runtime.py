"""Regression tests: collection snapshots and per-job VPN configuration."""

from unittest import mock

import pytest
import yaml

import scilex.crawlers.collector_collection as collector_collection
from scilex.config import SciLExConfig
from scilex.crawlers.collectors.base import API_collector
from scilex.vpn import rotator


@pytest.fixture(autouse=True)
def fresh_rotator(monkeypatch):
    monkeypatch.setattr(rotator, "_instance", None)
    monkeypatch.setattr(rotator, "_instance_config", None)


# ---------------------------------------------------------------------------
# 8. from_collection never merges scilex.advanced.yml into a snapshot
# ---------------------------------------------------------------------------


def test_from_collection_does_not_merge_advanced_into_snapshot(tmp_path):
    config_dir = tmp_path / "conf"
    config_dir.mkdir()
    (config_dir / "scilex.advanced.yml").write_text(
        yaml.safe_dump(
            {"quality_filters": {"max_papers": 5}, "extra_option": "from-advanced"}
        )
    )
    snapshot = {
        "collect_name": "c",
        "keywords": [["a"]],
        "years": [2020],
        "apis": ["OpenAlex"],
        "quality_filters": {"max_papers": 100},
    }
    collect_dir = tmp_path / "out" / "c"
    collect_dir.mkdir(parents=True)
    (collect_dir / "config_used.yml").write_text(yaml.safe_dump(snapshot))

    config = SciLExConfig.from_collection(str(collect_dir), config_dir=config_dir)

    assert config.main == snapshot


# ---------------------------------------------------------------------------
# 9. The VPN configuration comes from the job, not from a frozen singleton
# ---------------------------------------------------------------------------


def test_rotator_is_rebuilt_when_configuration_changes():
    first = rotator.get_vpn_rotator({"enabled": False, "max_rotations_per_session": 3})
    assert (
        rotator.get_vpn_rotator({"enabled": False, "max_rotations_per_session": 3})
        is first
    )
    second = rotator.get_vpn_rotator({"enabled": False, "max_rotations_per_session": 7})
    assert second is not first
    assert second.max_rotations == 7


def test_rotator_without_configuration_is_disabled():
    assert rotator.get_vpn_rotator().should_rotate("OpenAlex") is False
    assert rotator.get_vpn_rotator("not a mapping").should_rotate("OpenAlex") is False


def test_rotator_never_raises_on_bad_configuration():
    with mock.patch.object(
        rotator.VPNRotator, "__init__", side_effect=[ValueError("boom"), None]
    ):
        assert isinstance(
            rotator.get_vpn_rotator({"enabled": True}), rotator.VPNRotator
        )


def test_collector_rotation_uses_its_own_vpn_config(tmp_path):
    collector = API_collector(
        {
            "year": 2020,
            "keyword": ["a"],
            "id_collect": 0,
            "total_art": 0,
            "last_page": 0,
            "coll_art": 0,
            "state": 0,
        },
        str(tmp_path),
        None,
    )
    assert collector.vpn_config == {}
    collector.api_name = "OpenAlex"
    collector.vpn_config = {"enabled": False, "marker": 1}
    with mock.patch("scilex.vpn.rotator.get_vpn_rotator") as get_rotator:
        get_rotator.return_value.should_rotate.return_value = False
        assert collector._try_vpn_rotation(429, 1) is False
    get_rotator.assert_called_once_with({"enabled": False, "marker": 1})


def _vpn_seen_by_worker(main_config_extra, api_config=None):
    """Run CollectCollection with a recording worker; return the vpn_config it got."""
    seen = {}

    def recording_worker(*args, **kwargs):
        seen["vpn_config"] = kwargs.get(
            "vpn_config", args[7] if len(args) > 7 else None
        )

    main_config = {
        "collect_name": "c",
        "output_dir": main_config_extra.pop("output_dir"),
        "keywords": [["a"]],
        "years": [2020],
        "apis": ["OpenAlex"],
        **main_config_extra,
    }
    with mock.patch.object(
        collector_collection, "_run_job_collects_worker", recording_worker
    ):
        collection = collector_collection.CollectCollection(
            main_config, api_config or {}
        )
        collection.create_collects_jobs()
    return seen["vpn_config"]


def test_job_with_vpn_block_passes_it_to_the_workers(tmp_path):
    vpn = {"enabled": True, "rotate_on_rate_limit": ["OpenAlex"]}
    seen = _vpn_seen_by_worker({"output_dir": str(tmp_path), "vpn": vpn})
    assert seen == vpn


def test_job_without_vpn_block_has_rotation_disabled(tmp_path):
    seen = _vpn_seen_by_worker({"output_dir": str(tmp_path)})
    assert seen == {}
    assert rotator.get_vpn_rotator(seen).should_rotate("OpenAlex") is False


def test_worker_hands_vpn_config_to_the_collector(tmp_path):
    from queue import Queue

    received = {}

    class Fake:
        def __init__(self, *args):
            pass

        def load_rate_limit_from_config(self, rate_limits=None):
            pass

        def runCollect(self):
            received["vpn_config"] = self.vpn_config
            return {"coll_art": 0}

        def close_session(self):
            pass

    query = {"id_collect": 0, "keyword": ["a"], "year": 2020}
    with mock.patch.dict(collector_collection.api_collectors, {"FakeAPI": Fake}):
        collector_collection._run_job_collects_worker(
            "FakeAPI",
            [{"query": query, "api": "FakeAPI"}],
            {},
            str(tmp_path),
            "c",
            Queue(),
            vpn_config={"enabled": True},
        )
    assert received["vpn_config"] == {"enabled": True}

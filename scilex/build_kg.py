#!/usr/bin/env python3
"""Build the knowledge graph of a review with the scilex-lpwc-ap application profile.

The papers come from the review's Zotero library / collection (chosen in the
desktop app, ``zotero_source.yml``: a collection, its sub-collections, or a
whole user or group library; by default the collection named after the review),
exported by Zotero as BibLaTeX (tags with the review coding, Extra with the
citation lists), or from a BibLaTeX file given with ``--bib``. The coding
dimensions come from the review's ``annotation_grid.csv``.

Writes ``{output_dir}/{collect_name}/kg/<review>.ttl``, the BibLaTeX export it
was built from and, unless ``--no-validate``, a SHACL report.

An ORCID iD is required (``--orcid``, else the one saved by the desktop app):
it is written as the creator of the graph.

Needs the optional dependencies: ``pip install 'scilex[kg]'``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scilex.kg.build import KgDependencyError
from scilex.kg.profile import ProfileError, read_version
from scilex.logging_config import setup_logging
from scilex.pipeline_utils import resolve_collect_dir
from scilex.settings.cli import (
    add_config_arguments,
    apply_config_arguments,
    exit_on_config_error,
)
from scilex.settings.loader import find_config_file
from scilex.settings.resolve import resolve_legacy_configs
from scilex.user_profile import InvalidOrcidError, UserProfile, orcid_uri

logger = logging.getLogger(__name__)


def review_folder(config_arg: str | None) -> Path:
    """Folder of the review's ``scilex.yml`` (the current folder for a legacy config)."""
    found = find_config_file(config_arg)
    return found.resolve().parent if found else Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--bib", type=Path, metavar="FILE",
        help="BibLaTeX export to map instead of exporting from Zotero",
    )
    parser.add_argument("--orcid", help="your ORCID iD (default: the one saved by the app)")
    parser.add_argument("--base-iri", help="base IRI of the review's resources")
    parser.add_argument("--output-dir", type=Path, metavar="DIR", help="where to write")
    parser.add_argument(
        "--no-validate", action="store_true", help="skip the SHACL validation"
    )
    add_config_arguments(parser)
    return parser


@exit_on_config_error
def main(argv: list[str] | None = None) -> int:
    """Run the command."""
    from scilex.gui.services.kg_export import export_knowledge_graph
    from scilex.gui.services.zotero_library import ZoteroNotConfiguredError

    args = build_parser().parse_args(argv)
    apply_config_arguments(args)
    setup_logging()

    try:
        creator = orcid_uri(args.orcid) if args.orcid else UserProfile.load().orcid_uri
    except InvalidOrcidError as error:
        logger.error("%s", error)
        return 1
    if not creator:
        logger.error(
            "An ORCID iD is required: pass --orcid, or set it in the desktop app."
        )
        return 1

    main_config, api_config = resolve_legacy_configs()
    name = main_config.get("collect_name") or "review"
    output_dir = args.output_dir or Path(resolve_collect_dir(main_config)) / "kg"
    base_iri = args.base_iri
    if base_iri and not base_iri.endswith("/"):
        base_iri += "/"

    profile = read_version()
    if not profile:
        logger.error("No application profile in scilex/kg/ap (run: python -m scilex.kg.sync_profile)")
        return 1
    logger.info(
        "Application profile %s (%s @ %s)",
        profile.get("version_info"), profile.get("ref"), profile.get("commit", "")[:10],
    )

    try:
        result = export_knowledge_graph(
            keys=api_config,
            folder=review_folder(args.config),
            review_name=name,
            output_dir=output_dir,
            creator=creator,
            base_iri=base_iri,
            run_validation=not args.no_validate,
            bib=args.bib,
            progress=lambda percent, message: logger.info("%s", message),
        )
    except (
        KgDependencyError,
        ProfileError,
        LookupError,
        ConnectionError,
        ValueError,
        ZoteroNotConfiguredError,
    ) as error:
        logger.error("%s", error)
        return 1

    report = result.report
    logger.info(
        "%d papers -> %d triples in %s (%d SciLEx automation tags left out, "
        "%d citation notes cleaned)",
        report.papers, report.triples, report.output, report.dropped_tags, report.notes_cleaned,
    )
    if report.conforms is True:
        logger.info("SHACL: the graph conforms to the profile")
    elif report.conforms is False:
        logger.warning("SHACL: violations, see %s", report.validation_report.with_suffix(".txt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Entry point for `python -m scilex`."""

import sys

COMMANDS = {
    "collect": "scilex.run_collection",
    "aggregate": "scilex.aggregate_collect",
    "status": "scilex.collect_status",
    "enrich": "scilex.enrich_with_pwc",
    "export-bibtex": "scilex.export_to_bibtex",
    "push-zotero": "scilex.push_to_zotero",
}
# Commands whose ``main(argv)`` returns an exit code.
ARGV_COMMANDS = {
    "init": ("scilex.init_templates", "main"),
    "config": ("scilex.settings.cli", "config_main"),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m scilex <command> [options]")
        print()
        print("Commands:")
        print("  collect        Collect papers from academic APIs")
        print("  status         Show collection completeness (keywords, APIs, years)")
        print("  aggregate      Deduplicate, filter, and rank papers")
        print("  enrich         Enrich papers with Papers with Code metadata")
        print("  export-bibtex  Export aggregated papers to BibTeX")
        print("  push-zotero    Push aggregated papers to Zotero")
        print("  init           Create scilex.yml (template, questions or skeleton)")
        print("  config         show | check | migrate the configuration")
        sys.exit(0)

    command = sys.argv[1]
    if command in ARGV_COMMANDS:
        from importlib import import_module

        module_name, function_name = ARGV_COMMANDS[command]
        function = getattr(import_module(module_name), function_name)
        sys.exit(function(sys.argv[2:]))
    if command not in COMMANDS:
        print(f"Unknown command: {command}")
        print(f"Available commands: {', '.join([*COMMANDS, *ARGV_COMMANDS])}")
        sys.exit(1)

    # Remove the subcommand from argv so the module sees its own args
    sys.argv = [sys.argv[0]] + sys.argv[2:]

    from importlib import import_module

    module = import_module(COMMANDS[command])
    module.main()


if __name__ == "__main__":
    main()

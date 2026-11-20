"""Pipeline entry point.

Examples:
    python scripts/run_pipeline.py --step info
    python scripts/run_pipeline.py --step collect --limit 10
    python scripts/run_pipeline.py --step collect
"""

import argparse

from semnav_gp.helpers.config import get_settings
from semnav_gp.helpers.logging import get_logger, setup_logging

STEPS = ["info", "collect", "gold", "graph", "index", "cues", "stats", "all"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SemNav-GP data pipeline")
    parser.add_argument("--step", choices=STEPS, default="info", help="pipeline step to run")
    parser.add_argument("--limit", type=int, default=None, help="process only the first N instances")
    parser.add_argument("--instances", nargs="*", default=None, help="explicit instance_ids to process")
    parser.add_argument("--overwrite", action="store_true", help="recompute outputs that already exist")
    return parser.parse_args()


def run_info() -> None:
    settings = get_settings()
    settings.ensure_dirs()
    log = get_logger("info")
    log.info("DATA_DIR      = %s", settings.DATA_DIR)
    log.info("repos_dir     = %s", settings.repos_dir)
    log.info("processed_dir = %s", settings.processed_dir)
    log.info("dataset       = %s [%s]", settings.DATASET_NAME, settings.DATASET_SPLIT)


def main() -> None:
    args = parse_args()
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL, settings.logs_dir / "pipeline.log")

    if args.step == "info":
        run_info()
    elif args.step == "collect":
        from semnav_gp.collection.collect import run_collection

        run_collection(settings, limit=args.limit, instance_ids=args.instances)
    elif args.step == "gold":
        from semnav_gp.preprocessing.run_gold import compare_with_cosil, run_gold

        run_gold(settings, limit=args.limit, instance_ids=args.instances, overwrite=args.overwrite)
        cosil = settings.raw_dir / "external" / "cosil_gt.json"
        if cosil.exists():
            compare_with_cosil(settings, cosil)
        else:
            get_logger("gold").warning("CoSIL gt.json not found at %s; skipping validation", cosil)
    else:
        raise SystemExit(f"Step '{args.step}' is not implemented yet.")


if __name__ == "__main__":
    main()

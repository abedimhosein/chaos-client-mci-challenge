import logging
import os
import random
from pathlib import Path

from dotenv import load_dotenv

from app.client import (
    Orchestrator,
    OrchestratorConfig,
)
from app.models import Group, Node

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y/%m/%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


def env(path: Path) -> dict:
    load_dotenv(dotenv_path=path)
    environ = os.environ

    return {
        'nodes': set(environ.get('NODES').split(";")),
        'max_retries': int(environ.get('MAX_RETRIES', 5)),
        'timeout': float(environ.get('TIMEOUT', 2)),
        'backoff': float(environ.get('BACKOFF', 1)),
    }


def main() -> None:
    env_variables = env(Path(__file__).resolve().parent / '.env')
    nodes = [Node(node_base_url) for node_base_url in env_variables.pop('nodes')]

    with Orchestrator(nodes=nodes, config=OrchestratorConfig(**env_variables)) as orchestrator:
        while True:
            group = Group(group_id="".join(random.choices("abcdefghijklmnopqrstuvwxyz1234567890", k=10)))

            try:
                orchestrator.create_group(group)
            except Exception:
                logger.exception("Failed to create group %s.", group.group_id)

            try:
                orchestrator.delete_group(group)
            except Exception:
                logger.exception("Failed to delete group %s.", group.group_id)


if __name__ == "__main__":
    main()

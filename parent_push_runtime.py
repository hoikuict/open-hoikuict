from __future__ import annotations

import asyncio
import logging

from sqlmodel import Session

import database
from parent_push_service import (
    create_parent_push_transport,
    run_parent_push_worker_cycle,
)
from security_config import (
    deployment_environment,
    parent_auth_mode,
    parent_push_transport,
)


logger = logging.getLogger(__name__)
DEFAULT_WORKER_INTERVAL_SECONDS = 2.0


def parent_push_worker_enabled() -> bool:
    environment = deployment_environment()
    transport = parent_push_transport()
    return (environment == "development" and transport in {"capture", "webpush"}) or (
        environment == "production"
        and transport == "webpush"
        and parent_auth_mode() == "local_password"
    )


def run_parent_push_worker_once() -> int:
    transport_name = parent_push_transport()
    transport = create_parent_push_transport(transport_name)
    with Session(database.engine) as session:
        return run_parent_push_worker_cycle(
            session,
            transport=transport,
            environment=deployment_environment(),
        )


async def parent_push_worker_loop(
    *,
    interval_seconds: float = DEFAULT_WORKER_INTERVAL_SECONDS,
) -> None:
    while True:
        try:
            await asyncio.to_thread(run_parent_push_worker_once)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("parent push worker cycle failed")
        await asyncio.sleep(interval_seconds)

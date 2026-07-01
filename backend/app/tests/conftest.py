import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop so Motor connections survive across async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

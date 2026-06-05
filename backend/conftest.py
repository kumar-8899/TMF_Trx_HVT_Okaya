"""Root conftest — applies to both tests/ and modules/ test trees.

aiomqtt (paho) needs a selector loop; Windows defaults to Proactor, which does
not implement socket add_reader/remove_writer. Force the selector policy for the
whole test session (broker-backed tests live under modules/ too).
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

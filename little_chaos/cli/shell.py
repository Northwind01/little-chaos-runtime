from __future__ import annotations

import asyncio
from typing import Any

from little_chaos.cli.factory import build_runtime, close_runtime
from little_chaos.runtime.ownership import ControlOwnershipError
from little_chaos.runtime.types import RuntimeConfig


async def _ainput(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


async def _amain() -> None:
    config = RuntimeConfig.from_env()
    try:
        runtime = build_runtime(config)
    except ControlOwnershipError as exc:
        print(f"cannot start autonomous runtime: {exc}")
        return
    except RuntimeError as exc:
        print(f"cannot start runtime: {exc}")
        return

    print("LittleChaos runtime shell. Type ':help' for commands.")
    active_task: asyncio.Task[Any] | None = None

    try:
        while True:
            line = (await _ainput("> ")).strip()
            if not line:
                continue

            if line.startswith(":"):
                cmd = line[1:].strip().lower()

                if cmd in {"quit", "exit"}:
                    if active_task is not None:
                        await runtime.stop()
                        try:
                            await active_task
                        except Exception:
                            pass
                    break

                if cmd == "help":
                    print(":stop - cancel current episode")
                    print(":status - runtime status")
                    print(":skills - supported skills")
                    print(":tasks - mock-planner phrases (default PLANNER_BACKEND=mock)")
                    print("Anything else: a natural language task")
                    continue

                if cmd == "tasks":
                    try:
                        from little_chaos.planner.mock import SEQUENCES

                        for name in sorted(SEQUENCES):
                            print(f"  {name}")
                    except Exception as exc:
                        print(f"cannot list mock tasks: {exc}")
                    continue

                if cmd == "stop":
                    await runtime.stop()
                    if active_task is not None:
                        outcome = await active_task
                        print(f"episode stopped: {outcome.value}")
                        active_task = None
                    continue

                if cmd == "status":
                    print(runtime.status)
                    continue

                if cmd == "skills":
                    print(runtime.skills.names())
                    continue

                print(f"unknown command: {cmd!r}")
                continue

            if active_task is not None and not active_task.done():
                await runtime.stop()
                try:
                    await active_task
                except Exception:
                    pass
                active_task = None

            active_task = asyncio.create_task(runtime.execute(line))
            outcome = await active_task
            print(f"episode outcome: {outcome.value}")
            active_task = None
    finally:
        close_runtime(runtime)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()

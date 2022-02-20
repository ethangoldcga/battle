import asyncio
from dataclasses import asdict
from pathlib import Path
import aiohttp
from aiohttp import web

from robots import Arena, Robot, GameParameters
from example_drivers import PongDriver, RadarDriver, StillDriver


STATIC_PATH = Path(__file__).parent / "site"
INDEX_PATH = STATIC_PATH / "index.html"


async def runner_task(a: Arena, event: asyncio.Event) -> None:
    print(f"Starting battle with: {', '.join(r.name for r in a.robots)}")
    while not (winner := a.get_winner()):
        a.update_arena()
        event.set()
        event.clear()
        await asyncio.sleep(1 / GameParameters.FPS)
    a.winner = winner.name
    event.set()
    event.clear()
    print(f"{winner.name} is the winner!")


async def server_task(arena: Arena, event: asyncio.Event) -> None:
    app = web.Application()
    app["arena"] = arena
    app["event"] = event
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/watch", watch_handler)
    app.router.add_static("/", STATIC_PATH)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", 8000)
    await site.start()
    try:
        await asyncio.Future()
    finally:
        await runner.cleanup()


def arena_state_as_json(arena: Arena):
    d = asdict(arena)
    del d["robot_drivers"]
    return d


async def index_handler(request):
    return web.FileResponse(INDEX_PATH)


async def watch_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    async def send_updates():
        try:
            while True:
                # print("Waiting for event")
                await request.app["event"].wait()
                # print("Got event")
                await ws.send_json(arena_state_as_json(request.app["arena"]))
        except Exception as e:
            print(f"Exception: {e!r}")
        finally:
            print("Exiting sender")

    send_task = asyncio.create_task(send_updates())
    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.ERROR:
                print("ws connection closed with exception %s" % ws.exception())
    finally:
        send_task.cancel()

    print("websocket connection closed")

    return ws


async def amain():
    arena = Arena()
    event = asyncio.Event()
    server = asyncio.create_task(server_task(arena, event))
    while True:
        arena.winner = None
        arena.robots = [Robot("radarbot"), Robot("pongbot"), Robot("stillbot")]
        arena.robot_drivers["radarbot"] = RadarDriver()
        arena.robot_drivers["pongbot"] = PongDriver()
        arena.robot_drivers["stillbot"] = StillDriver()
        await runner_task(arena, event)
        await asyncio.sleep(10)
    await server


if __name__ == "__main__":
    asyncio.run(amain())

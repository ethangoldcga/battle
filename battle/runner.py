#!/usr/bin/env python3

import argparse
import asyncio
import json
import uuid
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
import aiohttp_jinja2
import jinja2
from aiohttp import web

from battle.arena import Arena
from battle.chillbot import ChillDriver
from battle.persistence import Connection, create_connection, get_leaderboard, store_match, store_match_cmd_stat
from battle.pongbot import PongDriver
from battle.radarbot import RadarDriver
from battle.robots import GameParameters, Robot, RobotCommand, RobotCommandType
from battle.util import state_as_json


TEMPLATE_PATH = Path(__file__).parent / "templates"
STATIC_PATH = Path(__file__).parent / "static"
ARENA_STATE_DELAY_LINE_LEN = GameParameters.FPS * 10
MAX_ARENA_ID = 1000
MAX_MATCH_PLAYERS = 20

@dataclass
class Match:
    arena_id: int
    min_num_players: int = 2
    wait_time: int = 10
    started: bool = False
    finished: bool = False
    allow_late_entrants: bool = False
    arena: Arena = field(default_factory=Arena)
    event: asyncio.Event = field(default_factory=asyncio.Event)
    command_queues: Dict[str, List[RobotCommand]] = field(default_factory=dict)
    arena_state_delay_line: List[Arena] = field(default_factory=list)
    player_secrets: Dict[str, str] = field(default_factory=dict)
    player_connected: Dict[str, bool] = field(default_factory=dict)
    runner_task: asyncio.Task = field(init=False)
    stats_db: Optional[Connection] = None
    stats: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(lambda: 0)))

    def __post_init__(self):
        self.runner_task = asyncio.create_task(runner_task(self))
        # For demos, match 0 gets some example bots
        if self.arena_id == 0:
            self.allow_late_entrants = True
            self.wait_time = 1
            asyncio.create_task(demo_player_task("pongbot", PongDriver()))
            asyncio.create_task(demo_player_task("radarbot", RadarDriver()))
            asyncio.create_task(demo_player_task("chillbot", ChillDriver()))


async def demo_player_task(robot_name: str, driver):
    try:
        print(f"Starting demo player {robot_name}")
        async with aiohttp.ClientSession() as client:
            ## fails with any change in IP/port
            async with client.ws_connect(f"http://{GameParameters.ADDR}:{GameParameters.PORT}/api/play/0") as ws:
                await ws.send_json({"name": robot_name, "secret": str(uuid.uuid4())})
                async for msg in ws:
                    if "echo" in msg.json():
                        continue
                    r = Robot.from_dict(msg.json())
                    cmd = driver.get_next_command(r)
                    if cmd is None:
                        continue
                    if isinstance(cmd, RobotCommand):
                        cmd = [cmd]
                    if isinstance(cmd, List):
                        for c in cmd:
                            await ws.send_json(c.to_dict())
    except Exception as e:
        print(f"Demo player {robot_name} exception: {e!r}")


def get_or_create_match(matches: Dict[int, Match], arena_id: int, recycle: bool, db: Connection) -> Match:
    if MAX_ARENA_ID < 0 or arena_id > MAX_ARENA_ID:
        raise KeyError(arena_id)

    match = matches.get(arena_id)
    if match is None or match.finished and recycle:
        match = Match(arena_id, stats_db=db)
        matches[arena_id] = match

    return matches[arena_id]


async def runner_task(match: Match) -> None:
    """Runs a single match, returning when there is a clear winner or there are no turns remaining"""
    try:
        print(f"Waiting for at least {match.min_num_players} players")
        while len(match.arena.robots) < match.min_num_players:
            await asyncio.sleep(1)
        print(f"{len(match.arena.robots)} have joined, will start in {match.wait_time} seconds")
        await asyncio.sleep(match.wait_time)
        print(f"Starting battle with: {', '.join(r.name for r in match.arena.robots)} at {datetime.now()}")
        match.started = True
        standing_orders = {r.name: RobotCommand(RobotCommandType.IDLE, 0) for r in match.arena.robots}
        while not match.arena.get_winner() and match.arena.remaining > 0:
            match.arena.remaining -= 1
            if match.arena.remaining % GameParameters.COMMAND_RATE == 0:
                standing_orders = {r.name: RobotCommand(RobotCommandType.IDLE, 0) for r in match.arena.robots}
                # Get new commands for each robot
                for r in match.arena.robots:
                    r.cmd_q_len = len(match.command_queues[r.name])
                match.event.set()
                match.event.clear()
                await asyncio.sleep(GameParameters.COMMAND_RATE / GameParameters.FPS)
                for r in match.arena.robots:
                    q = match.command_queues.get(r.name)
                    if q:
                        standing_orders[r.name] = q.pop(0)
                    else:
                        standing_orders[r.name] = RobotCommand(RobotCommandType.IDLE, 0)
                # Save some stats
                for name, order in standing_orders.items():
                    match.stats[name][order.command_type.name] += 1
                # Process the commands
                match.arena.update_commands(standing_orders)
                # Retain all commands as standing orders, except for FIRE which only occurs once
                match.arena.reset_flags()
                for command in standing_orders.values():
                    if command.command_type is RobotCommandType.FIRE:
                        command.command_type = RobotCommandType.IDLE
            else:
                match.arena.update_commands(standing_orders)
            match.arena.update_arena()
            match.arena_state_delay_line.append(deepcopy(match.arena))
        winner = match.arena.get_winner()
        if not winner:
            #winner = max(match.arena.robots, key=lambda r: r.health)
            winner = match.arena.winner_calc()
        match.arena.winner = winner.name
        match.arena_state_delay_line.append(deepcopy(match.arena))
        match.finished = True
        match.event.set()
        match.event.clear()
        ## EGOLD
        print(f"{winner.name} is the winner with max sum of {winner.health:.2f} health and {winner.damage_inflicted:.2f} damage inflicted!")
        if match.stats_db:
            print("Storing match stats ...", end="")
            match_id = store_match(match.stats_db, match.arena_id, datetime.now(tz=timezone.utc), winner.name)
            print(f"match_id={match_id}...", end="")
            for name, cmd_stats in match.stats.items():
                for cmd, stat in cmd_stats.items():
                    store_match_cmd_stat(match.stats_db, match_id, name, cmd, stat)
            print("done!")
    except Exception as e:
        print(f"Runner exception: {e!r}")


async def server_task(bind_addr: str = GameParameters.ADDR, list_port: int = GameParameters.PORT) -> None:
    app = web.Application()
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(TEMPLATE_PATH))

    app["matches"] = {}
    app["match_db"] = create_connection()

    app.router.add_get("/", index_handler)
    app.router.add_get("/game/{arena_id}", index_handler)
    app.router.add_get("/api/watch/{arena_id}", watch_handler)
    app.router.add_get("/api/play/{arena_id}", play_handler)
    app.router.add_get("/api/leaderboard/{arena_id}", leaderboard_handler)
    app.router.add_static("/", STATIC_PATH, name="static", append_version=True)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, bind_addr, list_port)
    await site.start()
    print(f"Serving on http://{bind_addr}:{list_port}")
    try:
        await asyncio.Future()
    finally:
        await runner.cleanup()


@aiohttp_jinja2.template("index.html.j2")
async def index_handler(request):
    return {}


async def watch_handler(request):
    """Sends arena updates to the client for rendering. Since this includes all x,y positions of each robot,
    a delay-line is used to minimize any benefit of cheating."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    arena_id = int(request.match_info["arena_id"])
    print(f"New request for arena {arena_id}")

    async def send_updates():
        placeholder_arena = Arena()
        try:
            while True:
                match = get_or_create_match(
                    request.app["matches"], arena_id, recycle=arena_id == 0, db=request.app["match_db"]
                )
                delay_line = match.arena_state_delay_line
                # Wait until enough time has passed before we start sending results
                while len(delay_line) < ARENA_STATE_DELAY_LINE_LEN:
                    msg = state_as_json(placeholder_arena)
                    await ws.send_str(msg)
                    await asyncio.sleep(1)
                # Start playing from near the end
                if match.finished:
                    idx = len(delay_line) - 1
                else:
                    idx = max(0, len(delay_line) - ARENA_STATE_DELAY_LINE_LEN)
                # Return results until we reach the end and the actual game is finished
                while not match.finished or idx < len(delay_line):
                    # Ensure we don't go over the end
                    if idx >= len(delay_line):
                        idx = len(delay_line) - 1
                    # Ensure we don't fall behind either
                    lag = len(delay_line) - ARENA_STATE_DELAY_LINE_LEN - idx
                    if lag > 0:
                        fps_mult = 1.1
                    elif lag < 0:
                        fps_mult = 0.99
                    else:
                        fps_mult = 1

                    # Get the arena state to send
                    arena = delay_line[idx]
                    idx += 1
                    # Send it
                    msg = state_as_json(arena)
                    await asyncio.gather(ws.send_str(msg), asyncio.sleep(1 / GameParameters.FPS / fps_mult))
                # Match is finished and we've replayed everything, chill for a bit - replay the final
                # frame until a new match is available
                await asyncio.sleep(1)
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


async def play_handler(request):
    """Sends robot updates to the client and gets resulting commands, adding them to a command queue for the
    given robot."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    arena_id = int(request.match_info["arena_id"])
    match = get_or_create_match(request.app["matches"], arena_id, recycle=True, db=request.app["match_db"])

    async def send_updates():
        try:
            while True:
                await match.event.wait()
                r = match.arena.get_robot(robot_name)
                msg = json.dumps(asdict(r), separators=(",", ":"))
                await ws.send_str(msg)
                if match.arena.winner is not None:
                    await ws.send_json({"echo": f"{match.arena.winner.name} is the winner with max sum of {winner.health:.2f} health and {match.arena.winner.damage_inflicted:.2f} damage inflicted!"})
                    await ws.send_json({"echo": f"{match.arena.finalstats}"})
                    await ws.send_json({"echo": f"{match.arena.winner} is the winner!"})
                    break
                if not r.live():
                    await ws.send_json({"echo": f"*** {r.name} is no longer alive!"})
                    break
        except KeyError:
            print("Robot dropped")
        except Exception as e:
            print(f"Exception: {e!r}")
        finally:
            print("Closing websocket")
            await ws.close()
            print("Exiting sender")

    send_task = None
    robot_name = None
    try:
        # First wait for the hello message which gives us the robot's name
        hello_msg = await ws.receive_json()
        robot_name = hello_msg["name"]
        robot_secret = hello_msg["secret"]
        if not isinstance(robot_name, str):
            return
        if not isinstance(robot_secret, str):
            return

        if robot_secret == match.player_secrets.get(robot_name) and not match.player_connected.get(robot_name):
            await ws.send_json({"echo": f"Welcome back, {robot_name}"})
        else:
            if match.started and not match.allow_late_entrants:
                await ws.send_json({"echo": f"Sorry {robot_name}, this game has already started"})
                return

            # If we already have a player with this name, give up immediately
            if any(r.name == robot_name for r in match.arena.robots):
                await ws.send_json({"echo": f"Sorry, {robot_name} is already in the game"})
                return
            # Limit the number of players to MAX_MATCH_PLAYERS
            num_alive = len([r for r in match.arena.robots if r.live()])
            if num_alive >= MAX_MATCH_PLAYERS:
                await ws.send_json({"echo": f"Sorry {robot_name}, this game is full"})
                return
            # Drop any dead players making room for more
            if len(match.arena.robots) != num_alive:
                for r in match.arena.robots[:]:
                    if not r.live():
                        print(f"Dropping robot {r.name}")
                        match.arena.robots.remove(r)
                        match.command_queues.pop(r.name, None)
            # Finally we can add this new robot
            await ws.send_json({"echo": f"Welcome, {robot_name}"})
            print(f"Adding robot {robot_name}")
            match.arena.robots.append(Robot(robot_name))
            match.command_queues[robot_name] = []
            match.player_secrets[robot_name] = robot_secret
        # Start sending state updates to the player
        match.player_connected[robot_name] = True
        send_task = asyncio.create_task(send_updates())
        # Start receiving commands from the player, adding them to the command queue
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    cmds = msg.json()
                    if cmds is None:
                        continue
                    if isinstance(cmds, dict):
                        cmds = [cmds]
                    for cmd in cmds[: match.arena.remaining]:
                        command = RobotCommand(
                            command_type=RobotCommandType(cmd.get("command_type")),
                            parameter=float(cmd.get("parameter")),
                        )
                        match.command_queues[robot_name].append(command)
                except KeyError:
                    print("Robot dropped")
                    break
                except (json.decoder.JSONDecodeError, TypeError, ValueError) as e:
                    await ws.send_json({"echo": "Bad command received."})
                    print(f"Bad command: {e!r}")
                    continue
            elif msg.type == aiohttp.WSMsgType.ERROR:
                print("ws connection closed with exception %s" % ws.exception())
                break
    finally:
        if robot_name is not None:
            match.player_connected[robot_name] = False
        if send_task is not None:
            send_task.cancel()
            await asyncio.gather(send_task, return_exceptions=True)
        await ws.close()

    print("websocket connection closed")

    return ws


def leaderboard_handler(request):
    arena_id = int(request.match_info["arena_id"])
    if arena_id < 0 or arena_id > MAX_ARENA_ID:
        raise web.HTTPNotFound
    data = get_leaderboard(request.app["match_db"], arena_id)
    return web.json_response(data)


async def amain():
    parser = argparse.ArgumentParser()
    parser.add_argument("--addr", default="127.0.0.1", help="Battle server bind address (default: 127.0.0.1)")
    #### EGOLD: Add arena size, max players options.
    parser.add_argument("--port", default="8000", help=f"Battle server listen port (default: 8000)")
    AW = GameParameters.ARENA_WIDTH
    AH = GameParameters.ARENA_HEIGHT
    parser.add_argument("--awidth", default=AW, help=f"Arena width in pixels: (default: {AW})")
    parser.add_argument("--aheight", default=AH, help=f"Arena height in pixels: (default: {AH})")
    args = parser.parse_args()
    try:
        GameParameters.ARENA_WIDTH = int(args.awidth)
        GameParameters.ARENA_HEIGHT = int(args.aheight)
        GameParameters.PORT = int(args.port)
        GameParameters.ADDR = args.addr
        await server_task(args.addr, int(args.port))
    except KeyboardInterrupt:
        return


def main():
    asyncio.run(amain())

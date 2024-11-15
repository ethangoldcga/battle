import argparse
import json
import uuid
import webbrowser
from urllib.parse import urljoin, urlsplit
import os
import websocket

from battle.robots import Robot, RobotCommand

####
## args available because the driver needs access
## for passing name in at driver object init time.
argparser = argparse.ArgumentParser()
botname = os.environ.get('USERNAME')
if not botname:
    botname = os.environ.get('USER')
if not botname:
    botname = "mystery"
    
argparser.add_argument("--name", default=botname, help="The name of the player.")
argparser.add_argument("--game-id", default="0", help="The game ID to play - default is 0")
argparser.add_argument("--url", default="ws://localhost:8000", help="The game server base URL.")
argparser.add_argument("--browser", action="store_true", help="Open a browser window to watch the game")
argparser.add_argument(
    "--secret", type=str, help="A secret to allow reconnect to the same robot in case of disconnect"
)
####

def play(robot_name: str, robot_secret: str, driver, url: str):
    """Connects to the game server at `url` and passes robot state updates to the `driver`, and commands back
    to the game server"""
    print(f"Connecting to game API server... ", end="")
    ws = websocket.WebSocket()
    try:
        ws.connect(url)
    except ConnectionRefusedError:
        print("Could not connect")
        return
    print("Done!")

    try:
        ws.send(json.dumps({"name": robot_name, "secret": robot_secret}))
        for msg in ws:
            if not msg:
                break
            data = json.loads(msg)
            if "echo" in data:
                print(data["echo"])
                continue
            robot_state = Robot.from_dict(data)
            command = driver.get_next_command(robot_state)
            if command is None:
                continue
            if not isinstance(command, list):
                command = [command]
            for cmd in command:
                if not isinstance(cmd, RobotCommand):
                    raise TypeError(f"Commands should be of type RobotCommand, not {type(cmd)}")
                ws.send(json.dumps(cmd.to_dict()))
    except (websocket.WebSocketConnectionClosedException, BrokenPipeError):
        pass
    finally:
        print("Connection closed")






def player_main(robot_name: str, driver):
    """Main entry point for running a robot"""
    """
    argparser = argparse.ArgumentParser()
    argparser.add_argument("--name", default=robot_name, help="The name of the player.")
    argparser.add_argument("--game-id", default=0, help="The game ID to play - default is 0")
    argparser.add_argument("--url", default="ws://localhost:8000", help="The game server base URL.")
    argparser.add_argument("--browser", action="store_true", help="Open a browser window to watch the game")
    argparser.add_argument(
        "--secret", type=str, help="A secret to allow reconnect to the same robot in case of disconnect"
    )
    """
    args = argparser.parse_args()
    url = urljoin(args.url.replace("http", "ws"), f"/api/play/{args.game_id}")
    us = urlsplit(args.url)
    watch_url = f"{us.scheme.replace('ws', 'http')}://{us.netloc}/game/{args.game_id}"
    print(f"Watch this game at: {watch_url}")
    if args.browser:
        webbrowser.open(watch_url)
    if args.secret is None:
        secret = str(uuid.UUID(fields=(0, 0, 0, 0, 0, uuid.getnode())))
    else:
        secret = args.secret
    try:
        play(args.name, secret, driver, url)
    except KeyboardInterrupt:
        pass

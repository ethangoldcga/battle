## battle - a Python based robot battle simulator set in space
## This is a fork of https://github.com/atcase/battle.git
## as of June, 2024 for updates to the arena
## See CHANGES.md file for details
##

This is a robot programming game which allows programming a virtual spaceship robot driver with simple commands
to fight a battle against other players.

![](battle_demo.gif)

or alternatively from GitHub, with:

    $ python -m pip install git+https://github.com/ethangoldcga/battle.git

A sample robot battlefield server can then be run with:

    $ battle-runner

Once running, a sample game can be watched at http://localhost:8000/

If a publically available battlefield server is available elsewhere, then the above step can be skipped.

Three example robots are provided and will automaticaly join the demo game.

- `pongbot`: a spaceship driver who bounces around the screen
- `chillbot`: a spaceship driver who stays still and shoots
- `radarbot`: a spaceship driver with an optimized radar scanning algorithm


The robot driver works by calling the `get_next_command` function with the current state
of the robot. The function then returns the next command to issue.

Commands can be any of the following:

- `ACCELERATE`: Increases the forward velicity of the spaceship.
- `TURN_HULL`: Rotates the spaceship hull.
- `TURN_TURRET`: Rotates the spaceship's gun turret.
- `TURN_RADAR`: Rotates the spaceship's detection radar.
- `FIRE`: Fires the weapon.

Some commands may also include a parameter to refine the command:

- `ACCELERATE`: There is no parameter - the spaceship always increases velocity by a fixed amount.
- `TURN_HULL`: The parameter indicates the number of degrees of rotation.
- `TURN_TURRET`: The parameter indicates the number of degrees of rotation.
- `TURN_RADAR`: The parameter indicates the number of degrees of rotation.
- `FIRE`: The parameter controls how much weapon energy to use when firing.

The input to the `get_next_command` function is the current state of the robot as below:

- `name`: The name of the robot. This never changes throughout the game.
- `position`: The (X,Y) co-ordinates of the robot's current position on the battlefield, ranging from 0..1000.
- `velocity`: The current velocity of the robot, in units-per-frame.
- `velocity_angle`: The current direction (in degrees) that the robot is moving.
- `hull_angle`: The current direction (in degrees) that the hull is facing.
- `turret_angle`: The angular difference between where the hull is facing, and where the gun turret is facing. If set to
  0 then the gun turret is facing forwards.
- `radar_angle`: The angular difference between where the gun turret is facing, and where the scanning radar is facing.
  i.e. the radar is sitting on top of the gun turret and moves whenever the turret moves. It can also move independently
  if commanded.
- `health`: The current health of the spaceship from 100% down to 0%.
- `weapon_energy`: The current weapon energy. The weapons recharge each frame, and firing the weapon depletes energy.
- `radius`: The radius of the spaceship. This is a constant value and is used to calculate whether the spaceship has
  been hit.
- `radar_ping`: If the radar detected an enemy spaceship during the last scan (rotation), this value indicates the
  distance.
- `got_hit`: If the ship was hit during the last turn, this flag will be `True`.
- `bumped_wall`: If the ship bumped the wall defined by the 1000x1000 battlefield, this flag will be `True`.
- `cmd_q_len`: The robot may queue up several commands to the spaceship. This property indicates how many commands are
  already queued.

## Connecting a new robot to a server

The robots may be copied, modified or replaced. They can then connect to a battlefield server by running them locally,
with the server URL and robot name provided on the command line. e.g.

    $ battle-pongbot pongbot2 --url https://some.battlefield.server

The URL to watch the game will be provided, and the robot then connects.

There are several other options available to robot drivers:

```
usage: battle-pongbot [-h] [--game-id GAME_ID] [--url URL] [--browser] [--secret SECRET] [name]

positional arguments:
  name               The name of the player.

optional arguments:
  -h, --help         show this help message and exit
  --game-id GAME_ID  The game ID to play - default is 0
  --url URL          The game server base URL.
  --browser          Open a browser window to watch the game
  --secret SECRET    A secret to allow reconnect to the same robot in case of disconnect
```

## Playing a match

Several games can be staged at once. The default game index 0 is shown at the home page of the server. However, other
game IDs can be used as well, by specifying them on the player command line with `--game-id`. The game ID is an integer
value from 0 to 1000. All games are public and can be joined by anyone, however once the game has started, nobody else
may join. Each player has 10 seconds after the second player has joined before the game starts and no new players may
join.

If a robot driver crashes or disconnects, the original player may rejoin. An automatically generated secret is used to
achieve this, however it can be overridden with the `--secret` command argument.

## Watching the game

The battlefield is located 10 light seconds from your terminal, and as such all vision is delayed by 10 seconds.

## Winning the game
If all other robots have been destroyed, the last robot / spaceship pair standing is the winner.
Each game expires after 5 minutes at which point the most the winner is determined by the sum of each surviving robot's remaining health and the total damage it caused to other robots.


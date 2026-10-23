## @file
## Apply script for the fire crystal levers in Glacial Hollow.
##
## Each lever names the ice wall squares it melts in its event options, as
## space-separated "x,y" pairs on the lever's own map; both levers of one
## tunnel list both of its mouths, so one crystal opens the whole tunnel.
## Malformed options raise, so the mistake shows in the server log. Applying the lever
## while carrying a fire crystal removes those walls and consumes one crystal.
## The walls come back when the map resets, because the reloaded map is read
## from its source file again.

from Atrinik import *

CRYSTAL_ARCH = "nawerhals_fire_crystal"
WALL_ARCH = "fwall_ice"


def parse_squares(options):
    squares = []

    for pair in (options or "").split():
        x, sep, y = pair.partition(",")

        if not sep or not x.isdigit() or not y.isdigit():
            raise ValueError("bad fire crystal lever square {!r} in {!r}".format(pair, options))

        squares.append((int(x), int(y)))

    if not squares:
        raise ValueError("fire crystal lever lists no wall squares")

    return squares


def find_walls():
    walls = []

    for x, y in parse_squares(GetOptions()):
        for obj in me.map.Objects(x, y):
            if obj.arch.name == WALL_ARCH:
                walls.append(obj)

    return walls


def main():
    # The lever has no connection of its own; the script decides everything.
    SetReturnValue(1)

    if not pl:
        return

    walls = find_walls()

    if not walls:
        pl.DrawInfo("The ice here has already melted. It will reform in time.", COLOR_WHITE)
        return

    crystal = activator.FindObject(INVENTORY_CONTAINERS, CRYSTAL_ARCH)

    if not crystal:
        pl.DrawInfo("Beside the lever is a small fire-blackened socket aimed at the wall of ice. Nothing happens when you pull the lever; perhaps a fire crystal, dropped by the creatures of this cave, would fit the socket.", COLOR_WHITE)
        return

    # Melt the walls before taking the crystal, so a failure can never cost
    # the player a crystal without opening the way.
    for wall in walls:
        wall.Destroy()

    crystal.Decrease()
    pl.DrawInfo("You set the fire crystal into the lever's socket and pull. A small blast of fire melts the wall of ice in front of you, and the crystal disintegrates.", COLOR_ORANGE)


main()

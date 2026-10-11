"""One-shot Classic ASK_SHOW mutation fixture for native map packet tests.

Attach this script to the actor's ASK_SHOW event with options ``blocker``,
``monster``, ``move``, ``invisible``, ``cover``, ``hide_other``, ``move_other``,
``viewstate``, ``kick_observer``, ``kick_other``, or
``floor_on``/``floor_off``/``hidden_on``/``hidden_off``.
Place the actor at x >= 2 with free space at x - 1 and x + 1. For ``cover``, set the actor's
``los_ask_show_upper_path`` custom key to its loaded upper map's path.
For other-actor modes, name the object at x + 1, y with the custom key
``los_ask_show_other_name``; relocation moves it by (+1, +1). Roof flag
modes select the single roof at actor x, y on ``los_ask_show_upper_path``.
The ``viewstate`` mode disables the observing activator controller's ``tli``.
Kick modes require an observing activator in playing state with ``kick``
command permission. ``kick_observer`` targets its own name; ``kick_other``
targets the name in the actor's ``los_ask_show_kick_name`` custom key.
The ``los_ask_show_done`` key records completion and prevents later mutations.
"""

import Atrinik

actor = Atrinik.WhoAmI()
mode = Atrinik.GetOptions()
if actor.ReadKey("los_ask_show_done") != "1":
    if mode not in ("blocker", "monster", "move", "invisible", "cover",
                    "hide_other", "move_other", "floor_on", "floor_off",
                    "hidden_on", "hidden_off", "viewstate", "kick_observer",
                    "kick_other"):
        raise ValueError("Unknown LOS ASK_SHOW fixture mode: {}".format(mode))
    # Fence a nested ASK_SHOW invocation before the mutation sends updates.
    actor.WriteKey("los_ask_show_done", "1")
    if mode == "blocker":
        actor.map.CreateObject("wall_wood_1", actor.x - 1, actor.y)
    elif mode == "monster":
        actor.map.CreateObject("raas", actor.x - 1, actor.y)
    elif mode == "move":
        actor.map.Insert(actor, actor.x + 1, actor.y)
    elif mode == "invisible":
        actor.f_is_invisible = True
    elif mode == "viewstate":
        Atrinik.WhoIsActivator().Controller().tli = False
    elif mode in ("kick_observer", "kick_other"):
        observer = Atrinik.WhoIsActivator()
        name = (observer.name if mode == "kick_observer"
                else actor.ReadKey("los_ask_show_kick_name"))
        if not name:
            raise ValueError("Expected a kick target name")
        # The command can synchronously free its observer and socket. Do not
        # read any object or controller wrapper after executing it.
        observer.Controller().ExecuteCommand("/kick " + name)
    elif mode == "cover":
        upper = Atrinik.ReadyMap(actor.ReadKey("los_ask_show_upper_path"))
        upper.CreateObject("roof_thatch", actor.x, actor.y)
    elif mode in ("hide_other", "move_other"):
        name = actor.ReadKey("los_ask_show_other_name")
        targets = [obj for obj in actor.map.Objects(actor.x + 1, actor.y)
                   if obj.name == name]
        if len(targets) != 1:
            raise ValueError("Expected one named earlier actor: {}".format(name))
        other = targets[0]
        if mode == "hide_other":
            other.f_is_invisible = True
        else:
            other.map.Insert(other, other.x + 1, other.y + 1)
    elif mode in ("floor_on", "floor_off", "hidden_on", "hidden_off"):
        upper = Atrinik.ReadyMap(actor.ReadKey("los_ask_show_upper_path"))
        roofs = [obj for obj in upper.Objects(actor.x, actor.y)
                 if obj.arch.name == "roof_thatch"]
        if len(roofs) != 1:
            raise ValueError("Expected one upper-map roof")
        roof = roofs[0]
        if mode.startswith("floor_"):
            roof.f_is_floor = mode == "floor_on"
        else:
            roof.f_hidden = mode == "hidden_on"

Atrinik.SetReturnValue(0)

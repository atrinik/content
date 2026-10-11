"""One-shot Classic ASK_SHOW mutation fixture for native map packet tests.

Attach this script to the actor's ASK_SHOW event with options ``blocker``,
``monster``, ``move``, ``invisible``, or ``cover``. Place the actor at x >= 2
with free space at x - 1 and x + 1. For ``cover``, set the actor's
``los_ask_show_upper_path`` custom key to its loaded upper map's path.
The ``los_ask_show_done`` key records completion and prevents later mutations.
"""

import Atrinik

actor = Atrinik.WhoAmI()
mode = Atrinik.GetOptions()
if actor.ReadKey("los_ask_show_done") != "1":
    if mode not in ("blocker", "monster", "move", "invisible", "cover"):
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
    elif mode == "cover":
        upper = Atrinik.ReadyMap(actor.ReadKey("los_ask_show_upper_path"))
        upper.CreateObject("roof_thatch", actor.x, actor.y)

Atrinik.SetReturnValue(0)

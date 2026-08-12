"""Complete the Lost Memories apartment lesson when its hammock is used."""

from Atrinik import COLOR_GREEN, WhoIsActivator
from LostMemoriesApartment import complete_apartment_tutorial


activator = WhoIsActivator()
if complete_apartment_tutorial(activator):
    activator.Controller().DrawInfo(
        "Your apartment is now your recall point. Return to Sam's priest, "
        "Brelend Lee, to continue recovering your memories.",
        COLOR_GREEN,
    )

"""Temple.py: Implements temple-related functions."""

from Atrinik import *
from Interface import InterfaceBuilder
from TempleServices import (
    SERVICES,
    execute_treatment,
    provider_for,
    quote as service_quote,
    snapshot as service_snapshot,
)


service_descriptions = {
    "remove depletion": "Depletion most commonly occurs when you die, and it drains some of your stat attributes. I can restore them with a remove depletion prayer.",
    "remove curse": "I will remove ordinary curses from cursed items in your inventory. A permanent curse may return.",
    "remove damnation": "I will remove damnation from damned items in your inventory. A permanent damnation may return.",
    "cure disease": "I can cure diseases that are within my service training.",
    "cure poison": "I can cleanse poison that is within my service training.",
}

class Temple(InterfaceBuilder):
    """Temple interface builder."""

    temple_name = "xxx"
    temple_desc = "xxx"
    enemy_temple_name = ""
    enemy_temple_desc = ""

    def subdialog_services(self):
        """Show the available temple services."""

        for service in SERVICES.values():
            self.add_link(service.title, dest=service.spell)

        self.add_link("Spare bit of food", dest="food")
        self.add_link("Tell me about {}.".format(self.temple_name), dest=self.temple_name)

        if self.enemy_temple_name:
            self.add_link(
                "Tell me about {}.".format(self.enemy_temple_name),
                dest=self.enemy_temple_name,
            )

    def dialog_hello(self):
        """Default hello dialog handler."""

        self.add_msg(
            "Welcome to the church of {god}. I am {npc.name}, a devoted servant of {god}.",
            god=self.temple_name,
        )

        if self.enemy_temple_name:
            self.add_msg(
                "Beware that followers of {enemy_god} are not welcome here.",
                enemy_god=self.enemy_temple_name,
            )

        self.add_msg("I can offer you the following services.")
        self.subdialog_services()

    def _provider(self):
        return provider_for(self._npc.name, self._npc.map.path)

    def _snapshot(self, service_name):
        return service_snapshot(service_name, self._activator.inv, Type.DISEASE)

    def _current_quote(self, service_name):
        provider = self._provider()
        if provider is None:
            self.add_msg(
                "My temple-service training is not configured, so I cannot safely offer this treatment."
            )
            return None

        condition = self._snapshot(service_name)
        if condition.count == 0:
            self.add_msg("You do not have a condition this service can treat.")
            return None

        try:
            current = service_quote(
                service_name,
                self._activator.level,
                provider.service_rank,
                condition,
            )
        except ValueError:
            self.add_msg(
                "This condition has difficulty {difficulty}, but my service rank is only {rank}. I cannot reliably treat it, so I will not cast or charge you.",
                difficulty=condition.difficulty,
                rank=provider.service_rank,
            )
            return None

        return provider, condition, current

    def _show_quote(self, current):
        if current.free:
            self.add_msg(
                "Newcomer care covers this difficulty-{difficulty} treatment. There is no charge.",
                difficulty=current.difficulty,
            )
        else:
            self.add_msg(
                "This difficulty-{difficulty} treatment will cost {cost}.",
                difficulty=current.difficulty,
                cost=CostString(current.cost),
            )
        self.add_link(
            "Confirm treatment",
            dest="buy {}|{}".format(current.service, current.token),
        )

    def _cast(self, provider, service_name):
        old_level = self._npc.level
        try:
            self._npc.level = provider.service_rank
            spell = GetArchetype(
                "spell_" + service_name.replace(" ", "_")
            ).clone.sp
            self._npc.Cast(spell, self._activator)
        finally:
            self._npc.level = old_level

    def _confirm(self, service_name, presented_token, provider, before, current):
        preview = current._replace(token=presented_token)
        result = execute_treatment(
            preview,
            current,
            self._activator.GetMoney(),
            before,
            lambda: self._cast(provider, service_name),
            lambda: self._snapshot(service_name),
            self._activator.PayAmount,
        )
        if result.outcome == "drift":
            self.add_msg(
                "Your condition or quote changed before confirmation. I have not cast or charged you; please review the new quote."
            )
            self._show_quote(current)
        elif result.outcome == "insufficient-funds":
            self.add_msg(
                "You do not have enough money. I have not cast or charged you."
            )
        elif result.outcome == "failure":
            self.add_msg("The prayer had no effect. You are not charged.")
        elif result.outcome == "payment-failure":
            self.add_msg(
                "The treatment had an effect, but payment could not be collected. You are not charged."
            )
        else:
            if result.outcome == "partial":
                self.add_msg(
                    "The prayer helped, but some of the condition remains. The confirmed partial-success policy applies."
                )
            else:
                self.add_msg("The treatment succeeds.")
            if result.charged:
                self.add_msg(
                    "You pay {cost}.",
                    cost=CostString(result.charged),
                    color=COLOR_YELLOW,
                )
            else:
                self.add_msg("No payment is due under newcomer care.")

    def dialog(self, msg):
        """Handle services and speaking about particular gods."""

        if msg == self.temple_name:
            self.add_msg(self.temple_desc)
            return
        if msg == self.enemy_temple_name:
            self.add_msg(self.enemy_temple_desc)
            return
        if msg == "food":
            if self._activator.food < 500:
                self._activator.food = 500
                self.add_msg("Your stomach is filled again.")
            else:
                self.add_msg("You don't look very hungry to me...")
            return

        presented_token = None
        if msg.startswith("buy "):
            service_name, separator, presented_token = msg[4:].partition("|")
            if not separator:
                return
        else:
            service_name = msg

        service = SERVICES.get(service_name)
        if service is None:
            return

        self.add_msg("[title]{title}[/title]", title=service.title)
        self.add_msg(service_descriptions[service_name])
        quoted = self._current_quote(service_name)
        if quoted is None:
            return
        provider, before, current = quoted
        if presented_token is None:
            self._show_quote(current)
        else:
            self._confirm(
                service_name, presented_token, provider, before, current
            )

class TempleGrunhilde(Temple):
    """Grunhilde temple."""
    temple_name = "Grunhilde"
    temple_desc = "I am a servant of the Valkyrie Queen and the Goddess of Victory, Grunhilde."

class TempleDalosha(Temple):
    """Dalosha temple."""
    temple_name = "Dalosha"
    temple_desc = "I am a servant of the first Queen of the Drow and Spider Goddess, Dalosha."
    enemy_temple_name = "Tylowyn"
    enemy_temple_desc = "The high elves and their oppressive queen! Do not be swayed by her traps, she started the war with her attempt to enforce proper elven conduct in war. Tylowyn was too cowardly and weak to realize that it was our destiny to rule the world, so now she and her elves shall also perish!"

class TempleDrolaxi(Temple):
    """Drolaxi temple."""
    temple_name = "Drolaxi"
    temple_desc = "I am a servant of Queen of the Chaotic Seas and the Goddess of Water, Drolaxi."
    enemy_temple_name = "Shaligar"
    enemy_temple_desc = "Flames and terror does he seek to spread. Do not be deceived, although the flame be kin to the Lady, he is complerely mad. Avoid the scorching flames or they will consume you. We shall rule the world and all shall be seas!"

class TempleElathiel(Temple):
    """Elathiel temple."""
    temple_name = "Elathiel"
    temple_desc = "I am a servant of the God of Light and King of the Angels, Elathiel."
    enemy_temple_name = "Rashindel"
    enemy_temple_desc = "Caution child, for you speak of the Fallen One. In the days before the worlds were created by our Lord Elathiel, the archangel Rashindel stood at his right hand. In that day, however, Rashindel sought to claim the throne of Heaven and unseat the Mighty Elathiel. The Demon King was quickly defeated and banished to Hell with the angels he managed to deceive and they were transformed into the awful demons and devils which threaten the lands to this day."

class TempleGrumthar(Temple):
    """Grumthar temple."""
    temple_name = "Grumthar"
    temple_desc = "I am a servant of the First Dwarven Lord and the God of Smithery, Grumthar."
    enemy_temple_name = "Jotarl"
    enemy_temple_desc = "Do not be speaking of that Giant tyrant amongst us. Him and his giants have long sought to crush the little folk. He has those goblin vermin under his wing also."

class TempleJotarl(Temple):
    """Jotarl temple."""
    temple_name = "Jotarl"
    temple_desc = "I am a servant of the Titan King and the God of the Giants, Jotarl."
    enemy_temple_name = "Grumthar"
    enemy_temple_desc = "Puny dwarves do not scare Jotarl with their technology and mithril weapons, we shall rule the caves! The Dwarves shall fall and we shall claim their gold for ourselves."

class TempleRashindel(Temple):
    """Rashindel temple."""
    temple_name = "Rashindel"
    temple_desc = "I am a servant of the Demonic King and the Overlord of Hell, Rashindel."
    enemy_temple_name = "Elathiel"
    enemy_temple_desc = "Accursed fool, do not mention that name in our presence! In the days before this world, the Tyrant sought to oppress us with the his oppressive ideals of truth and justice. After our master freed us from the simpleton lots who follow him, he was bound into the darkness which is now our glorious kingdom."

class TempleRogroth(Temple):
    """Rogroth temple."""
    temple_name = "Rogroth"
    temple_desc = "I am a servant of the King of the Stormy Skies and the God of Lightning, Rogroth."

class TempleShaligar(Temple):
    """Shaligar temple."""
    temple_name = "Shaligar"
    temple_desc = "I am a servant of King of the Lava and the God of Flame, Shaligar."
    enemy_temple_name = "Drolaxi"
    enemy_temple_desc = "Ah, the weak and cowardly sister of the Flame Lord. One day, she shall no longer be able to keep our flames from consuming all things and our flames shall make all subjects to our will."

class TempleTerria(Temple):
    """Terria temple."""
    temple_name = "Terria"
    temple_desc = "I am a servant of Mother Earth and the Goddess of Life, Terria."
    enemy_temple_name = "Zechna"
    enemy_temple_desc = "Speak not of the Dark Lord here! The King of Death with his awful necromantic minions that rise from the sleep of death are not to be trifled with, for they are dangerous. Our Lady has long sought to remove the plague of death from the lands after that foul Lich ascended."

class TempleTylowyn(Temple):
    """Tylowyn temple."""
    temple_name = "Tylowyn"
    temple_desc = "I am a servant of the first Queen of Elven Kind and Elven Goddess of Luck, Tylowyn."
    enemy_temple_name = "Dalosha"
    enemy_temple_desc = "That rebellious heretic! In the days of the First Elven Kings, the first daughter of our gracious Tylowyn sought to overthrow the Elven Kingdoms with her lies and treachery. After she was routed from the Elven lands, she took her band of rebel dark elves and hid in the caves, but unfortunately managed to survive there. Avoid those drow if you know what is best for you."

class TempleZechna(Temple):
    """Zechna temple."""
    temple_name = "Zechna"
    temple_desc = "I am a servant of the Lord of the Grave and King of Undeath, Zechna."
    enemy_temple_name = "Terria"
    enemy_temple_desc = "Do you honestly believe the lies of those naturists? The powers of undeath will rule the universe and the servants of Nature will fail. The Dark Lord shall not fail to dominate the land and all be consumed in glorious Death."

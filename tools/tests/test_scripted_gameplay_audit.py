from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.scripted_gameplay_audit import (
    MANIFEST_PATH,
    ScriptedGameplayAuditError,
    discover_sites,
    load_and_validate,
)


ROOT = Path(__file__).resolve().parents[2]


class ScriptedGameplayAuditTests(unittest.TestCase):
    def _fixture(
        self,
        root: Path,
        source_text: str,
        source_path: str = "maps/python/feature.py",
    ) -> Path:
        source = root / source_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(source_text, encoding="utf-8")
        metrics, logs = discover_sites(root)
        sites = [*metrics, *logs]
        document = {
            "schema_version": 1,
            "source_contexts": [
                {
                    "path": path,
                    "scope": scope,
                    "context_sha256": context_sha256,
                }
                for (path, scope), context_sha256 in sorted({
                    (row["path"], row["scope"]): row["context_sha256"]
                    for row in sites
                }.items())
            ],
            "metric_sites": [
                {
                    **{key: value for key, value in row.items() if key != "context_sha256"},
                    "classification": "gameplay-journal",
                    "proposed_journal_reason": "fixture.event",
                    "event_rate": "bounded",
                    "rationale": "fixture",
                }
                for row in metrics
            ],
            "audit_like_sites": [
                {
                    **{key: value for key, value in row.items() if key != "context_sha256"},
                    "classification": "operational/security-log",
                    "event_rate": "bounded",
                    "rationale": "fixture",
                }
                for row in logs
            ],
        }
        target = root / MANIFEST_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document), encoding="utf-8")
        return target

    def test_repository_inventory_is_exact_and_reviewed(self):
        report = load_and_validate(ROOT)
        self.assertEqual(26, report["metric_sites"])
        self.assertEqual(21, report["metric_identities"])
        self.assertEqual(19, report["audit_like_sites"])

    def test_unreviewed_metric_site_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = self._fixture(
                root,
                'player.MetricAdd("economy.new_action")\nLogger("fixture")\n',
            )
            document = json.loads(target.read_text(encoding="utf-8"))
            document["metric_sites"][0]["metric"] = "economy.other_action"
            target.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "inventory differs"):
                load_and_validate(root)

    def test_dynamic_metric_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text("player.MetricAdd(metric_name)\n", encoding="utf-8")
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "dynamic metric identity"):
                discover_sites(root)

    def test_metric_alias_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'emit = player.MetricAdd\nemit("economy.new_action")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "indirect metric method"):
                discover_sites(root)

    def test_metric_getattr_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'getattr(player, "MetricAdd")("economy.new_action")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_audit_log_alias_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'emit = guild.log_add\nemit("player text")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "indirect audit-log"):
                discover_sites(root)

    def test_audit_log_getattr_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'getattr(guild, "log_add")("player text")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_computed_metric_getattr_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'getattr(player, "Metric" + "Add")("economy.hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_dynamic_aliased_metric_getattr_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'subject = player\ngetattr(subject, f"{kind}Add")("economy.hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_metric_dict_reflection_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'player.__dict__["Metric" + "Add"]("economy.hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_metric_class_dict_reflection_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'player.__class__.__dict__["Metric" + "Add"]("economy.hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_aliased_getattr_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "lookup = getattr\nlookup(player, method)(\"economy.hidden\")\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reserved reflective"):
                discover_sites(root)

    def test_destructured_receiver_alias_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "subject, = (player,)\ngetattr(subject, method)(\"economy.hidden\")\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_getattribute_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "player.__getattribute__(method)(\"economy.hidden\")\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_aliased_vars_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "namespace = vars\nnamespace(player)[method](\"economy.hidden\")\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reserved reflective"):
                discover_sites(root)

    def test_imported_logger_alias_is_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'from Atrinik import Logger as emit\nemit("CHAT", player_text)\n',
                encoding="utf-8",
            )
            _, logs = discover_sites(root)
            self.assertEqual("Atrinik.Logger", logs[0]["facility"])

    def test_innocent_spelling_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text('label = "Logger"\n', encoding="utf-8")
            self.assertEqual(([], []), discover_sites(root))

    def test_qualified_logger_alias_is_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'import Atrinik as api\napi.Logger("INFO", "fixture")\n',
                encoding="utf-8",
            )
            _, logs = discover_sites(root)
            self.assertEqual("Atrinik.Logger", logs[0]["facility"])

    def test_atrinik_print_is_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'import Atrinik as api\nAtrinik.print("one")\napi.print("two")\n',
                encoding="utf-8",
            )
            _, logs = discover_sites(root)
            self.assertEqual(
                ["Python.print", "Python.print"],
                [row["facility"] for row in logs],
            )

    def test_qualified_builtin_reflection_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'import builtins as core\ncore.getattr(player, "MetricAdd")("hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "qualified reflective"):
                discover_sites(root)

    def test_imported_builtin_alias_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "from builtins import getattr as lookup\nlookup(player, method)(\"hidden\")\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reserved reflective"):
                discover_sites(root)

    def test_qualified_builtin_alias_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "import builtins\n"
                "lookup = builtins.getattr\n"
                'lookup(player, "MetricAdd")("hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reserved reflective"):
                discover_sites(root)

    def test_imported_operator_reflection_fails_closed(self):
        for callable_name in ("attrgetter", "methodcaller"):
            with self.subTest(
                callable_name=callable_name
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "maps" / "python" / "feature.py"
                source.parent.mkdir(parents=True)
                source.write_text(
                    "from operator import {} as reflect\n".format(callable_name),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ScriptedGameplayAuditError, "reserved reflective"):
                    discover_sites(root)

    def test_methodcaller_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'operator.methodcaller("MetricAdd", "hidden")(player)\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "attribute construction"):
                discover_sites(root)

    def test_starred_reflection_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'getattr(*(player, "MetricAdd"))("hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_object_dict_getattribute_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'object.__dict__["__getattribute__"]'
                '(player, "MetricAdd")("hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_dynamic_execution_is_reviewed_and_cannot_be_aliased(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text('eval("player.MetricAdd")\n', encoding="utf-8")
            _, logs = discover_sites(root)
            self.assertEqual("Python.eval", logs[0]["facility"])
            source.write_text('run = eval\nrun(payload)\n', encoding="utf-8")
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reserved reflective"):
                discover_sites(root)

    def test_qualified_dynamic_execution_is_reviewed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'import builtins as runtime\nruntime.eval("payload")\n',
                encoding="utf-8",
            )
            _, logs = discover_sites(root)
            self.assertEqual("Python.eval", logs[0]["facility"])

    def test_dynamic_and_print_attribute_aliases_fail_closed(self):
        for source_text in (
            "import Atrinik\nemit = Atrinik.print\n",
            "import builtins\nemit = builtins.print\n",
            "import builtins\nemit = builtins.eval\n",
            "from Atrinik import print as emit\n",
            "from Atrinik import Eval as emit\n",
            "from code import InteractiveConsole as Runner\n",
        ):
            with self.subTest(
                source_text=source_text
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "maps" / "python" / "feature.py"
                source.parent.mkdir(parents=True)
                source.write_text(source_text, encoding="utf-8")
                with self.assertRaisesRegex(
                    ScriptedGameplayAuditError,
                    "reserved audit|reserved reflective|reserved execution",
                ):
                    discover_sites(root)

    def test_additional_reflection_paths_fail_closed(self):
        for source_text in (
            'import builtins\ngetattr(builtins, "eval")("payload")\n',
            'getattr(player, "__getattribute__")("MetricAdd")\n',
            'import builtins\nvars(builtins)["eval"]("payload")\n',
            'import operator\noperator.__dict__["methodcaller"]("MetricAdd")\n',
            "lookup = globals().get\n",
            "namespace = globals()\n",
            "lookup, = (builtins.getattr,)\n",
            "from builtins import globals as namespace\n",
            "import builtins\nnamespace = builtins.globals\n",
            "import builtins\ngetattr(builtins, method)(payload)\n",
            "import builtins\nmodule = builtins\nlookup = module.getattr\n",
        ):
            with self.subTest(
                source_text=source_text
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "maps" / "python" / "feature.py"
                source.parent.mkdir(parents=True)
                source.write_text(source_text, encoding="utf-8")
                with self.assertRaises(ScriptedGameplayAuditError):
                    discover_sites(root)

    def test_builtin_module_alias_sites_are_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "import builtins\n"
                "runtime = builtins\n"
                "runtime.eval(payload)\n"
                "runtime.print(payload)\n",
                encoding="utf-8",
            )
            _, logs = discover_sites(root)
            self.assertEqual(
                ["Python.eval", "Python.print"],
                [row["facility"] for row in logs],
            )

    def test_destructured_privileged_module_aliases_are_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "import Atrinik, builtins, code\n"
                "runtime, = (builtins,)\n"
                "api, = (Atrinik,)\n"
                "engine, = (code,)\n"
                "runtime.eval(payload)\n"
                "api.print(payload)\n"
                "engine.InteractiveConsole.push(console, payload)\n",
                encoding="utf-8",
            )
            _, logs = discover_sites(root)
            self.assertEqual(
                [
                    "Python.eval",
                    "Python.print",
                    "Python.InteractiveConsole.push",
                ],
                [row["facility"] for row in logs],
            )

    def test_interactive_console_execution_is_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "import code as runtime\n"
                "runtime.InteractiveConsole.push(console, player_text)\n",
                encoding="utf-8",
            )
            _, logs = discover_sites(root)
            self.assertEqual(
                "Python.InteractiveConsole.push", logs[0]["facility"]
            )

    def test_namespace_get_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text('globals().get("Logger")("hidden")\n', encoding="utf-8")
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "namespace access"):
                discover_sites(root)

    def test_sensitive_receiver_rebinding_fails_closed(self):
        for source_text in (
            'subject = player\nsubject = cache\nsubject.MetricAdd("cache.hit")\n',
            'def bind():\n    subject = player\ndef reuse():\n    subject = cache\n    subject.MetricAdd("cache.hit")\n',
        ):
            with self.subTest(
                source_text=source_text
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "maps" / "python" / "feature.py"
                source.parent.mkdir(parents=True)
                source.write_text(source_text, encoding="utf-8")
                with self.assertRaisesRegex(ScriptedGameplayAuditError, "rebound telemetry"):
                    discover_sites(root)

    def test_guild_factory_alias_is_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'storage = Guild(name)\nstorage.log_add("fixture")\n',
                encoding="utf-8",
            )
            _, logs = discover_sites(root)
            self.assertEqual("Guild.log_add", logs[0]["facility"])

    def test_reserved_callable_shadowing_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'def helper(print):\n    print("ordinary callback")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "shadows a reserved"):
                discover_sites(root)

    def test_guild_receiver_rebinding_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'guild = cache\nguild.log_add("ordinary cache")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "rebinds the guild"):
                discover_sites(root)

    def test_print_alias_rebinding_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'emit = print\nemit = callback\nemit("ordinary callback")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "rebinds a print alias"):
                discover_sites(root)

    def test_reserved_metric_on_unreviewed_receiver_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'cache.MetricAdd("cache.hit")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "unreviewed receiver"):
                discover_sites(root)

    def test_unreviewed_log_add_receiver_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text('self.guild.log_add("fixture")\n', encoding="utf-8")
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "indirect audit-log"):
                discover_sites(root)

    def test_unbound_getattribute_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'object.__getattribute__(player, "MetricAdd")("hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_attrgetter_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'operator.attrgetter("MetricAdd")(player)("hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "attribute construction"):
                discover_sites(root)

    def test_builtins_dict_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'import builtins\nbuiltins.__dict__["print"]("hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_wrapped_receiver_reflection_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'getattr((player,)[0], method)("hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_typed_receiver_vars_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'vars(type(player))["MetricAdd"](player, "hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "reflective telemetry"):
                discover_sites(root)

    def test_builtin_namespace_subscription_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                '__builtins__["print"]("hidden")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "namespace access"):
                discover_sites(root)

    def test_globals_subscription_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text('globals()["Logger"]("hidden")\n', encoding="utf-8")
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "namespace access"):
                discover_sites(root)

    def test_imported_logger_alias_shadowing_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'from Atrinik import Logger as report\ndef run(report):\n    report("ordinary")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "shadows a reserved"):
                discover_sites(root)

    def test_unreviewed_logger_receiver_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text('cache.Logger("ordinary")\n', encoding="utf-8")
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "indirect audit-log"):
                discover_sites(root)

    def test_audit_facility_cannot_be_gameplay_journal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = self._fixture(
                root,
                'player.MetricAdd("economy.new_action")\nLogger("fixture")\n',
            )
            document = json.loads(target.read_text(encoding="utf-8"))
            document["audit_like_sites"][0]["classification"] = "gameplay-journal"
            target.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "operational or not recorded"):
                load_and_validate(root)

    def test_relocated_occurrence_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(
                root,
                'player.MetricAdd("economy.new_action")\nLogger("fixture")\n',
            )
            source = root / "maps" / "python" / "feature.py"
            source.write_text(
                'if committed:\n    player.MetricAdd("economy.new_action")\nLogger("fixture")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "inventory differs"):
                load_and_validate(root)

    def test_changed_surrounding_operation_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(
                root,
                'charge()\nplayer.MetricAdd("economy.new_action")\nLogger("fixture")\n',
            )
            source = root / "maps" / "python" / "feature.py"
            source.write_text(
                'debit()\nplayer.MetricAdd("economy.new_action")\nLogger("fixture")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "inventory differs"):
                load_and_validate(root)

    def test_audit_like_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(
                root,
                'player.MetricAdd("economy.new_action")\nLogger("fixture")\n',
            )
            source = root / "maps" / "python" / "feature.py"
            source.write_text(
                'player.MetricAdd("economy.new_action")\nLogger("fixture")\nLogger("new")\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "inventory differs"):
                load_and_validate(root)

    def test_map_local_script_is_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(
                root,
                'player.MetricAdd("economy.new_action")\nLogger("fixture")\n',
                "maps/area/scripts/feature.py",
            )
            report = load_and_validate(root)
            self.assertEqual(1, report["metric_sites"])
            self.assertEqual(1, report["audit_like_sites"])

    def test_proposed_reason_is_ascii_and_bounded(self):
        for invalid in ("player supplied text", "x." + "y" * 254, "fixture.évent"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = self._fixture(
                    root,
                    'player.MetricAdd("economy.new_action")\nLogger("fixture")\n',
                )
                fixture = json.loads(target.read_text(encoding="utf-8"))
                fixture["metric_sites"][0]["proposed_journal_reason"] = invalid
                target.write_text(json.dumps(fixture), encoding="utf-8")
                with self.assertRaisesRegex(
                    ScriptedGameplayAuditError, "bounded ASCII|invalid or exceeds"
                ):
                    load_and_validate(root)

    def test_backslash_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = self._fixture(
                root,
                'player.MetricAdd("economy.new_action")\nLogger("fixture")\n',
            )
            document = json.loads(target.read_text(encoding="utf-8"))
            document["metric_sites"][0]["path"] = "maps/python/..\\outside.py"
            target.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "canonical POSIX"):
                load_and_validate(root)


if __name__ == "__main__":
    unittest.main()

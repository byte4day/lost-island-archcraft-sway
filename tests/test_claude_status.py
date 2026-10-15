import json
import os
import tempfile
import unittest
from unittest.mock import patch

from lostisland import claude_setup
from lostisland.claude_status_hook import state_for, tool_detail
from lostisland.services.claude_status import (DONE_SECONDS, ancestors,
                                               visible_sessions,
                                               window_for_pid)


class HookTests(unittest.TestCase):
    def test_prompt_means_thinking(self):
        self.assertEqual(state_for({"hook_event_name": "UserPromptSubmit"}),
                         ("thinking", "Thinking"))

    def test_bash_shows_its_description(self):
        self.assertEqual(
            tool_detail("Bash", {"command": "npm test",
                                 "description": "Run tests"}), "Run tests")

    def test_file_tools_show_the_file_name(self):
        self.assertEqual(tool_detail("Edit", {"file_path": "/a/b/app.py"}),
                         "Edit app.py")

    def test_permission_prompt_needs_the_user(self):
        state = state_for({
            "hook_event_name": "Notification",
            "notification_type": "permission_prompt",
            "message": "Claude needs your permission to use Bash"})
        self.assertEqual(state, ("needs", "Allow Bash?"))

    def test_idle_notification_is_ignored(self):
        self.assertIsNone(state_for({
            "hook_event_name": "Notification",
            "message": "Claude is waiting for your input"}))

    def test_stop_and_end(self):
        self.assertEqual(state_for({"hook_event_name": "Stop"})[0], "done")
        self.assertEqual(state_for({"hook_event_name": "SessionEnd"})[0],
                         "ended")


class AggregateTests(unittest.TestCase):
    def test_needs_beats_working_beats_done(self):
        now = 1000.0
        sessions = [
            {"state": "done", "updated": now - 1},
            {"state": "tool", "updated": now - 2},
            {"state": "needs", "updated": now - 50},
        ]
        order = [s["state"] for s in visible_sessions(sessions, now)]
        self.assertEqual(order, ["needs", "tool", "done"])

    def test_done_expires(self):
        now = 1000.0
        sessions = [{"state": "done", "updated": now - DONE_SECONDS - 1},
                    {"state": "idle", "updated": now}]
        self.assertEqual(visible_sessions(sessions, now), [])

    def test_window_lookup_walks_up_the_process_tree(self):
        tree = {"id": 1, "nodes": [{"id": 7, "pid": os.getppid(),
                                    "nodes": []}]}
        self.assertIn(os.getpid(), ancestors(os.getpid()))
        self.assertEqual(window_for_pid(tree, os.getpid()), 7)


class SetupTests(unittest.TestCase):
    def test_merge_keeps_user_hooks_and_is_idempotent(self):
        user = {"hooks": {"Stop": [{"hooks": [{"type": "command",
                                               "command": "say done"}]}]}}
        cmd = "python3 /x/claude-status-hook.py"
        once = claude_setup.merge_status_hooks(json.loads(json.dumps(user)), cmd)
        twice = claude_setup.merge_status_hooks(json.loads(json.dumps(once)), cmd)
        self.assertEqual(once, twice)
        self.assertEqual(len(once["hooks"]["Stop"]), 2)
        self.assertEqual(once["hooks"]["PreToolUse"][0]["matcher"], "*")
        back = claude_setup.strip_status_hooks(twice)
        self.assertEqual(back, user)

    def test_install_backs_up_and_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = os.path.join(tmp, ".claude")
            os.makedirs(claude_dir)
            settings = os.path.join(claude_dir, "settings.json")
            with open(settings, "w") as f:
                json.dump({"model": "opus"}, f)
            with patch.object(claude_setup, "CLAUDE_DIR", claude_dir), \
                    patch.object(claude_setup, "SETTINGS", settings), \
                    patch.object(claude_setup, "STATUS_HOOK_DEST",
                                 os.path.join(tmp, "hook.py")), \
                    patch.object(claude_setup.config, "CONFIG_DIR", tmp):
                claude_setup.install_status()
            with open(settings) as f:
                data = json.load(f)
            self.assertEqual(data["model"], "opus")
            self.assertIn("SessionStart", data["hooks"])
            self.assertTrue(any(n.startswith("settings.json.bak-lostisland")
                                for n in os.listdir(claude_dir)))


if __name__ == "__main__":
    unittest.main()

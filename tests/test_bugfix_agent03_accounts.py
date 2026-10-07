# -*- coding: utf-8 -*-
"""Agent 03: offline account/profile regressions, with network blocked."""
from __future__ import annotations

import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mclauncher import auth, utils


class OfflineAccountTestCase(unittest.TestCase):
    def setUp(self):
        fixtures = ROOT.parent / ".zcode-bugfix" / "agent-03-local-tests"
        fixtures.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="case-", dir=fixtures)
        self.addCleanup(temporary.cleanup)
        self.accounts_path = Path(temporary.name) / "accounts.json"
        for patcher in (
            patch.object(auth, "ACCOUNTS_FILE", self.accounts_path),
            patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")),
            patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")),
            patch.object(auth, "_keyring_backend", return_value=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


class MicrosoftRefreshTests(OfflineAccountTestCase):
    def setUp(self):
        super().setUp()
        self.account = {
            "type": "microsoft", "name": "OldPlayer",
            "uuid": "11111111-1111-1111-1111-111111111111",
            "access_token": "unit-test-mc-old",
            "refresh_token": "unit-test-refresh-old",
            "expires_at": 0, "skin_model": "slim",
        }
        self.profile = {
            "name": "NewPlayer", "uuid": "22222222-2222-2222-2222-222222222222",
        }
        # Skip __init__: no requests.Session or external authentication exists.
        self.client = auth.MicrosoftAuthenticator.__new__(auth.MicrosoftAuthenticator)
        self.client.client_id = "unit-test-client"
        self.client.timeout = 1
        self.response = SimpleNamespace(status_code=200, json=Mock(return_value={
            "access_token": "unit-test-ms-new", "refresh_token": "unit-test-refresh-new",
        }))
        self.client.session = SimpleNamespace(post=Mock(return_value=self.response))
        self.client.xbl_authenticate = Mock(return_value="unit-test-xbl")
        self.client.xsts_authenticate = Mock(return_value=("unit-test-xsts", "unit-test-uhs"))
        self.client.mc_login = Mock(return_value="unit-test-mc-new")
        self.client.get_profile = Mock(return_value=self.profile)

    def test_refresh_updates_current_profile(self):
        actual = self.client.refresh(self.account)
        self.assertEqual(actual["name"], self.profile["name"])
        self.assertEqual(actual["uuid"], self.profile["uuid"])
        self.assertEqual(actual["access_token"], "unit-test-mc-new")
        self.assertEqual(actual["refresh_token"], "unit-test-refresh-new")
        self.client.get_profile.assert_called_once_with("unit-test-mc-new")

    def test_refresh_keeps_account_object_and_unrelated_fields(self):
        actual = self.client.refresh(self.account)
        self.assertIs(actual, self.account)
        self.assertEqual(actual["type"], "microsoft")
        self.assertEqual(actual["skin_model"], "slim")
        self.assertGreater(actual["expires_at"], actual["updated_at"])

    def test_missing_rotated_refresh_token_preserves_previous_token(self):
        self.response.json.return_value = {"access_token": "unit-test-ms-new"}
        self.assertEqual(self.client.refresh(self.account)["refresh_token"], "unit-test-refresh-old")

    def test_profile_failure_does_not_partially_update_account(self):
        before = dict(self.account)
        self.client.get_profile.side_effect = auth.AuthError("profile failed offline")
        with self.assertRaises(auth.AuthError):
            self.client.refresh(self.account)
        self.assertEqual(self.account, before)

    def test_token_failure_preserves_account_and_raises_auth_error(self):
        before = dict(self.account)
        self.response.status_code = 400
        with self.assertRaises(auth.AuthError):
            self.client.refresh(self.account)
        self.assertEqual(self.account, before)
        self.client.get_profile.assert_not_called()

    def test_missing_refresh_token_rejects_before_request(self):
        self.account["refresh_token"] = ""
        with self.assertRaises(auth.AuthError):
            self.client.refresh(self.account)
        self.client.session.post.assert_not_called()

    def test_current_identity_survives_save_reload_and_launch_props(self):
        manager = auth.AccountManager()
        manager.accounts = [self.account]
        manager.active = self.account["name"]
        current = self.client.refresh(self.account)
        # Synthetic tokens only; storage crypto has separate existing regressions.
        with patch.object(auth, "seal_account", side_effect=dict):
            manager.add_account(current)
        reloaded = auth.AccountManager()
        self.assertEqual(len(reloaded.accounts), 1)
        self.assertEqual(reloaded.active, "NewPlayer")
        self.assertIsNone(reloaded.get_account("OldPlayer"))
        properties = reloaded.launch_props(reloaded.get_active())
        self.assertEqual(properties["name"], self.profile["name"])
        self.assertEqual(properties["uuid"], self.profile["uuid"])
        self.assertEqual(properties["token"], "unit-test-mc-new")


class AccountFileShapeTests(OfflineAccountTestCase):
    def test_non_object_documents_load_as_empty(self):
        for document in ([{"name": "Player"}], "broken", 123, True):
            with self.subTest(document=document), patch.object(utils, "read_json", return_value=document):
                manager = auth.AccountManager()
                self.assertEqual(manager.accounts, [])
                self.assertIsNone(manager.get_active())

    def test_non_list_accounts_load_as_empty(self):
        for entries in (None, 123, True, "broken", {"Player": {"name": "Player"}}):
            with self.subTest(entries=entries), patch.object(utils, "read_json", return_value={"accounts": entries}):
                manager = auth.AccountManager()
                self.assertEqual(manager.accounts, [])
                self.assertIsNone(manager.get_active())

    def test_bad_entries_do_not_discard_valid_accounts(self):
        valid = {"type": "offline", "name": "Player", "uuid": utils.offline_uuid("Player")}
        document = {"active": "Player", "accounts": [None, "broken", 123, valid]}
        with patch.object(utils, "read_json", return_value=document):
            manager = auth.AccountManager()
        self.assertEqual(manager.accounts, [valid])
        self.assertEqual(manager.get_active(), valid)

    def test_malformed_documents_allow_adding_replacement_account(self):
        documents = ([{"name": "bad"}], "broken", {"accounts": None}, {"accounts": 123})
        for index, document in enumerate(documents):
            path = self.accounts_path.with_name(f"malformed-{index}.json")
            utils.write_json(path, document)
            with self.subTest(document=document), patch.object(auth, "ACCOUNTS_FILE", path):
                manager = auth.AccountManager()
                replacement = manager.offline_account("RecoveredPlayer")
                manager.add_account(replacement)
                self.assertEqual(auth.AccountManager().get_active(), replacement)
                persisted = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(persisted["accounts"], [replacement])

    def test_load_does_not_rewrite_bad_document(self):
        utils.write_json(self.accounts_path, {"accounts": None})
        before = self.accounts_path.read_bytes()
        manager = auth.AccountManager()
        self.assertEqual(manager.accounts, [])
        self.assertEqual(self.accounts_path.read_bytes(), before)

    def test_normal_account_roundtrip_and_active_removal(self):
        manager = auth.AccountManager()
        first = manager.offline_account("First")
        second = manager.offline_account("Second")
        manager.add_account(first)
        manager.add_account(second)
        manager.set_active("First")
        loaded = auth.AccountManager()
        self.assertEqual(loaded.accounts, [first, second])
        self.assertEqual(loaded.get_active(), first)
        loaded.remove_account("First")
        self.assertEqual(auth.AccountManager().get_active(), second)

    def test_missing_file_is_empty_without_creating_storage(self):
        manager = auth.AccountManager()
        self.assertEqual(manager.accounts, [])
        self.assertIsNone(manager.active)
        self.assertFalse(self.accounts_path.exists())


class AccountRefreshChainTests(OfflineAccountTestCase):
    class FakeKeyring:
        def __init__(self):
            self.values = {}

        def set_password(self, service, name, value):
            self.values[(service, name)] = value

        def get_password(self, service, name):
            return self.values.get((service, name))

        def delete_password(self, service, name):
            self.values.pop((service, name), None)

    def setUp(self):
        super().setUp()
        self.keys = self.FakeKeyring()
        for patcher in (
            patch.object(auth, "_keyring_backend", return_value=self.keys),
            # Exercise real keyring sealing logic without changing os.name on Windows.
            patch.object(auth, "seal_secret", side_effect=auth._store_in_keyring),
            patch.dict(sys.modules, {
                "mclauncher.config": SimpleNamespace(CONFIG={"microsoft_client_id": "unit-test-client"}),
            }),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.manager = auth.AccountManager()
        self.manager.add_account({
            "type": "microsoft", "name": "OldPlayer",
            "uuid": "11111111-1111-1111-1111-111111111111",
            "access_token": "unit-chain-mc-old",
            "refresh_token": "unit-chain-refresh-old", "expires_at": 0,
        })
        self.old_keyring_items = set(self.keys.values)
        self.account = self.manager.get_active()
        # Real MicrosoftAuthenticator.refresh with all network-facing methods mocked.
        self.client = auth.MicrosoftAuthenticator.__new__(auth.MicrosoftAuthenticator)
        self.client.client_id, self.client.timeout = "unit-test-client", 1
        self.response = SimpleNamespace(status_code=200, json=Mock(return_value={
            "access_token": "unit-chain-ms-new", "refresh_token": "unit-chain-refresh-new",
        }))
        self.client.session = SimpleNamespace(post=Mock(return_value=self.response))
        self.client.xbl_authenticate = Mock(return_value="unit-chain-xbl")
        self.client.xsts_authenticate = Mock(return_value=("unit-chain-xsts", "unit-chain-uhs"))
        self.client.mc_login = Mock(return_value="unit-chain-mc-new")
        self.client.get_profile = Mock(return_value={
            "name": "NewPlayer", "uuid": self.account["uuid"],
        })

    def _refresh(self):
        with patch.object(auth, "MicrosoftAuthenticator", return_value=self.client):
            return self.manager.ensure_valid(self.account)

    def test_renamed_active_account_survives_restart(self):
        refreshed = self._refresh()
        reloaded = auth.AccountManager()
        self.assertEqual(refreshed["name"], "NewPlayer")
        self.assertEqual(self.manager.active, "NewPlayer")
        self.assertEqual(reloaded.active, "NewPlayer")
        self.assertEqual(reloaded.get_active()["uuid"], self.account["uuid"])
        self.assertEqual(reloaded.get_active()["type"], "microsoft")
        self.assertEqual(len(reloaded.accounts), 1)
        self.assertIsNone(reloaded.get_account("OldPlayer"))

    def test_rename_deletes_old_keyring_items_but_preserves_current_tokens(self):
        self._refresh()
        self.assertFalse(self.old_keyring_items & set(self.keys.values))
        self.assertEqual(len(self.keys.values), 2)
        reloaded = auth.AccountManager().get_active()
        self.assertEqual(reloaded["access_token"], "unit-chain-mc-new")
        self.assertEqual(reloaded["refresh_token"], "unit-chain-refresh-new")

    def test_rename_preserves_unrotated_refresh_token(self):
        self.response.json.return_value.pop("refresh_token")
        self._refresh()
        self.assertEqual(len(self.keys.values), 2)
        reloaded = auth.AccountManager().get_active()
        self.assertEqual(reloaded["refresh_token"], "unit-chain-refresh-old")
        self.assertEqual(reloaded["access_token"], "unit-chain-mc-new")

    def test_same_name_refresh_cleans_old_tokens_and_remains_active(self):
        self.client.get_profile.return_value["name"] = "OldPlayer"
        self._refresh()
        self.assertFalse(self.old_keyring_items & set(self.keys.values))
        reloaded = auth.AccountManager()
        self.assertEqual(reloaded.active, "OldPlayer")
        self.assertEqual(len(reloaded.accounts), 1)
        self.assertEqual(reloaded.get_active()["access_token"], "unit-chain-mc-new")

    def test_rename_keeps_unrelated_account_and_current_refresh_selection(self):
        other = self.manager.offline_account("OtherPlayer")
        self.manager.add_account(other)
        self._refresh()
        reloaded = auth.AccountManager()
        self.assertEqual(len(reloaded.accounts), 2)
        self.assertEqual(reloaded.get_account("OtherPlayer"), other)
        self.assertEqual(reloaded.active, "NewPlayer")
        self.assertEqual(reloaded.get_active()["uuid"], self.account["uuid"])

    def test_name_collision_rejects_without_changing_active_accounts_or_storage(self):
        other = self.manager.offline_account("NewPlayer")
        self.manager.add_account(other)
        before_accounts = [dict(account) for account in self.manager.accounts]
        before_disk = self.accounts_path.read_bytes()
        before_keys = dict(self.keys.values)
        with self.assertRaises(auth.AuthError):
            self._refresh()
        self.assertEqual(self.manager.active, "NewPlayer")
        self.assertEqual(self.manager.get_active(), other)
        self.assertEqual(self.manager.accounts, before_accounts)
        self.assertEqual(self.accounts_path.read_bytes(), before_disk)
        self.assertEqual(self.keys.values, before_keys)
        reloaded = auth.AccountManager()
        self.assertEqual(reloaded.get_active(), other)
        self.assertEqual(len(reloaded.accounts), 2)

    def test_failed_profile_refresh_does_not_change_account_or_keyring(self):
        before_disk = self.accounts_path.read_bytes()
        before_keys = dict(self.keys.values)
        before_account = dict(self.account)
        self.client.get_profile.side_effect = auth.AuthError("offline profile failure")
        with self.assertRaises(auth.AuthError):
            self._refresh()
        self.assertEqual(self.account, before_account)
        self.assertEqual(self.accounts_path.read_bytes(), before_disk)
        self.assertEqual(self.keys.values, before_keys)
        self.assertEqual(self.manager.active, "OldPlayer")


if __name__ == "__main__":
    unittest.main()

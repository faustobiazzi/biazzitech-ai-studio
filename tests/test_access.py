import os
import unittest

from _env import clear_data

import access_control as access


class AccessTest(unittest.TestCase):
    def setUp(self):
        clear_data()
        access._sessions.clear()
        access._fails.clear()

    def test_port_rules(self):
        self.assertIsNotNone(access.validate_port(80))
        self.assertIsNotNone(access.validate_port(8080))
        self.assertIsNotNone(access.validate_port("abc"))
        self.assertIsNone(access.validate_port(59321))

    def test_no_users_is_free_only_on_this_pc(self):
        self.assertTrue(access.decide("chat", True, None)[0])
        self.assertTrue(access.decide("admin", True, None)[0])
        self.assertFalse(access.decide("chat", False, None)[0])
        self.assertFalse(access.decide("admin", False, None)[0])

    def test_lan_needs_a_user(self):
        access.set_config(lan=True)
        self.assertFalse(access.lan_effective())
        self.assertEqual(access._cli(["set", "lan", "true"]), 2)
        access.add_user("ana", "segredo1")
        self.assertTrue(access.lan_effective())
        self.assertEqual(access._cli(["set", "lan", "true"]), 0)
        self.assertIn("lan_risk_accepted", access.get_config())

    def test_https_needs_cert_and_key(self):
        st = access.https_status()
        self.assertFalse(st["ready"])
        self.assertEqual(st["port"], access.get_config()["port"] + 1)
        for name in ("cert.pem", "key.pem"):
            open(os.path.join(st["folder"], name), "w").close()
        self.assertTrue(access.https_status()["ready"])

    def test_login_is_logged(self):
        access.add_user("ana", "segredo1")
        access.login("ana", "errada", "5.5.5.5")
        access.login("ana", "segredo1", "5.5.5.5")
        with open(access._path("acessos.log"), encoding="utf-8") as f:
            log = f.read()
        self.assertIn("login_falhou\t5.5.5.5\tana", log)
        self.assertIn("login_ok\t5.5.5.5\tana", log)
        self.assertNotIn("segredo1", log)

    def test_first_user_is_admin_and_password_rules(self):
        self.assertFalse(access.add_user("ana", "123")[0])
        self.assertFalse(access.add_user("nome inválido!", "123456")[0])
        ok, _, token = access.add_user("ana", "segredo1", ["chat"])
        self.assertTrue(ok)
        self.assertTrue(token.startswith("btk_"))
        self.assertIn("admin", access.list_users()[0]["perms"])

    def test_login_session_and_token(self):
        _, _, token = access.add_user("ana", "segredo1")
        access.add_user("bia", "segredo2", ["imagens"])
        sess, msg = access.login("ana", "segredo1", "1.2.3.4")
        self.assertTrue(sess, msg)
        user = access.user_from_request(f"bt_session={sess}", None)
        self.assertEqual(user["name"], "ana")
        user = access.user_from_request(None, "Bearer " + token)
        self.assertEqual(user["name"], "ana")
        self.assertIsNone(access.user_from_request("bt_session=errado", None))

    def test_permissions_with_users(self):
        access.add_user("ana", "segredo1")
        access.add_user("bia", "segredo2", ["imagens"])
        bia = {"name": "bia", "perms": ["imagens"]}
        self.assertEqual(access.decide("chat", False, None), (False, "Faça login.", True))
        self.assertTrue(access.decide("imagens", False, bia)[0])
        self.assertFalse(access.decide("chat", False, bia)[0])
        self.assertTrue(access.decide("chat", True, None)[0])  # neste PC é livre (auth_local desligado)
        access.set_config(auth_local=True)
        self.assertFalse(access.decide("chat", True, None)[0])

    def test_brute_force_block(self):
        access.add_user("ana", "segredo1")
        for _ in range(access.MAX_FAILS):
            access.login("ana", "errada", "9.9.9.9")
        sess, msg = access.login("ana", "segredo1", "9.9.9.9")
        self.assertIsNone(sess)
        self.assertIn("tentativas", msg)

    def test_cannot_remove_last_admin(self):
        access.add_user("ana", "segredo1")
        access.add_user("bia", "segredo2", ["chat"])
        self.assertFalse(access.delete_user("ana")[0])
        self.assertFalse(access.update_user("ana", perms=["chat"])[0])


if __name__ == "__main__":
    unittest.main()

"""HTTPS de verdade: gera um certificado temporário com o openssl (se existir no PC) e conversa por TLS."""
import json
import os
import shutil
import ssl
import subprocess
import threading
import unittest
import urllib.request

from _env import TMP, clear_data

import access_control as access
import studio_server


def find_openssl():
    found = shutil.which("openssl")
    if found:
        return found
    for p in (r"C:\Program Files\Git\usr\bin\openssl.exe", r"C:\Program Files\Git\mingw64\bin\openssl.exe"):
        if os.path.isfile(p):
            return p
    return None


OPENSSL = find_openssl()


@unittest.skipUnless(OPENSSL, "openssl não encontrado")
class HttpsTest(unittest.TestCase):
    def setUp(self):
        clear_data()
        self.cert = os.path.join(TMP, "cert.pem")
        self.key = os.path.join(TMP, "key.pem")
        subprocess.run([OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
                        "-keyout", self.key, "-out", self.cert], check=True, capture_output=True, timeout=60)

    def test_tls_and_secure_cookie(self):
        httpd = studio_server.make_https_server("127.0.0.1", 0, self.cert, self.key)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            base = f"https://127.0.0.1:{httpd.server_port}"
            with urllib.request.urlopen(base + "/healthz", context=ctx, timeout=10) as r:
                self.assertEqual(json.loads(r.read())["app"], "biazzitech")
            access.add_user("ana", "segredo1")
            req = urllib.request.Request(base + "/api/auth/login", data=json.dumps({"user": "ana", "password": "segredo1"}).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
                self.assertIn("Secure", r.headers.get("Set-Cookie"))
            # HTTP sem TLS na porta HTTPS não funciona
            with self.assertRaises(Exception):
                urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/healthz", timeout=5).read()
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()

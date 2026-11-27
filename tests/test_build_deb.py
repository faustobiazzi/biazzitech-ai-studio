"""Pacote .deb: estrutura que o dpkg espera, control, permissões e arquivos do app (sem precisar de Linux)."""
import io
import os
import tarfile
import tempfile
import unittest

from _env import ROOT  # noqa: F401  (põe o projeto no sys.path)

import build_deb


def read_ar(raw):
    assert raw[:8] == b"!<arch>\n"
    pos, members = 8, []
    while pos < len(raw):
        h = raw[pos:pos + 60]
        size = int(h[48:58].decode().strip())
        members.append((h[:16].decode().strip(), raw[pos + 60:pos + 60 + size]))
        pos += 60 + size + (size % 2)
    return members


class BuildDebTest(unittest.TestCase):
    def test_package(self):
        path, count = build_deb.build("9.9.9", tempfile.mkdtemp())
        self.assertTrue(path.endswith("biazzitech-ai-studio_9.9.9_all.deb"))
        members = dict(read_ar(open(path, "rb").read()))
        self.assertEqual(list(members), ["debian-binary", "control.tar.gz", "data.tar.gz"])
        self.assertEqual(members["debian-binary"], b"2.0\n")
        ctl = tarfile.open(fileobj=io.BytesIO(members["control.tar.gz"]))
        control = ctl.extractfile("./control").read().decode()
        self.assertIn("Version: 9.9.9", control)
        self.assertIn("Architecture: all", control)
        self.assertIn("Depends: python3", control)
        data = tarfile.open(fileobj=io.BytesIO(members["data.tar.gz"]))
        names = set(data.getnames())
        for must in ("./usr/bin/biazzitech-studio", "./usr/lib/biazzitech-ai-studio/studio_server.py",
                     "./usr/lib/biazzitech-ai-studio/ui/studio.js", "./usr/share/applications/biazzitech-ai-studio.desktop",
                     "./usr/share/icons/hicolor/512x512/apps/biazzitech-ai-studio.png"):
            self.assertIn(must, names)
        self.assertEqual(data.getmember("./usr/bin/biazzitech-studio").mode, 0o755)
        self.assertNotIn("./usr/lib/biazzitech-ai-studio/build_deb.py", names)
        self.assertFalse(any(n.endswith((".ps1", ".bat")) for n in names))
        for n in names:
            if n.endswith(".py"):
                self.assertNotIn(b"\r\n", data.extractfile(n).read(), n)
        # md5sums cobre todos os arquivos instalados
        md5 = ctl.extractfile("./md5sums").read().decode().splitlines()
        self.assertEqual(len(md5), count)
        os.remove(path)


if __name__ == "__main__":
    unittest.main()

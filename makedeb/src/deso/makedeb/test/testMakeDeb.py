# testMakeDeb.py

#/***************************************************************************
# *   Copyright (C) 2018 Daniel Mueller (deso@posteo.net)                   *
# *                                                                         *
# *   This program is free software: you can redistribute it and/or modify  *
# *   it under the terms of the GNU General Public License as published by  *
# *   the Free Software Foundation, either version 3 of the License, or     *
# *   (at your option) any later version.                                   *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU General Public License for more details.                          *
# *                                                                         *
# *   You should have received a copy of the GNU General Public License     *
# *   along with this program.  If not, see <http://www.gnu.org/licenses/>. *
# ***************************************************************************/

"""Test module for the makedeb package."""

from deso.makedeb import (
  makeDeb,
)
# We also test some private functionality.
from deso.makedeb.makedeb import (
  _copyContent,
  _getInstallSize,
  _makeControl,
  _makeControlTar,
  cwd,
)
from hashlib import (
  md5,
)
from os import (
  access,
  chmod,
  fsync,
  mkdir,
  R_OK,
  W_OK,
  X_OK,
)
from os.path import (
  isfile,
  join,
)
from subprocess import (
  check_call,
  DEVNULL,
)
from tarfile import (
  open as tarOpen,
)
from tempfile import (
  NamedTemporaryFile,
  TemporaryDirectory,
)
from textwrap import (
  dedent,
)
from unittest import (
  TestCase,
  main,
)


class TestMakeDeb(TestCase):
  """A test case for testing of the makedeb package."""
  def testInstallSizeRetrieval(self):
    """Test retrieval of installation size."""
    with TemporaryDirectory() as d:
      with open(join(d, "foo"), "w+") as f:
        f.write(20 * "a")

      with open(join(d, "bar"), "w+") as f:
        f.write(10 * "b")

      d2 = join(d, "foobar")
      mkdir(d2)

      with open(join(d2, "baz"), "w+") as f:
        f.write(35 * "b")

      # We wrote a total of 65 bytes. That's what should be reported.
      self.assertEqual(_getInstallSize(d), 65)


  def testCopyContentAbsolute(self):
    """Verify that we cannot use absolute content paths."""
    path = "/usr/lib64/test.so"
    regex = "\(%s\) must not be absolute" % path

    with TemporaryDirectory() as d:
      with self.assertRaisesRegex(RuntimeError, regex):
        content = [
          ("foo/bar", path),
        ]
        _copyContent(content, d)


  def testCopyContentRegularFile(self):
    """Test copy of a regular file."""
    for dst in ("f2", "some/destination/dir/f2"):
      with TemporaryDirectory() as d:
        data = "hello"
        f1 = join(d, "f1")
        f2 = join(d, dst)

        with open(f1, "w+") as f:
          f.write(data)

        content = [(f1, dst)]
        _copyContent(content, d)

        with open(f2, "r") as f:
          self.assertEqual(f.read(), data)


  def testCopyContentRegularFilePermissions(self):
    """Test copy of a regular file."""
    with TemporaryDirectory() as d:
      data = "hello"
      f1 = join(d, "f1")
      f2 = join(d, "f2")

      with open(f1, "w+") as f:
        f.write(data)

      chmod(f1, 0o401)

      content = [(f1, "f2")]
      _copyContent(content, d)

      with open(f2, "r") as f:
        self.assertEqual(f.read(), data)

      self.assertTrue(access(f2, R_OK | W_OK | X_OK))


  def testCopyContentDirectory(self):
    """Test copy of a directory."""
    for dst in ("d2", "usr/local/share/d2"):
      with TemporaryDirectory() as d:
        data = "mydata"
        d1 = join(d, "d1")
        mkdir(d1)

        with open(join(d, "d1", "foobar"), "w+") as f:
          f.write(data)
        with open(join(d, "d1", "baz"), "w+") as f:
          f.write(data)

        content = [(d1, dst)]
        _copyContent(content, d)

        with open(join(d, dst, "foobar"), "r") as f:
          self.assertEqual(f.read(), data)
        with open(join(d, dst, "baz"), "r") as f:
          self.assertEqual(f.read(), data)


  def testControlFileLongDescription(self):
    """Test that the long description in the control file is formatted properly."""
    with NamedTemporaryFile("r+") as ctrl:
      _makeControl(ctrl.name, "test", "0.1", 0)
      content = ctrl.read()
      self.assertTrue(content.endswith("Description: None\n"))

    with NamedTemporaryFile("r+") as ctrl:
      long_desc = """\
This is a long description for test that spans
multiple lines and timezones.

And here is even more\
"""

      _makeControl(ctrl.name, "test", "0.1", 0, long_desc=long_desc)
      content = ctrl.read()
      expected = dedent("""\
      Description: None
       This is a long description for test that spans
       multiple lines and timezones.
       .
       And here is even more
      """)
      self.assertTrue(content.endswith(expected))


  def testAdditionalControlFileSupport(self):
    """Test that we support adding of other control files properly."""
    with NamedTemporaryFile("w+") as preinst, \
         NamedTemporaryFile("w+") as postrm:
      preinst.write(dedent("""\
        #!/bin/sh
        echo preinst
      """))
      postrm.write(dedent("""\
        #!/bin/sh
        echo postrm
      """))
      preinst.flush()
      postrm.flush()
      fsync(preinst)
      fsync(postrm)

      with TemporaryDirectory() as pkg:
        debian = join(pkg, "DEBIAN")
        mkdir(debian)

        control_files = [
          (preinst.name, "preinst"),
          (postrm.name, "postrm"),
        ]
        _makeControlTar(debian, control_files, pkg)

        with cwd(pkg):
          with tarOpen("control.tar.gz", "r") as f:
            members = f.getmembers()
            self.assertEqual(len(members), 3)
            self.assertEqual(members[0].name, ".")
            self.assertEqual(members[1].name, "./preinst")
            self.assertEqual(members[2].name, "./postrm")


  def inspect(self, deb):
    """Perform a couple of check on the given .deb file."""
    with TemporaryDirectory() as tmp:
      with cwd(tmp):
        check_call(["ar", "x", deb], stdout=DEVNULL, stderr=DEVNULL)

        self.assertTrue(isfile("debian-binary"))
        self.assertTrue(isfile("control.tar.gz"))
        self.assertTrue(isfile("data.tar.xz"))

        with open("debian-binary", "rb") as f:
          self.assertEqual(f.read(), b"2.0\x0a")

        with tarOpen("data.tar.xz", "r") as f:
          members = f.getmembers()
          self.assertEqual(members[0].name, ".")
          self.assertEqual(members[1].name, "./etc")
          self.assertEqual(members[2].name, "./etc/conf")
          self.assertEqual(members[3].name, "./usr")
          self.assertEqual(members[4].name, "./usr/file")
          self.assertEqual(members[4].uname, "root")
          self.assertEqual(members[4].gname, "root")
          self.assertEqual(members[5].name, "./usr/dir")
          self.assertEqual(members[6].name, "./usr/dir/file")
          self.assertEqual(len(members), 7)

        with tarOpen("control.tar.gz", "r") as f:
          members = f.getmembers()
          self.assertEqual(members[0].name, ".")
          self.assertEqual(members[1].name, "./md5sums")
          md5sums = f.extractfile(members[1])
          md5sum = md5(b"testfile1").hexdigest()
          self.assertIn("%s  %s" % (md5sum, "usr/file"), md5sums.read().decode())

          self.assertEqual(members[2].name, "./control")
          control = f.extractfile(members[2]).read().decode()
          self.assertTrue(control.startswith("Package: helloworld"))
          self.assertIn("Version: 0.1", control)
          self.assertIn("Maintainer: None", control)
          self.assertIn("Installed-Size: 1", control)
          self.assertTrue(control.endswith("Description: None\n"))


  def testMakeDeb(self):
    """Test creation of a .deb file and examine the contents."""
    with TemporaryDirectory() as usr_root, \
         TemporaryDirectory() as etc_root:
      with open(join(usr_root, "file"), "w+") as f:
        f.write("testfile1")

      d = join(usr_root, "dir")
      mkdir(d)

      with open(join(d, "file"), "w+") as f:
        f.write("testfile2")

      d = join(etc_root, "dir1")
      mkdir(d)

      with open(join(d, "conf"), "w+") as f:
        f.write("config")

      content = [
        (usr_root, "usr"),
        (join(etc_root, "dir1", "conf"), join("etc", "conf")),
      ]
      outfile = makeDeb("helloworld", "0.1", content, outdir=usr_root)

      self.assertEqual(outfile, join(usr_root, "helloworld-0.1.deb"))

      self.inspect(outfile)


if __name__ == "__main__":
  main()

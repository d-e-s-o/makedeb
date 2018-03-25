# makedeb.py

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

from contextlib import (
  contextmanager,
)
from hashlib import (
  md5,
)
from math import (
  ceil,
)
from os import (
  chdir,
  chmod,
  getcwd,
  makedirs,
  mkdir,
  stat,
  walk,
)
from os.path import (
  curdir,
  dirname,
  getsize,
  isabs,
  isdir,
  join,
  relpath,
)
from shutil import (
  copy2,
  copytree,
)
from stat import (
  S_IXGRP,
  S_IXOTH,
  S_IXUSR,
)
from subprocess import (
  check_call,
  DEVNULL,
)
from tarfile import (
  open as tarOpen,
)
from tempfile import (
  TemporaryDirectory,
)

# The content requires a trailing newline, otherwise dpkg will error
# out:
# > dpkg-deb: error: archive has no newlines in header
# We do not want Python to potentially mess around with \n (which can
# mean different things on different platforms), so just embed the byte
# value directly.
DEB_VERSION = "2.0\x0a"
CONTROL = """\
Package: {name}
Version: {version}
Architecture: all
Maintainer: {maintainer}
Installed-Size: {size}
Pre-Depends: dpkg (>= 1.15.6~)
Depends: {depends}
Priority: optional
Homepage: {homepage}
Description: {short_desc}
{long_desc}\
"""


@contextmanager
def cwd(path):
  """Change the working directory and revert the change after continuing."""
  previous = getcwd()
  chdir(path)
  try:
    yield
  finally:
    chdir(previous)


def _getInstallSize(pkg):
  """Get the install size of the given package."""
  size = 0
  for root, _, files in walk(pkg):
    for file_ in files:
      size += getsize(join(root, file_))

  return size


def _normalizeFileMode(file_):
  """Normalize the mode for the given file."""
  s = stat(file_)
  exe = (s.st_mode & S_IXUSR) or (s.st_mode & S_IXGRP) or (s.st_mode & S_IXOTH)
  # If anybody has execute access we extend that to everybody.
  mode = 0o755 if exe else 0o644
  chmod(file_, mode)


def _normalizeMode(dir_):
  """Normalize the mode for all files/directories below the given directory.

    We use a heuristic approach here instead of specifying everything.
    If the file is executable for anyone we make it executable for
    everyone. If it is readable we make it readable for everyone. If it
    is writable we make it writable only for the owner (which will
    eventually be root).
  """
  for root, _, files in walk(dir_):
    # Directories always have executable access and are owner writable.
    chmod(root, 0o755)

    for file_ in files:
      _normalizeFileMode(join(root, file_))


def _copyContent(content, pkg_root, ignore=None):
  """Copy the content into the deb package root."""
  for src, dst in content:
    # Specifying an absolute path would break the copytree result as the
    # result of a join of two absolute paths is the last absolute path.
    if isabs(dst):
      raise RuntimeError("Destination path (%s) must not be absolute" % dst)

    dst = join(pkg_root, dst)
    if isdir(src):
      copytree(src, dst, ignore=ignore)
      _normalizeMode(dst)
    else:
      # copy2 does not automatically create all directories up to the
      # destination file.
      makedirs(dirname(dst), exist_ok=True)
      copy2(src, dst)
      # TODO: We currently punt on fixing up the directories potentially
      #       created above via makedirs. They will have the users mode
      #       mask applied.
      _normalizeFileMode(dst)


def _makeControl(control, name, version, install_size,
                 dependencies=None, maintainer=None, homepage=None,
                 short_desc=None, long_desc=None):
  """Write out the control."""
  # The size is supposed to be in KiB.
  install_size = ceil(install_size / 1024)

  if dependencies is None:
    dependencies = []

  if long_desc is None:
    long_desc = ""
  else:
    # Replace empty lines with a dot. Required by the format.
    long_desc = map(lambda x: "." if x == "" else x, long_desc.splitlines())
    # Indent all lines in the description by one space. Yet another
    # requirement.
    long_desc = "\n".join(map(lambda x: " " + x, long_desc)) + "\n"

  with open(control, "w+") as ctrl:
    depends = ", ".join(dependencies)
    content = CONTROL.format(name=name, version=version,
                             maintainer=maintainer, homepage=homepage,
                             size=install_size, depends=depends,
                             short_desc=short_desc, long_desc=long_desc)
    ctrl.write(content)


def _md5File(file_):
  """Create the md5 checksum of the given file."""
  with open(file_, "rb") as f:
    return md5(f.read()).hexdigest()


def _makeMd5Sums(md5sums, pkg, exclude):
  """Create an md5sums file containing checksums of all packaged files."""
  with open(md5sums, "w+") as md5sums:
    for root, _, files in walk(pkg):
      if root.endswith(exclude):
        continue

      for file_ in files:
        file_ = join(root, file_)
        chksum = _md5File(file_)
        path = relpath(file_, pkg)
        md5sums.write("{chksum}  {path}\n".format(chksum=chksum, path=path))


def _chownTarInfo(tar_info):
  """Adjust ownership information of the given tar info object."""
  tar_info.uname = "root"
  tar_info.gname = "root"
  return tar_info


def _makeDebBinary(pkg_root):
  path = join(pkg_root, "debian-binary")
  with open(path, "w+") as f:
    # The current version Debian uses.
    f.write(DEB_VERSION)

  return path


def _makeControlTar(debian, control_files, pkg_root):
  """Create a control.tar.gz containing all the DEBIAN files."""
  path = join(pkg_root, "control.tar.gz")
  with tarOpen(path, "x:gz") as control:
    with cwd(debian):
      control.add(curdir, filter=_chownTarInfo)

    if control_files is not None:
      for src, dst in control_files:
        if isabs(dst):
          raise RuntimeError("Destination path (%s) must not be absolute" % dst)

        # We could impose additional checks on the source/destination
        # files here. E.g., using a directory as a source or placing a
        # file not in the root are unlikely to make much sense. However,
        # we do not want to get into too much business of enforcing
        # policies. A whitelist-style approach (check for things
        # allowed, deny everything else) does not seem very future proof
        # while a blacklist based method is prone to missing certain
        # bits.
        control.add(src, arcname=join(curdir, dst), filter=_chownTarInfo)

  return path


def _makeDataTar(content, pkg_root):
  """Create a data.tar.xz containing all the data."""
  path = join(pkg_root, "data.tar.xz")
  with tarOpen(path, "x:xz") as data:
    with cwd(pkg_root):
      for _, dst in content:
        data.add(dst, filter=_chownTarInfo)

  return path


def _makeDebPkg(outfile, debian, control_files, content, pkg_root):
  """Create a .deb package."""
  deb_bin = _makeDebBinary(pkg_root)
  control = _makeControlTar(debian, control_files, pkg_root)
  data = _makeDataTar(content, pkg_root)

  # Python does not seem to have support for ar(1)-style archives by
  # default, so we have to fall back to using the system's `ar`. Note
  # that the order of files in the archive is important.
  check_call(["ar", "r", outfile, deb_bin, control, data],
             stdout=DEVNULL, stderr=DEVNULL)


def makeDeb(pkg_name, version, content, control_files=None, outdir=None,
            ignore=None, dependencies=None, maintainer=None,
            homepage=None, short_desc=None, long_desc=None):
  """Create a .deb package.

  `pkg_name` is an arbitrary name of the resulting package. This name
    will be used both as the file name but also as the name specified
    inside the package's meta data.
  `version` represents the version of the package. Typically that should
    be a semantic version but the string is not interpreted by us.
  `content` is an iterable of (src, dst) pairs. Both the source and the
    destination may be directories, which will be copied recursively.
  `control_files` is an iterable of (str, dst) pairs describing
    additional control files to include in the package. Examples of
    such a files include preinst and postinst scripts.
  `outdir` specifies the output directory. If its value is None the
    current directory will be used.
  `ignore` is a shutil.copytree style ignore function that can be used
    to filter out files matching a pattern and exclude them from
    entering into the package.
  `maintainer` represents the optional name(s) of the maintainer(s). It
    is a free form string and as such can contain additional data such
    as email addresses.
  `homepage` is the optional URL to the project's home page.
  `short_desc` is an optional short (i.e., single line) description.
  `long_desc` is an optional long (multi line) description.
  `dependencies` is an optional iterable of dependencies. Currently we
    do not allow for specifying specific versions. Only package names
    are supported.
  """
  # A .deb package is an ar(1)-style archive with the following
  # structure:
  # ├── debian-binary
  # ├── control.tar.gz
  # └── data.tar.xz
  #
  # `debian-binary` is a file specifying the deb version to use. Version
  # 2.0 is the current one as of 2018.
  #
  # `control.tar.gz` is a gzipped tar archive containing:
  # └── DEBIAN
  #     ├── control
  #     ├── md5sums [optional]
  #     ├── conffiles [optional]
  #     ├── preinst, postinst, prerm and postrm [optional]
  #     ├── config [optional]
  #     └── shlib [optional]
  #
  # We only support and make use of the `control` and `md5sums` files.
  #
  # `data.tar.xz` is a xz compressed (other compression formats are
  # supported) tar archive that contains the actual data that is to be
  # installed. Paths are treated as relative to the root directory.

  with TemporaryDirectory() as pkg:
    # TODO: Strictly speaking we could get away without copying the
    #       content and adding it to the tar directly. The problem then
    #       is how to determine the install size.
    _copyContent(content, pkg, ignore=ignore)
    # Note that we retrieve the size before creating any of the
    # additional meta data. That simplifies the logic because we don't
    # have to exclude anything.
    install_size = _getInstallSize(pkg)

    debian = join(pkg, "DEBIAN")
    mkdir(debian)

    kwargs = {
      "dependencies": dependencies,
      "maintainer": maintainer,
      "homepage": homepage,
      "short_desc": short_desc,
      "long_desc": long_desc,
    }
    _makeControl(join(debian, "control"), pkg_name, version, install_size, **kwargs)
    _makeMd5Sums(join(debian, "md5sums"), pkg, exclude="DEBIAN")

    if outdir is None:
      outdir = curdir

    outfile = join(outdir, "%s-%s.deb" % (pkg_name, version))
    _makeDebPkg(outfile, debian, control_files, content, pkg)
    return outfile

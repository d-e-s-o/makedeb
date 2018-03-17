makedeb
=======

The **makedep** package provides the necessary infrastructure to create
.deb packages in an automated fashion from within Python. Such packages
are used for bundling and installing software on various Linux
distributions, e.g., Debian and Ubuntu. The package's goal is solely to
provide the functionality for creating packages. It does not prescribe
the resulting layout of files in the file system, when such a package is
installed. This knowledge is generally distribution specific and needs
to be handled in a per package basis.

The module's interface is designed to be minimalistic, asking only for
strictly required inputs. E.g.,

```python
>>> from deso.makedeb import makeDeb
>>> content = [
...   ("src/", "usr/lib/python3/dist-packages/"),
... ]
>>> makeDeb("python3-cleanup", "0.2", content, homepage="https://github.com/d-e-s-o/cleanup")
'./python3-cleanup-0.2.deb'
```

Additional input parameters such as a list of dependencies and the name of
the maintainer are supported and will cause this data to be embedded
into the resulting package in the form of meta data.


Installation
------------

The **makedep** package does not have any external dependencies aside
from Python itself and the `ar` program (see ar(1)). In order to use the
package it only needs to be made known to Python, e.g., by adding the
path to the ``src/`` directory to the ``PYTHONPATH`` environment
variable.


Support
-------

The module is tested with Python 3. There is no work going on to
ensure compatibility with Python 2.

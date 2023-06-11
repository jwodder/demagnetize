.. image:: http://www.repostatus.org/badges/latest/wip.svg
    :target: http://www.repostatus.org/#wip
    :alt: Project Status: WIP — Initial development is in progress, but there
          has not yet been a stable, usable release suitable for the public.

.. image:: https://github.com/jwodder/demagnetize/workflows/Test/badge.svg?branch=master
    :target: https://github.com/jwodder/demagnetize/actions?workflow=Test
    :alt: CI Status

.. image:: https://codecov.io/gh/jwodder/demagnetize/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/jwodder/demagnetize

.. image:: https://img.shields.io/github/license/jwodder/demagnetize.svg
    :target: https://opensource.org/licenses/MIT
    :alt: MIT License

`GitHub <https://github.com/jwodder/demagnetize>`_
| `Issues <https://github.com/jwodder/demagnetize/issues>`_

``demagnetize`` is a Python program for converting one or more BitTorrent
`magnet links`_ into ``.torrent`` files by downloading the torrent info from
active peers.

.. _magnet links: https://en.wikipedia.org/wiki/Magnet_URI_scheme

At the moment, ``demagnetize`` only supports basic features of the BitTorrent
protocol.  The following notable features are supported:

- BitTorrent protocol v1
- HTTP and UDP trackers
- magnet URIs with info hashes encoded in either hexadecimal (btih) or base32
  (btmh)

The following features are not currently supported but are planned, in no
particular order:

- Encryption
- Distributed hash tables
- BitTorrent protocol v2
- UDP tracker protocol extensions (`BEP 41`_)
- uTP (possibly)

.. _BEP 41: https://www.bittorrent.org/beps/bep_0041.html


Installation
============
``demagnetize`` requires Python 3.10 or higher.  Just use `pip
<https://pip.pypa.io>`_ for Python 3 (You have pip, right?) to install it::

    python3 -m pip install git+https://github.com/jwodder/demagnetize.git


Usage
=====

::

    demagnetize [<global options>] <subcommand> ...

The ``demagnetize`` command has two subcommands, ``get`` (for converting a
single magnet link) and ``batch`` (for converting a file of magnet links), both
detailed below.

Global Options
--------------

-l LEVEL, --log-level LEVEL
                        Set the log level to the given value.  Possible values
                        are "``CRITICAL``", "``ERROR``", "``WARNING``",
                        "``INFO``", "``DEBUG``", and "``TRACE``" (all
                        case-insensitive).  [default value: ``INFO``]


``demagnetize get``
-------------------

::

    demagnetize [<global options>] get [<options>] <magnet-link>

Convert a single magnet link specified on the command line to a ``.torrent``
file.  (Note that you will likely have to quote the link in order to prevent it
from being interpreted by the shell.)  By default, the file is saved at
``{name}.torrent``, where ``{name}`` is replaced by the value of the ``name``
field from the torrent info, but a different path can be set via the
``--outfile`` option.

Options
^^^^^^^

-o PATH, --outfile PATH
                        Save the ``.torrent`` file to the given path.  The path
                        may contain a ``{name}`` placeholder, which will be
                        replaced by the name of the torrent, and/or a
                        ``{hash}`` placeholder, which will be replaced by the
                        torrent's info hash in hexadecimal.  [default:
                        ``{name}.torrent``]


``demagnetize batch``
---------------------

::

    demagnetize [<global options>] batch [<options>] <file>

Read magnet links from ``<file>``, one per line (ignoring empty lines and lines
that start with ``#``), and convert each one to a ``.torrent`` file.  By
default, each file is saved at ``{name}.torrent``, where ``{name}`` is replaced
by the value of the ``name`` field from the torrent info, but a different path
can be set via the ``--outfile`` option.

Options
^^^^^^^

-o PATH, --outfile PATH
                        Save the ``.torrent`` files to the given path.  The
                        path may contain a ``{name}`` placeholder, which will
                        be replaced by the name of the torrent, and/or a
                        ``{hash}`` placeholder, which will be replaced by the
                        torrent's info hash in hexadecimal.  [default:
                        ``{name}.torrent``]

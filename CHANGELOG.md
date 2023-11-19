v0.3.0 (2023-11-19)
-------------------
- Support Python 3.12
- Update anyio to 4.x
- Migrated from setuptools to hatch
- Fix another occurrence of the Heisenbug from v0.2.0
- Update torf requirement to `>= 4.2.2, < 5.0`

v0.2.0 (2023-09-23)
-------------------
- Disable coloring of log messages when stderr is redirected
- Increase colorlog minimum version requirement to 6.0
- Support UDP tracker protocol extensions (BEP 41)
- Bugfix: Do not reject extended peer messages 1 to 7 bytes in length
- Sanitize all ASCII non-printable characters in torrent names when filling in
  output path templates
- Suppress sub-INFO log messages from dependencies
- Fix a Heisenbug involving attrs, slotted classes, and garbage collection
- Test against PyPy

v0.1.0 (2023-06-11)
-------------------
Initial release

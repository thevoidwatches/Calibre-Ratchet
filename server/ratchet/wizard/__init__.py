"""The setup wizard: a page in the browser, served to this machine only, that
gets Ratchet from an unpacked folder to a running service.

Run it with `python -m ratchet.wizard` (Setup.bat does, after installing the
packages). It is its own program rather than a mode of the service because
the service cannot start without the configuration this exists to write.
"""

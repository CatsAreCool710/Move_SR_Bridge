# version.py - Single source of the Move-SR-Bridge version string
# Copyright (C) 2026 Jeremiah Ticket
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
Version string for Move-SR-Bridge.

Both processes (the remote script inside Live and sr_helper) log this at
startup, so Move_SR_Bridge.log always records which build produced it --
the log is the primary support artefact for this project.

Release process: bump this, then tag the commit `v<__version__>`.  The
release workflow (.github/workflows/build.yml) asserts the two match and
fails the release if they have drifted.
"""

__version__ = "1.7.0"

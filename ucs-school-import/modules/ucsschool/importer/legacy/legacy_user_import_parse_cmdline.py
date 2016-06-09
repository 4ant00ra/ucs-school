# -*- coding: utf-8 -*-
#
# Univention UCS@School
"""
Legacy command line frontend for user import.
"""
# Copyright 2016 Univention GmbH
#
# http://www.univention.de/
#
# All rights reserved.
#
# The source code of this program is made available
# under the terms of the GNU Affero General Public License version 3
# (GNU AGPL V3) as published by the Free Software Foundation.
#
# Binary versions of this program provided by Univention to you as
# well as other copyrighted, protected or trademarked materials like
# Logos, graphics, fonts, specific documentations and configurations,
# cryptographic keys etc. are subject to a license agreement between
# you and Univention and not subject to the GNU AGPL V3.
#
# In the case you use this program under the terms of the GNU AGPL V3,
# the program is provided in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License with the Debian GNU/Linux or Univention distribution in file
# /usr/share/common-licenses/AGPL-3; if not, see
# <http://www.gnu.org/licenses/>.

import sys
import os.path
from argparse import ArgumentParser

from ucsschool.importer.frontend.parse_user_import_cmdline import ParseUserImportCmdline


class LegacyUserImportParseUserImportCmdline(ParseUserImportCmdline):
		def __init__(self):
			self.defaults = dict()
			self.parser = ArgumentParser(description="Create/modify/delete user accounts according to import file for "
				"ucs@school.")
			self.parser.add_argument('importFile', help="CSV file with users to import [mandatory].")
			self.parser.add_argument('-c', '--conffile', help="Configuration file to use (e.g. "
				"/var/lib/ucs-school-import/configs/user_import_legacy.json).")
			self.parser.add_argument("-o", "--outfile", dest="outfile", help="File to write passwords of created users "
				"to.")

		def parse_cmdline(self):
			if sys.argv[-1] == "ucs-test":
				del sys.argv[-1]
				ucs_test = True
				print("------ Running in ucs-test mode. ------")
			else:
				ucs_test = False

			super(LegacyUserImportParseUserImportCmdline, self).parse_cmdline()

			# legacy cmdline tool output emulation
			print("infile is: {}".format(self.args.importFile))
			if self.args.outfile:
				if os.path.exists(self.args.outfile):
					print("ERROR: outfile exists, will not overwrite existing file.")
					sys.exit(1)
				else:
					print("outfile is: {}".format(self.args.importFile))

			if ucs_test:
				self.args.settings["csv"] = {"mapping": {"11": "password"}}
				self.args.settings["ucs_test"] = True
			self.args.settings["input"] = dict(filename=self.args.importFile)
			self.args.settings["output"] = dict(passwords=self.args.outfile)
			self.args.verbose = True
			# adding "logfile" early makes early logging possible
			self.args.logfile = "/var/log/univention/ucsschool-import.log"
			# self.args.conffile = "/var/lib/ucs-school-import/configs/user_import_legacy.json"
			return self.args
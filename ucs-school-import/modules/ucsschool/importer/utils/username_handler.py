# -*- coding: utf-8 -*-
#
# Univention UCS@school
"""
Create historically unique usernames.
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

import re
import string

from ldap.dn import escape_dn_chars
from univention.admin.uexceptions import noObject
from ucsschool.importer.utils.ldap_connection import get_admin_connection
from ucsschool.importer.exceptions import FormatError
from ucsschool.importer.utils.logging import get_logger


class UsernameHandler(object):
	replacement_variable_pattern = re.compile(r"\[.*?\]")
	allowed_chars = string.ascii_letters + string.digits + "."

	def __init__(self, username_max_length):
		self.username_max_length = username_max_length
		self.logger = get_logger()
		self.connection, self.position = get_admin_connection()

	def add_to_ldap(self, username, first_number):
		assert isinstance(username, basestring)
		assert isinstance(first_number, basestring)
		self.connection.add(
			"cn={},cn=unique-usernames,cn=ucsschool,cn=univention,{}".format(
				escape_dn_chars(username), self.connection.base),
			[
				("objectClass", "ucsschoolUsername"),
				("ucsschoolUsernameNextNumber", first_number)
			]
		)

	def get_next_number(self, username):
		assert isinstance(username, basestring)
		try:
			return self.connection.get(
				"cn={},cn=unique-usernames,cn=ucsschool,cn=univention,{}".format(
					escape_dn_chars(username), self.connection.base),
				attr=["ucsschoolUsernameNextNumber"])["ucsschoolUsernameNextNumber"][0]
		except KeyError:
			raise noObject("Username '{}' not found.".format(username))

	def get_and_raise_number(self, username):
		assert isinstance(username, basestring)
		cur = self.get_next_number(username)
		next = int(cur) + 1
		self.connection.modify(
			"cn={},cn=unique-usernames,cn=ucsschool,cn=univention,{}".format(
				escape_dn_chars(username), self.connection.base),
			[("ucsschoolUsernameNextNumber", cur, str(next))]
		)
		return cur

	def remove_bad_chars(self, name):
		"""
		Remove characters disallowed for usernames.
		* Username must only contain numbers, letters and dots, and may not be 'admin'!
		* Username must not start or end in a dot.

		:param name: str: username to check
		:return: str: copy of input, possibly modified
		"""
		bad_chars = "".join(sorted(set(name).difference(set(self.allowed_chars))))
		if bad_chars:
			self.logger.warn("Removing disallowed characters %r from username %r.", bad_chars, name)
		if name.startswith(".") or name.endswith("."):
			self.logger.warn("Removing disallowed dot from start and end of username %r.", name)
			name = name.strip(".")
		return name.translate(None, bad_chars)

	def format_username(self, name):
		"""
		Create a username from name, possibly replacing a counter variable.
		* This is intended to be called before/by/after ImportUser.format_from_scheme().
		* Supports inserting the counter anywhere in the name, as long as its
		length does not overflow username_max_length.
		* Only one counter variable is allowed.
		* Counters should run only to 999. The algorithm will not honor
		username_max_length for higher numbers!
		* Subclass->override counter_variable_to_function() and the called methods to support
		other schemes than [ALWAYSCOUNTER] and [COUNTER2] or change their meaning.

		:param name: str: username, possibly a template
		:return: str: unique username
		"""
		assert isinstance(name, basestring)
		ori_name = name
		cut_pos = self.username_max_length - 3  # numbers >999 are not supported

		match = self.replacement_variable_pattern.search(name)
		if not match:
			# no counter variable used, just check characters and length
			name = self.remove_bad_chars(name)
			if len(name) > self.username_max_length:
				res = name[:self.username_max_length]
				self.logger.warn("Username %r too long, shortened to %r.", name, res)
			else:
				res = name
			return res

		if len(self.replacement_variable_pattern.split(name)) > 2:
			raise FormatError("More than one counter variable found in username scheme '{}'.".format(name), name, name)

		# need username without counter variable to calculate length
		_base_name = "".join(self.replacement_variable_pattern.split(name))
		base_name = self.remove_bad_chars(_base_name)
		if _base_name != base_name:
			# recalculate position of pattern
			name = "{}{}{}".format(base_name[:match.start()], match.group(), base_name[match.end():])
			match = self.replacement_variable_pattern.search(name)

		variable = match.group()
		start = match.start()
		end = match.end()

		if start == 0 and end == len(name):
			raise FormatError("No username in '{}'.".format(name), ori_name, ori_name)

		# get counter function
		try:
			func = self.counter_variable_to_function[variable.upper()]
		except KeyError as exc:
			raise FormatError("Unknown variable name '{}' in username scheme '{}': '{}' not in known variables: '{}'".format(
				variable, ori_name, exc, self.counter_variable_to_function.keys()), variable, name)
		except AttributeError as exc:
			raise FormatError("No method '{}' can be found for variable name '{}' in username scheme '{}': {}".format(
				self.counter_variable_to_function[variable], variable, name, exc), variable, ori_name)

		if len(base_name) > cut_pos:
			# base name without variable to long, we have to shorten it
			# numbers will only be appended, no inserting possible anymore
			res = base_name[:cut_pos]
			insert_position = cut_pos
			self.logger.warn("Username %r too long, shortened to %r.", base_name, res)
			res = self.remove_bad_chars(res)  # dot from middle might be at end now
		else:
			insert_position = start
			res = u"{}{}".format(name[:start], name[end:])

		counter = func(res)  # get counter number to insert/append
		ret = "{}{}{}".format(res[:insert_position], counter, res[insert_position:])
		return ret

	@property
	def counter_variable_to_function(self):
		"""
		Subclass->override this to support other variables than [ALWAYSCOUNTER]
		and [COUNTER2] or change their meaning. Add/Modify corresponding
		methods in your subclass.
		Variables have to start with '[', end with ']' and must be all
		upper case.

		:return: dict: variable name -> function
		"""
		return {
			"[ALWAYSCOUNTER]": self.always_counter,
			"[COUNTER2]": self.counter2
		}

	def always_counter(self, name_base):
		"""
		[ALWAYSCOUNTER]

		:param name_base: str: the (base) username
		:return: str: number to append to username
		"""
		return self._counters(name_base, "1")

	def counter2(self, name_base):
		"""
		[COUNTER2]

		:param name_base: str: the (base) username
		:return: str: number to append to username
		"""
		return self._counters(name_base, "")

	def _counters(self, name_base, first_time):
		"""
		Common code of always_counter() and counter2().
		"""
		try:
			num = self.get_and_raise_number(name_base)
		except noObject:
			num = first_time
			self.add_to_ldap(name_base, "2")
		return num

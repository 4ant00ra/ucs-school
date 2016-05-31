# -*- coding: utf-8 -*-
#
# Univention UCS@School
"""
Legacy mass import class.
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

from univention.admin.uexceptions import noObject
from ucsschool.importer.mass_import.user_import import UserImport
from ucsschool.importer.exceptions import CreationError, UnkownAction, UnkownRole
from ucsschool.lib.roles import role_pupil, role_teacher, role_staff


class LegacyUserImport(UserImport):
	def detect_users_to_delete(self):
		"""
		No need to compare input and LDAP. Action was written in the CSV file
		and is already stored in user.action.
		"""
		# We need those to fetch the correct type from LDAP.
		a_student = self.factory.make_import_user([role_pupil])
		a_staff = self.factory.make_import_user([role_staff])
		a_teacher = self.factory.make_import_user([role_teacher])
		a_staff_teacher = self.factory.make_import_user([role_staff, role_teacher])

		users_to_delete = list()
		for user in self.imported_users:
			if user.action == "D":
				if user.is_student(user.school, user.dn):
					obj = a_student
				elif user.is_admininstrator(user.school, user.dn):  # attention: is_* are not mutually exclusive
					obj = a_staff_teacher
				elif user.is_teacher(user.school, user.dn):
					obj = a_teacher
				elif user.is_staff(user.school, user.dn):
					obj = a_staff
				else:
					raise UnkownRole("Cannot determine role of user with source_uid={} and user.record_uid={}.".format(
						user.source_uid, user.record_uid))
				try:
					users_to_delete.append(obj.get_by_import_id(self.connection, user.source_uid, user.record_uid))
				except noObject as exc:
					self.logger.error(exc)
		return users_to_delete

	def determine_add_modify_action(self, imported_user):
		"""
		Determine what to do with the ImportUser. Should set attribute "action"
		to either "A" or "M". If set to "M" the returned user must be a opened
		ImportUser from LDAP.

		:param imported_user: ImportUser from input
		:return: ImportUser: ImportUser with action set and possibly fetched
		from LDAP
		"""
		if imported_user.action == "A":
			try:
				user = imported_user.get_by_import_id(self.connection, imported_user.source_uid,
					imported_user.record_uid)
				if user.disabled != "none" or user.has_expiry(self.connection):
					self.logger.info("Found deactivated user %r, reactivating.", user)
					user.reactivate(self.connection)
					imported_user.prepare_properties(new_user=False)
					user.update(imported_user)
					user.action = "M"
				else:
					raise CreationError("User {} (source_uid:{} record_uid: {}) exist, but input demands 'A'.".format(
						imported_user, imported_user.source_uid, imported_user.record_uid),
						entry=imported_user.entry_count, import_user=imported_user)
			except noObject:
				# this is expected
				imported_user.prepare_properties(new_user=True)
				user = imported_user
		elif imported_user.action == "M":
			try:
				user = imported_user.get_by_import_id(self.connection, imported_user.source_uid,
					imported_user.record_uid)
				if user.disabled != "none" or user.has_expiry(self.connection):
					self.logger.info("Found deactivated user %r, reactivating.", user)
					user.reactivate(self.connection)
				imported_user.prepare_properties(new_user=False)
				user.update(imported_user)
			except noObject:
				user = imported_user
				user.action = "A"
		elif imported_user.action == "D":
			user = imported_user
		else:
			raise UnkownAction("{} (source_uid:{} record_uid: {}) has unknown action '{}'.".format(
				imported_user, imported_user.source_uid, imported_user.record_uid, imported_user.action),
				entry=imported_user.entry_count, import_user=imported_user)
		return user
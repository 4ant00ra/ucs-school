#!/usr/bin/python2.6
# -*- coding: utf-8 -*-
#
# Univention Management Console module:
#  Wizards
#
# Copyright 2012-2014 Univention GmbH
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

from univention.lib.i18n import Translation
from univention.management.console.log import MODULE
from univention.management.console.modules import UMC_CommandError
from univention.management.console.modules.decorators import simple_response, sanitize
from univention.management.console.modules.sanitizers import StringSanitizer
from univention.admin.uexceptions import valueError
from univention.admin.uexceptions import base as uldapBaseException
import univention.admin.modules as udm_modules

from ucsschool.lib.schoolldap import SchoolBaseModule, LDAP_Connection, LDAP_Filter, check_license, LicenseError, USER_READ, USER_WRITE
from ucsschool.lib.models import SchoolClass, School, User, Student, Teacher, Staff, TeachersAndStaff, SchoolComputer, WindowsComputer, MacComputer, IPComputer, UCCComputer
from univention.config_registry import ConfigRegistry

from univention.management.console.modules.schoolwizards.SchoolImport import SchoolImport

_ = Translation('ucs-school-umc-wizards').translate

ucr = ConfigRegistry()
ucr.load()

def get_user_class(user_type):
	if user_type == 'student':
		return Student
	if user_type == 'teacher':
		return Teacher
	if user_type == 'staff':
		return Staff
	if user_type == 'teachersAndStaff':
		return TeachersAndStaff
	return User

def get_computer_class(computer_type):
	if computer_type == 'windows':
		return WindowsComputer
	if computer_type == 'macos':
		return MacComputer
	if computer_type == 'ucc':
		return UCCComputer
	if computer_type == 'ipmanagedclient':
		return IPComputer
	return SchoolComputer

def iter_objects_in_request(request):
	flavor = request.flavor
	if flavor == 'schoolwizards/schools':
		klass = School
	elif flavor == 'schoolwizards/users':
		klass = User
	elif flavor == 'schoolwizards/computers':
		klass = SchoolComputer
	elif flavor == 'schoolwizards/classes':
		klass = SchoolClass
	for properties in request.options:
		obj_props = properties['object']
		for key, value in obj_props.iteritems():
			if isinstance(value, basestring):
				obj_props[key] = value.strip()
		if issubclass(klass, User):
			if 'type' in obj_props:
				klass = get_user_class(obj_props['type'])
		if issubclass(klass, SchoolComputer):
			if 'type' in obj_props:
				klass = get_computer_class(obj_props['type'])
		obj = klass(**obj_props)
		if '$dn$' in obj_props:
			obj.old_dn = obj_props['$dn$']
		yield obj

def response(func):
	def _decorated(self, request, *a, **kw):
		if not self._check_license(request):
			return
		try:
			ret = func(self, request, *a, **kw)
		except (ValueError, IOError, OSError, valueError) as err:
			MODULE.info(str(err))
			raise UMC_CommandError(str(err))
		else:
			self.finished(request.id, ret)
	return _decorated


class Instance(SchoolBaseModule, SchoolImport):
	"""Base class for the schoolwizards UMC module.
	"""

	def _computer_name_used(self, name, ldap_user_read):
		ldap_filter = LDAP_Filter.forAll(name, fullMatch=['name'])
		computer_exists = udm_modules.lookup('computers/computer', None, ldap_user_read,
		                                     scope='sub', filter=ldap_filter)
		return bool(computer_exists)

	def _mac_address_used(self, address, ldap_user_read):
		ldap_filter = LDAP_Filter.forAll(address, fullMatch=['mac'])
		address_exists = udm_modules.lookup('computers/computer', None, ldap_user_read,
		                                    scope='sub', filter=ldap_filter)
		return bool(address_exists)

	def _ip_address_used(self, address, ldap_user_read):
		ldap_filter = LDAP_Filter.forAll(address, fullMatch=['ip'])
		address_exists = udm_modules.lookup('computers/computer', None, ldap_user_read,
		                                    scope='sub', filter=ldap_filter)
		return bool(address_exists)

	def _check_license(self, request):
		try:
			check_license()
			return True
		except (LicenseError) as e:
			MODULE.warn('License error: %s' % e)
			self.finished(request.id, dict(message=str(e)))
			return False

	@simple_response
	def is_singlemaster(self):
		return ucr.is_true('ucsschool/singlemaster', False)

	@sanitize(
		schooldc=StringSanitizer(required=True, regex_pattern=re.compile(r'^[a-zA-Z](([a-zA-Z0-9-_]*)([a-zA-Z0-9]$))?$')),
		schoolou=StringSanitizer(required=True, regex_pattern=re.compile(r'^[a-zA-Z0-9](([a-zA-Z0-9_]*)([a-zA-Z0-9]$))?$')),
	)
	@simple_response
	def move_dc(self, schooldc, schoolou):
		params = ['--dcname', schooldc, '--ou', schoolou]
		return_code, stdout = self._run_script(SchoolImport.MOVE_DC_SCRIPT, params, True)
		return {'success': return_code == 0, 'message': stdout}

	def _computer_types(self):
		computer_types = [
			('windows', _('Windows system')),
			('macos', _('Mac OS X')),
			('ipmanagedclient', _('Device with IP address')),
		]
		try:
			import univention.admin.handlers.computers.ucc as ucc
			ucc_available = bool(ucc)
		except ImportError:
			ucc_available = False
		if ucc_available:
			computer_types.insert(1, ('ucc', _('Univention Corporate Client')))
		return computer_types

	@simple_response
	def computer_types(self):
		ret = []
		computer_types = self._computer_types()
		for computer_type_id, computer_type_label in computer_types:
			ret.append({'id': computer_type_id, 'label': computer_type_label})
		return ret

	@LDAP_Connection()
	@response
	def share_servers(self, request, search_base=None, ldap_user_read=None, ldap_position=None):
		# udm/syntax/choices UCSSchool_Server_DN
		ret = [{'id' : '', 'label' : ''}]
		for module in ['computers/domaincontroller_master', 'computers/domaincontroller_backup', 'computers/domaincontroller_slave', 'computers/memberserver']:
			for obj in udm_modules.lookup(module, None, ldap_user_read, scope='sub'):
				obj.open()
				ret.append({'id' : obj.dn, 'label' : obj.info.get('fqdn', obj.info['name'])})
		return ret

	@LDAP_Connection()
	@response
	def _get_obj(self, request, search_base=None,
	                 ldap_user_read=None, ldap_position=None):
		ret = []
		for obj in iter_objects_in_request(request):
			MODULE.process('Getting %r' % (obj))
			obj = obj.from_dn(obj.old_dn, obj.school, ldap_user_read)
			ret.append(obj.to_dict())
		return ret

	@LDAP_Connection( USER_READ, USER_WRITE )
	@response
	def _create_obj(self, request, search_base=None,
	                 ldap_user_read=None, ldap_user_write=None, ldap_position=None):
		ret = []
		for obj in iter_objects_in_request(request):
			if isinstance(obj, SchoolClass):
				# workaround to be able to reuse this function everywhere
				obj.name = '%s-%s' % (obj.school, obj.name)
			MODULE.process('Creating %r' % (obj))
			obj.validate(ldap_user_read)
			if obj.errors:
				ret.append({'result' : {'message' : obj.get_error_msg()}})
				continue
			try:
				if obj.create(ldap_user_write, validate=False):
					ret.append(True)
				else:
					ret.append({'result' : {'message' : _('"%s" already exists!') % obj.name}})
			except uldapBaseException as exc:
				ret.append({'result' : {'message' : str(exc)}})
		return ret

	@LDAP_Connection( USER_READ, USER_WRITE )
	@response
	def _modify_obj(self, request, search_base=None,
	                 ldap_user_read=None, ldap_user_write=None, ldap_position=None):
		ret = []
		for obj in iter_objects_in_request(request):
			if isinstance(obj, SchoolClass):
				# workaround to be able to reuse this function everywhere
				obj.name = '%s-%s' % (obj.school, obj.name)
			MODULE.process('Modifying %r' % (obj))
			obj.validate(ldap_user_read)
			if obj.errors:
				ret.append({'result' : {'message' : obj.get_error_msg()}})
				continue
			try:
				obj.modify(ldap_user_write, validate=False)
			except uldapBaseException as exc:
				raise
				ret.append({'result' : {'message' : str(exc)}})
			else:
				ret.append(True) # no changes? who cares?
		return ret

	@LDAP_Connection( USER_READ, USER_WRITE )
	@response
	def _delete_obj(self, request, search_base=None, ldap_user_read=None, ldap_user_write=None, ldap_position=None):
		ret = []
		for obj in iter_objects_in_request(request):
			obj.name = obj.get_name_from_dn(obj.old_dn)
			MODULE.process('Deleting %r' % (obj))
			ret.append(obj.remove(ldap_user_write))
		return ret

	def _get_all(self, user_class, school, lo):
		if school:
			objs = user_class.get_all(school, lo)
		else:
			objs = []
			for school in School.from_binddn(lo):
				objs.extend(user_class.get_all(school.name, lo))
		return [obj.to_dict() for obj in objs]

	@LDAP_Connection()
	@response
	def get_users(self, request, search_base=None, ldap_user_read=None, ldap_position=None):
		school = request.options['school']
		user_class = get_user_class(request.options['type'])
		return self._get_all(user_class, school, ldap_user_read)

	get_user = _get_obj

	modify_user = _modify_obj

	create_user = _create_obj

	delete_user = _delete_obj

	@LDAP_Connection()
	@response
	def get_computers(self, request, search_base=None, ldap_user_read=None, ldap_position=None):
		school = request.options['school']
		computer_class = get_computer_class(request.options['type'])
		return self._get_all(computer_class, school, ldap_user_read)

	get_computer = _get_obj

	modify_computer = _modify_obj

	create_computer = _create_obj

	delete_computer = _delete_obj

	@LDAP_Connection()
	@response
	def get_classes(self, request, search_base=None, ldap_user_read=None, ldap_position=None):
		school = request.options['school']
		return self._get_all(SchoolClass, school, ldap_user_read)

	get_class = _get_obj

	modify_class = _modify_obj

	create_class = _create_obj

	delete_class = _delete_obj

	@LDAP_Connection()
	@response
	def get_schools(self, request, search_base=None, ldap_user_read=None, ldap_position=None):
		schools = School.get_all(ldap_user_read)
		return [school.to_dict() for school in schools]

	get_school = _get_obj

	modify_school = _modify_obj

	create_school = _create_obj

	delete_school = _delete_obj


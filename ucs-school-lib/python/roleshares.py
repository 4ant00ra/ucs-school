#!/usr/bin/python2.6
# -*- coding: iso-8859-15 -*-
#
# UCS@school lib
#  module: Role specific shares
#
# Copyright 2014 Univention GmbH
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

import os
import sys
import univention.config_registry
from ucsschool.lib.roles import role_pupil, role_teacher, role_staff
from ucsschool.lib.i18n import ucs_school_name_i18n
from ucsschool.lib.models import Group, School
from ucsschool.lib.schoolldap import get_all_local_searchbases, LDAP_Connection, USER_READ, USER_WRITE, set_credentials
import univention.admin.uexceptions
import univention.admin.uldap as udm_uldap
from univention.admincli.admin import _2utf8
import univention.admin.modules as udm_modules
udm_modules.update()

def roleshare_name(role, school_ou, ucr):
	custom_roleshare_name = ucr.get('ucsschool/import/roleshare/%s' % (role,))
	if custom_roleshare_name:
		return custom_roleshare_name
	else:
		return '-'.join((ucs_school_name_i18n(role), school_ou))

def roleshare_path(role, school_ou, ucr):
	custom_roleshare_path = ucr.get('ucsschool/import/roleshare/%s/path' % (role,))
	if custom_roleshare_path:
		return custom_roleshare_path
	else:
		return os.path.join(school_ou, ucs_school_name_i18n(role))

def roleshare_home_subdir(school_ou, roles, ucr=None):
	if not ucr:
		ucr = univention.config_registry.ConfigRegistry()
		ucr.load()
		
	if ucr.is_true('ucsschool/import/roleshare', True):
		for role in (role_pupil, role_teacher, role_staff):
			if role in roles:
				return roleshare_path(role, school_ou, ucr)
	return ''


@LDAP_Connection(USER_READ, USER_WRITE)
def create_roleshare_on_server(role, school_ou, share_container_dn, serverfqdn, teacher_group=None, ucr=None, ldap_user_read=None, ldap_user_write=None, ldap_position=None, search_base=None):
	if not ucr:
		ucr = univention.config_registry.ConfigRegistry()
		ucr.load()
		
	if not teacher_group:
		teacher_groupname = '-'.join((ucs_school_name_i18n(role_teacher), school_ou))
		teacher_group = Group(teacher_groupname, school_ou).get_udm_object(ldap_user_read)
		if not teacher_group:
			raise univention.admin.uexceptions.noObject, 'Group not found: %s.' % teacher_groupname
	else:
		teacher_groupname = teacher_group['name']

	try:
		udm_module_name = 'shares/share'
		udm_modules.init(ldap_user_write, ldap_position, udm_modules.get(udm_module_name))
		share_container = udm_uldap.position(share_container_dn)
		udm_obj = udm_modules.get(udm_module_name).object(None, ldap_user_write, share_container)
		udm_obj.open()
		udm_obj['name'] = roleshare_name(role, school_ou, ucr)
		udm_obj['path'] = os.path.join('/home', roleshare_path(role, school_ou, ucr))
		udm_obj['host'] = serverfqdn
		udm_obj['group'] = teacher_group['gidNumber']
		udm_obj['sambaBrowseable'] = "0"
		udm_obj['sambaWriteable'] = "0"
		udm_obj['sambaValidUsers'] = '@"%s"' % (teacher_groupname,)
		udm_obj['sambaCustomSettings'] = [('admin users', '@"%s"' % (teacher_groupname,))]
		udm_obj.create()
	except univention.admin.uexceptions.objectExists, dn:
		print 'Object exists: %s' % (dn,)
		pass
	else:
		print 'Object created: %s' % _2utf8( udm_obj.dn )

@LDAP_Connection(USER_READ)
def fqdn_from_serverdn(serverdn, ucr=None, ldap_user_read=None, ldap_position=None, search_base=None):
	fqdn = None
	try:
		dn, ldap_obj = ldap_user_read.search(base=serverdn, scope='base', attr=['cn', 'associatedDomain'])[0]
		if 'associatedDomain' in ldap_obj:
			fqdn = ".".join((ldap_obj['cn'][0], ldap_obj['associatedDomain'][0]))
	except IndexError:
		print 'Could not determine FQDN for %s' % (serverdn,)
		pass
	return fqdn

@LDAP_Connection(USER_READ)
def create_roleshare_for_searchbase(role, target_searchbase, ucr=None, ldap_user_read=None, ldap_position=None, search_base=None):
	if not ucr:
		ucr = univention.config_registry.ConfigRegistry()
		ucr.load()
		
	school_ou = target_searchbase.school
	share_container_dn = target_searchbase.shares

	server_list = []

	school_obj = School(school_ou).get_udm_object(ldap_user_read)
	ucsschoolHomeShareFileServer = school_obj.get('ucsschoolHomeShareFileServer')
	if ucsschoolHomeShareFileServer:
		fqdn = fqdn_from_serverdn(ucsschoolHomeShareFileServer, ucr)
		if fqdn:
			server_list.append(fqdn)

	ucsschoolClassShareFileServer = school_obj.get('ucsschoolClassShareFileServer')
	if ucsschoolClassShareFileServer and ucsschoolClassShareFileServer != ucsschoolHomeShareFileServer:
		fqdn = fqdn_from_serverdn(ucsschoolClassShareFileServer)
		if fqdn:
			server_list.append(fqdn)
	
	teacher_groupname = '-'.join((ucs_school_name_i18n(role_teacher), school_ou))
	teacher_group = Group(teacher_groupname, school_ou).get_udm_object(ldap_user_read)
	if not teacher_group:
		raise univention.admin.uexceptions.noObject, 'Group not found: %s.' % teacher_groupname

	for serverfqdn in server_list:
		create_roleshare_on_server(role, school_ou, share_container_dn, serverfqdn, teacher_group, ucr)


def create_roleshares(role_list, school_list=None, ucr=None):
	if not ucr:
		ucr = univention.config_registry.ConfigRegistry()
		ucr.load()
		
	supported_roles = (role_pupil, role_teacher, role_staff)
	supported_role_aliases = { 'student': 'pupil' }

	roles = []
	for name in role_list:
		if name in supported_role_aliases:
			name = supported_role_aliases[name]
		if name not in supported_roles:
			print 'Given role is not supported. Only supported roles are %s' % (supported_roles,)
			sys.exit(1)
		roles.append(name)

	all_visible_searchbases = get_all_local_searchbases()

	if not school_list:
		school_list = []

	all_visible_schools = [searchbase.school for searchbase in all_visible_searchbases]
	for school_ou in school_list:
		if school_ou not in all_visible_schools:
			print 'School not found: %s' (school_ou,)

	for searchbase in all_visible_searchbases:
		school_ou = searchbase.school
		if school_list and school_ou not in school_list:
			continue
		for role in roles:
			create_roleshare_for_searchbase(role, searchbase, ucr)

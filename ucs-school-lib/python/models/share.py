#!/usr/bin/python2.7
# -*- coding: utf-8 -*-
#
# UCS@school python lib: models
#
# Copyright 2014-2018 Univention GmbH
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

import os.path

from ucsschool.lib.models.attributes import ShareName, SchoolClassAttribute
from ucsschool.lib.models.base import UCSSchoolHelperAbstractClass
from ucsschool.lib.models.utils import ucr, _, logger


class Share(UCSSchoolHelperAbstractClass):
	name = ShareName(_('Name'))
	school_group = SchoolClassAttribute(_('School class'), required=True, internal=True)

	@classmethod
	def from_school_group(cls, school_group):
		return cls(name=school_group.name, school=school_group.school, school_group=school_group)
	from_school_class = from_school_group  # legacy

	@classmethod
	def get_container(cls, school):
		return cls.get_search_base(school).shares

	def do_create(self, udm_obj, lo):
		gid = self.school_group.get_udm_object(lo)['gidNumber']
		udm_obj['host'] = self.get_server_fqdn(lo)
		udm_obj['path'] = self.get_share_path()
		udm_obj['writeable'] = '1'
		udm_obj['sambaWriteable'] = '1'
		udm_obj['sambaBrowseable'] = '1'
		udm_obj['sambaForceGroup'] = '+%s' % self.name
		udm_obj['sambaCreateMode'] = '0770'
		udm_obj['sambaDirectoryMode'] = '0770'
		udm_obj['owner'] = '0'
		udm_obj['group'] = gid
		udm_obj['directorymode'] = '0770'
		if ucr.is_false('ucsschool/default/share/nfs', True):
			try:
				udm_obj.options.remove('nfs')  # deactivate NFS
			except ValueError:
				pass
		logger.info('Creating share on "%s"', udm_obj['host'])
		return super(Share, self).do_create(udm_obj, lo)

	def get_share_path(self):
		if ucr.is_true('ucsschool/import/roleshare', True):
			return '/home/%s/groups/%s' % (self.school_group.school, self.name)
		else:
			return '/home/groups/%s' % self.name

	def do_modify(self, udm_obj, lo):
		old_name = self.get_name_from_dn(self.old_dn)
		if old_name != self.name:
			head, tail = os.path.split(udm_obj['path'])
			tail = self.name
			udm_obj['path'] = os.path.join(head, tail)
			if udm_obj['sambaName'] == old_name:
				udm_obj['sambaName'] = self.name
			if udm_obj['sambaForceGroup'] == '+%s' % old_name:
				udm_obj['sambaForceGroup'] = '+%s' % self.name
		return super(Share, self).do_modify(udm_obj, lo)

	def get_server_fqdn(self, lo):
		domainname = ucr.get('domainname')
		school = self.get_school_obj(lo)
		school_dn = school.dn

		# fetch serverfqdn from OU
		result = lo.get(school_dn, ['ucsschoolClassShareFileServer'])
		if result:
			server_domain_name = lo.get(result['ucsschoolClassShareFileServer'][0], ['associatedDomain'])
			if server_domain_name:
				server_domain_name = server_domain_name['associatedDomain'][0]
			else:
				server_domain_name = domainname
			result = lo.get(result['ucsschoolClassShareFileServer'][0], ['cn'])
			if result:
				return '%s.%s' % (result['cn'][0], server_domain_name)

		# get alternative server (defined at ou object if a dc slave is responsible for more than one ou)
		ou_attr_ldap_access_write = lo.get(school_dn, ['univentionLDAPAccessWrite'])
		alternative_server_dn = None
		if len(ou_attr_ldap_access_write) > 0:
			alternative_server_dn = ou_attr_ldap_access_write['univentionLDAPAccessWrite'][0]
			if len(ou_attr_ldap_access_write) > 1:
				logger.warning('more than one corresponding univentionLDAPAccessWrite found at ou=%s', self.school)

		# build fqdn of alternative server and set serverfqdn
		if alternative_server_dn:
			alternative_server_attr = lo.get(alternative_server_dn, ['uid'])
			if len(alternative_server_attr) > 0:
				alternative_server_uid = alternative_server_attr['uid'][0]
				alternative_server_uid = alternative_server_uid.replace('$', '')
				if len(alternative_server_uid) > 0:
					return '%s.%s' % (alternative_server_uid, domainname)

		# fallback
		return '%s.%s' % (school.get_dc_name_fallback(), domainname)

	class Meta:
		udm_module = 'shares/share'


class ClassShare(Share):

	@classmethod
	def get_container(cls, school):
		return cls.get_search_base(school).classShares

	def get_share_path(self):
		if ucr.is_true('ucsschool/import/roleshare', True):
			return '/home/%s/groups/klassen/%s' % (self.school_group.school, self.name)
		else:
			return '/home/groups/klassen/%s' % self.name

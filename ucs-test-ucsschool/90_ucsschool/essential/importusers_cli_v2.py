# -*- coding: utf-8 -*-

import tempfile
import json
import shutil
import logging
import copy
import sys
import random
import csv
import os
import subprocess
import time
import re
import traceback
from ldap.filter import escape_filter_chars
from apt.cache import Cache as AptCache
from essential.importusers import Person
import univention.testing.ucr
import univention.testing.udm
import univention.testing.strings as uts
import univention.testing.ucsschool as utu
import univention.testing.utils as utils
import univention.testing.format.text
from univention.testing.ucs_samba import wait_for_drs_replication


class Bunch(object):

	def __init__(self, **kwds):
		self.__dict__.update(kwds)


class ImportException(Exception):
	pass


class TestFailed(Exception):

	def __init__(self, msg, stack):
		self.msg = msg
		self.stack = stack


class ConfigDict(dict):

	def update_entry(self, key, value):
		"""
		update_entry('foo:bar:baz', 'my value')
		update_entry('foo:bar:ding', False)
		"""
		if isinstance(value, basestring):
			if value.lower() == 'false':
				value = False
			elif value.lower() == 'true':
				value = True
		mydict = self
		items = key.split(':')
		while items:
			if len(items) == 1:
				mydict[items[0]] = value
			else:
				mydict = mydict.setdefault(items[0], {})
			del items[0]


class PyHooks(object):

	def __init__(self, hook_basedir=None):
		self.hook_basedir = hook_basedir if hook_basedir else '/usr/share/ucs-school-import/pyhooks'
		self.tmpdir = tempfile.mkdtemp(prefix='pyhook.', dir='/tmp')
		self.cleanup_files = set()
		self.log = logging.getLogger('PyHooks')

	def create_hooks(self):
		"""
		"""
		fn = '%s.py' % (uts.random_name(),)
		data = '''from ucsschool.importer.utils.user_pyhook import UserPyHook
import os

class MyHook(UserPyHook):
	priority = {
			"pre_create": 1,
			"post_create": 1,
			"pre_modify": 1,
			"post_modify": 1,
			"pre_move": 1,
			"post_move": 1,
			"pre_remove": 1,
			"post_remove": 1
	}

	def pre_create(self, user):
			self.logger.info("Running a pre_create hook for %%s.", user)
			self.run(user, 'create', 'pre')

	def post_create(self, user):
			self.logger.info("Running a post_create hook for %%s.", user)
			self.run(user, 'create', 'post')

	def pre_modify(self, user):
			self.logger.info("Running a pre_modify hook for %%s.", user)
			self.run(user, 'modify', 'pre')

	def post_modify(self, user):
			self.logger.info("Running a post_modify hook for %%s.", user)
			self.run(user, 'modify', 'post')

	def pre_move(self, user):
			self.logger.info("Running a pre_move hook for %%s.", user)
			self.run(user, 'move', 'pre')

	def post_move(self, user):
			self.logger.info("Running a post_move hook for %%s.", user)
			self.run(user, 'move', 'post')

	def pre_remove(self, user):
			self.logger.info("Running a pre_remove hook for %%s.", user)
			self.run(user, 'remove', 'pre')

	def post_remove(self, user):
			self.logger.info("Running a post_remove hook for %%s.", user)
			self.run(user, 'remove', 'post')

	def run(self, user, action, when):
		self.logger.info("***** Running {} {} hook for user {}.".format(when, action, user))
		# udm_properties[k] is only filled from LDAP, if k was in the input
		# don't try to get_udm_object() on a user not {anymore, yet} in ldap
		if not user.udm_properties.get('street') and not ((action == 'create' and when == 'pre') or (action == 'remove' and when == 'post')):
			obj = user.get_udm_object(self.lo)
			user.udm_properties['street'] = obj.info.get('street', '')
		user.udm_properties['street'] = user.udm_properties.get('street', '') + ',{}-{}'.format(when, action)
		if when == 'post' and action != 'remove':
			user.modify(self.lo)
		fn_touchfile = os.path.join(%(tmpdir)r, '%%s-%%s' %% (when, action))
		open(fn_touchfile, 'w').write('EXECUTED\\n')
''' % {'tmpdir': self.tmpdir}

		fn = os.path.join(self.hook_basedir, fn)
		self.cleanup_files.add(fn)
		with open(fn, 'w') as fd:
			fd.write(data)
		self.log.info('Created hook %r', fn)

	def cleanup(self):
		shutil.rmtree(self.tmpdir, ignore_errors=True)
		for fn in self.cleanup_files:
			try:
				os.remove(fn)
			except (IOError, OSError):
				self.log.warning('Failed to remove %r' % (fn,))
			if fn.endswith('.py'):
				try:
					os.remove('%sc' % (fn,))  # also remove .pyc files
				except (IOError, OSError):
					pass


class CLI_Import_v2_Tester(object):
	ucr = univention.testing.ucr.UCSTestConfigRegistry()

	def __init__(self):
		logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(funcName)s:%(lineno)d: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
		self.tmpdir = tempfile.mkdtemp(prefix='34_import-users_via_cli_v2.', dir='/tmp/')
		self.log = ColoredLogger('main')
		self.lo = None
		self.ldap_status = None
		self.hook_fn_set = set()
		self.errors = list()
		self.udm = None
		self.ou_A = Bunch(name='AA{}'.format(uts.random_string(length=random.randint(1, 9))))
		# set ou_B to None if a second OU is not needed
		self.ou_B = Bunch(name='BB{}'.format(uts.random_string(length=random.randint(1, 9))))
		# set ou_C to None if a third OU is not needed
		self.ou_C = Bunch(name='CC{}'.format(uts.random_string(length=random.randint(1, 9))))
		self.ucr.load()
		try:
			maildomain = self.ucr["mail/hosteddomains"].split()[0]
		except (AttributeError, IndexError):
			maildomain = self.ucr["domainname"]
		self.default_config = ConfigDict({
			"factory": "ucsschool.importer.default_user_import_factory.DefaultUserImportFactory",
			"classes": {},
			"input": {
				"type": "csv",
				"filename": "import.csv"
			},
			"csv": {
				"mapping": {
					"OUs": "schools",
					"Vor": "firstname",
					"Nach": "lastname",
					"Gruppen": "school_classes",
					"E-Mail": "email",
					"Beschreibung": "description",
				}
			},
			"maildomain": maildomain,
			"scheme": {
				"email": "<firstname>[0].<lastname>@<maildomain>",
				"recordUID": "<firstname>;<lastname>;<email>",
				"username": {
					"allow_rename": False,
					"default": "<:umlauts><firstname>[0].<lastname>[COUNTER2]"
				},
			},
			"sourceUID": "sourceDB",
			"user_role": "student",
			"tolerate_errors": 0,
		})

	def cleanup(self):
		self.log.info('Purging %r', self.tmpdir)
		shutil.rmtree(self.tmpdir, ignore_errors=True)
		for hook_fn in self.hook_fn_set:
			try:
				os.remove(hook_fn)
			except (IOError, OSError):
				self.log.warning('Failed to remove %r' % (hook_fn,))

	def create_config_json(self, values=None, config=None):
		"""
		Creates a config file for "ucs-school-user-import".
		Default values may be overridden via a dict called values.
		>>> values = {'user_role': 'teacher', 'input:type': 'csv' }
		>>> create_config_json(values=values)
		'/tmp/config.dkgfcsdz'
		>>> create_config_json(values=values, config=DEFAULT_CONFIG)
		'/tmp/config.dkgfcsdz'
		"""
		fn = tempfile.mkstemp(prefix='config.', dir=self.tmpdir)[1]
		if not config:
			config = copy.deepcopy(self.default_config)
		if values:
			for config_option, value in values.iteritems():
				config.update_entry(config_option, value)
		with open(fn, 'w') as fd:
			json.dump(config, fd)

		return fn

	def create_csv_file(self, person_list, mapping=None, fn_csv=None):
		"""
		Create CSV file for given persons
		>>> create_csv_file([Person('schoolA', 'student'), Person('schoolB', 'teacher')])
		'/tmp/import.sldfhgsg.csv'
		>>> create_csv_file([Person('schoolA', 'student'), Person('schoolB', 'teacher')], fn_csv='/tmp/import.foo.csv')
		'/tmp/import.foo.csv'
		>>> create_csv_file([Person('schoolA', 'student'), Person('schoolB', 'teacher')], headers={'firstname': 'Vorname', ...})
		'/tmp/import.cetjdfgj.csv'
		"""
		if mapping:
			header2properties = mapping
		else:
			header2properties = self.default_config['csv']['mapping']

		properties2headers = {v: k for k, v in header2properties.iteritems()}

		header_row = header2properties.keys()
		random.shuffle(header_row)
		self.log.debug('Header row = %r', header_row)

		fn = fn_csv if fn_csv else tempfile.mkstemp(prefix='users.', dir=self.tmpdir)[1]
		writer = csv.DictWriter(
			open(fn, 'w'),
			header_row,
			restval='',
			delimiter=',',
			quotechar='"',
			quoting=csv.QUOTE_ALL)
		writer.writeheader()
		for person in person_list:
			person_dict = person.map_to_dict(properties2headers)
			self.log.debug('Person data = %r', person_dict)
			writer.writerow(person_dict)
		return fn

	def save_ldap_status(self):
		self.log.debug('Saving LDAP status...')
		self.ldap_status = set(self.lo.searchDn())
		self.log.debug('LDAP status saved.')

	def diff_ldap_status(self):
		self.log.debug('Reading LDAP status for check differences...')
		new_ldap_status = set(self.lo.searchDn())
		new_objects = new_ldap_status - self.ldap_status
		removed_objects = self.ldap_status - new_ldap_status
		self.log.debug('LDAP status diffed.')
		self.log.debug('New objects: %r', new_objects)
		self.log.debug('Removed objects: %r', removed_objects)
		return Bunch(new=new_objects, removed=removed_objects)

	@classmethod
	def syntax_date2_dateformat(cls, userexpirydate):
		# copied from 61_udm-users/26_password_expire_date
		# Note: this is a timezone dependend value
		_re_iso = re.compile('^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
		_re_de = re.compile('^[0-9]{1,2}\.[0-9]{1,2}\.[0-9]+$')
		if _re_iso.match(userexpirydate):
			return "%Y-%m-%d"
		elif _re_de.match(userexpirydate):
			return "%d.%m.%y"
		else:
			raise ValueError

	@classmethod
	def udm_formula_for_shadowExpire(cls, userexpirydate):
		# copied from 61_udm-users/26_password_expire_date
		# Note: this is a timezone dependend value
		dateformat = cls.syntax_date2_dateformat(userexpirydate)
		return str(long(time.mktime(time.strptime(userexpirydate, dateformat)) / 3600 / 24 + 1))

	def run_import(self, args, fail_on_error=True):
		cmd = ['/usr/share/ucs-school-import/scripts/ucs-school-user-import'] + args
		self.log.info('Starting import: %r', cmd)
		sys.stdout.flush()
		sys.stderr.flush()
		exitcode = subprocess.call(cmd)
		self.log.info('Import process exited with exit code %r', exitcode)
		if fail_on_error and exitcode:
			self.log.error('As requested raising an exception due to non-zero exit code')
			raise ImportException('Non-zero exit code %r' % (exitcode,))
		return exitcode

	def check_new_and_removed_users(self, exp_new, exp_removed):
		ldap_diff = self.diff_ldap_status()
		new_users = [x for x in ldap_diff.new if x.startswith('uid=')]
		if len(new_users) != exp_new:
			self.log.error('Invalid number of new users (expected %d, found %d)! Found new objects: %r', exp_new, len(new_users), new_users)
			self.fail('Stopping because of invalid number of new users.')
		removed_users = [x for x in ldap_diff.removed if x.startswith('uid=')]
		if len(removed_users) != exp_removed:
			self.log.error('Invalid number of removed users (expected %d, found %d)! Removed objects: %r', exp_removed, len(removed_users), removed_users)
			self.fail('Stopping because of invalid number of removed users.')

	def fail(self, msg, returncode=1):
		"""
		Print package versions, traceback and error message.
		"""
		apt_cache = AptCache()
		self.log.error('\n%s\n%s%s', '=' * 79, ''.join(traceback.format_stack()), '=' * 79)

		pck_s = ['{:<40} {}'.format(pck, apt_cache[pck].installed.version if apt_cache[pck].is_installed else 'Not installed') for pck in sorted([pck for pck in apt_cache.keys() if 'school' in pck])]
		self.log.info('Installed package versions:\n{}'.format('\n'.join(pck_s)))
		utils.fail(msg, returncode)

	def run(self):
		try:
			with univention.testing.udm.UCSTestUDM() as udm:
				self.udm = udm
				with utu.UCSTestSchool() as schoolenv:
					self.lo = schoolenv.open_ldap_connection(admin=True)
					self.log.info('Creating OUs...')
					for ou in [self.ou_A, self.ou_B, self.ou_C]:
						if ou is not None:
							ou.name, ou.dn = schoolenv.create_ou(ou_name=ou.name, name_edudc=self.ucr.get('hostname'))
							self.log.info('Created OU %r (%r)...', ou.name, ou.dn)

					self.test()
					self.log.info('Test was successful.\n\n')
		finally:
			self.cleanup()

	def test(self):
		raise NotImplemented()

	def wait_for_drs_replication_of_membership(self, group_dn, member_uid, is_member=True, **kwargs):
		"""
		wait_for_drs_replication() of a user to become a member of a group.
		:param group: str: DN of a group
		:param member_uid: str: username
		:param is_member: bool: whether the user should be a member or not
		:param kwargs: dict: will be passed to wait_for_drs_replication() with a modified 'ldap_filter'
		:return: None | <ldb result>
		"""
		try:
			user_filter = kwargs['ldap_filter']
			if user_filter and not user_filter.startswith('('):
				user_filter = '({})'.format(user_filter)
		except KeyError:
			user_filter = ''
		if is_member:
			member_filter = '(memberOf={})'.format(escape_filter_chars(group_dn))
		else:
			member_filter = '(!(memberOf={}))'.format(escape_filter_chars(group_dn))
		kwargs['ldap_filter'] = '(&(cn={}){}{})'.format(
			escape_filter_chars(member_uid),
			member_filter,
			user_filter
		)
		res = wait_for_drs_replication(**kwargs)
		if not res:
			self.log.warn('No result from wait_for_drs_replication().')
		return res


class ColoredLogger(object):
	# BLACK RED GREEN YELLOW BLUE MAGENTA CYAN WHITE
	_colors = {
		'critical': 'RED',
		'debug': 'WHITE',
		'error': 'RED',
		'exception': 'RED',
		'info': 'YELLOW',
		'warning': 'CYAN',
	}

	def __init__(self, name):
		logging.basicConfig(
			stream=sys.stdout,
			level=logging.DEBUG,
			format='%(asctime)s %(levelname)s: %(funcName)s:%(lineno)d: %(message)s',
			datefmt='%Y-%m-%d %H:%M:%S')
		self.logger = logging.getLogger(name)

		self.utext = univention.testing.format.text.Text()
		self.colorize = False
		if sys.stdout.isatty():
			self.colorize = True
		else:
			# try to use the stdout of the parent process if it's ucs-test
			ppid = os.getppid()
			if 'ucs-test' in open('/proc/{}/cmdline'.format(ppid), 'rb').read():
				fd = open('/proc/{}/fd/1'.format(ppid), 'a')
				if fd.isatty():
					self.utext.term = univention.testing.format.text._Term(fd)
					self.colorize = True

	def _colorize(self, msg, color):
		if self.colorize:
			return '{}{}{}'.format(getattr(self.utext.term, self._colors[color]), msg, self.utext.term.NORMAL)
		else:
			return msg

	def critical(self, msg, *args, **kwargs):
		self.logger.critical(self._colorize(msg, self._colors['critical']), *args, **kwargs)

	fatal = critical

	def debug(self, msg, *args, **kwargs):
		self.logger.debug(self._colorize(msg, 'debug'), *args, **kwargs)

	def error(self, msg, *args, **kwargs):
		self.logger.error(self._colorize(msg, 'error'), *args, **kwargs)

	def exception(self, msg, *args, **kwargs):
		self.logger.exception(self._colorize(msg, 'exception'), *args, **kwargs)

	def info(self, msg, *args, **kwargs):
		self.logger.info(self._colorize(msg, 'info'), *args, **kwargs)

	def warning(self, msg, *args, **kwargs):
		self.logger.warning(self._colorize(msg, 'warning'), *args, **kwargs)

	warn = warning

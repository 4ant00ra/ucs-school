#!/usr/bin/python2.7
# -*- coding: utf-8 -*-
#
# Univention Common Python Library
#  Connections to remote UMC Servers
#
# Copyright 2017 Univention GmbH
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
import pprint
import json
from httplib import HTTPSConnection, HTTPException

from univention.config_registry import ConfigRegistry
ucr = ConfigRegistry()
ucr.load()


class _HTTPType(type):
	"""Metaclass for HTTP Error exceptions"""

	def __init__(mcs, name, bases, dict):
		try:
			HTTPError.codes[mcs.code] = mcs
		except (NameError, AttributeError):
			pass
		return type.__init__(mcs, name, bases, dict)


class ConnectionError(Exception):

	def __init__(self, msg, reason=None):
		super(ConnectionError, self).__init__(msg, reason)
		self.reason = reason


class HTTPError(Exception):
	__metaclass__ = _HTTPType
	codes = {}

	@property
	def status(self):
		return self.response.status

	@property
	def message(self):
		return self.response.message

	@property
	def result(self):
		return self.response.result

	def __new__(cls, request, response, hostname):
		err = cls.codes.get(response.status, cls)
		return super(HTTPError, cls).__new__(err, request, response, hostname)

	def __init__(self, request, response, hostname):
		self.request = request
		self.hostname = hostname
		self.response = response

	def __repr__(self):
		return '<HTTPError %s>' % (self,)

	def __str__(self):
		return '%s on %s (%s): %s' % (self.status, self.hostname, self.request.path, self.response.body)


class BadRequest(HTTPError):
	code = 400


class Unauthorized(HTTPError):
	code = 401


class Forbidden(HTTPError):
	code = 403


class NotFound(HTTPError):
	code = 404


class MethodNotAllowed(HTTPError):
	code = 405


class NotAcceptable(HTTPError):
	code = 406


class UnprocessableEntity(HTTPError):
	code = 422


class InternalServerError(HTTPError):
	code = 500


class BadGateway(HTTPError):
	code = 502


class ServiceUnavailable(HTTPError):
	code = 503


class Request(object):
	"""The HTTP Request
		method: GET / POST / PUT / DELETE
		path: the relative path to /univention/
		data: either the raw request payload or some data which must be encoded by get_body()
		headers: a dict of HTTP headers
	"""

	def __init__(self, method, path, data=None, headers=None):
		self.method = method
		self.path = path
		self.data = data
		self.headers = headers or {}

	def get_body(self):
		if self.headers.get('Content-Type', '').startswith('application/json'):
			return json.dumps(self.data)
		return self.data


class Response(object):
	"""The HTTP Response
		status: int between 200 and 599
		reason: string with the reason phrase e.g. 'OK'
		body: the raw response body
		headers: the response headers as list of tuples
	"""

	@property
	def result(self):
		if isinstance(self.data, dict):
			return self.data.get('result')

	@property
	def message(self):
		if isinstance(self.data, dict):
			return self.data.get('message')

	def __init__(self, status, reason, body, headers, _response):
		self.status = status
		self.reason = reason
		self.body = body
		self.headers = headers
		self._response = _response
		self.data = self.encode_body()

	def get_header(self, name, default=None):
		return self._response.getheader(name, default)

	def encode_body(self):
		data = self.body
		if self.get_header('Content-Type', '').startswith('application/json'):
			try:
				data = json.loads(data)
			except ValueError as exc:
				raise ConnectionError('Malformed response data: %r' % (data,), reason=exc)
		return data

	@classmethod
	def _from_httplib_response(cls, response):
		data = response.read()
		return cls(response.status, response.reason, data, response.getheaders(), response)


class _Client(object):
	"""A client capable to speak with a UMC-Server"""

	ConnectionType = HTTPSConnection

	def __init__(self, hostname=None, username=None, password=None, language='en-US', timeout=None, automatic_reauthentication=False):
		self.hostname = hostname or '%s.%s' % (ucr.get('hostname'), ucr.get('domainname'))
		self._language = language
		self._headers = {
			'Content-Type': 'application/json; charset=UTF-8',
			'Accept': 'application/json; q=1, text/html; q=0.5; */*; q=0.1',
			'Accept-Language': language,
			'X-Requested-With': 'XMLHttpRequest',
		}
		self._base_uri = '/univention-management-console/'
		self._timeout = timeout
		self._raise_errors = True
		self._automatic_reauthentication = automatic_reauthentication
		self.username = username
		self.password = password
		if username:
			self.authenticate(username, password)

	def authenticate(self, username, password):
		'''Tries to authenticate against the host and preserves the
		cookie. Has to be done only once (but keep in mind that the
		session probably expires after 10 minutes of inactivity)'''
		self.username = username
		self.password = password
		return self.umc_auth(username, password)

	def reauthenticate(self):
		return self.authenticate(self.username, self.password)

	def set_basic_http_authentication(self, username, password):
		self._headers['Authorization'] = 'Basic %s' % ('%s:%s' % (username, password)).encode('base64').rstrip()

	def authenticate_saml(self, username, password):
		raise ConnectionError('SAML authentication currently not supported.')

	def authenticate_with_machine_account(self):
		username = '%s$' % ucr.get('hostname')
		try:
			with open('/etc/machine.secret') as machine_file:
				password = machine_file.readline().strip()
		except EnvironmentError as exc:
			raise ConnectionError('Could not read /etc/machine.secret', reason=exc)
		self.authenticate(username, password)

	def umc_command(self, path, options=None, flavor=None):
		data = self.__build_data(options, flavor)
		return self.request('POST', 'command/%s' % (path,), data)

	def umc_set(self, options):
		data = self.__build_data(options)
		return self.request('POST', 'set', data)

	def umc_get(self, path, options=None):
		return self.request('POST', 'get/%s' % path, self.__build_data(options))

	def umc_upload(self):
		raise NotImplementedError('File uploads currently need to be done manually.')

	def umc_auth(self, username, password, **data):
		data = self.__build_data(dict({'username': username, 'password': password}, **data))
		return self.request('POST', 'auth', data)

	def umc_logout(self):
		return self.request('GET', 'logout')

	def request(self, method, path, data=None, headers=None):
		request = Request(method, path, data, headers)
		try:
			return self.send(request)
		except Unauthorized:
			if not self._automatic_reauthentication:
				raise
			self.reauthenticate()
			return self.send(request)

	def send(self, request):
		request.headers = dict(self._headers, **request.headers)
		try:
			response = self.__request(request)
		except (HTTPException, EnvironmentError) as exc:
			raise ConnectionError(reason=exc)
		self._handle_cookies(response)
		response = Response._from_httplib_response(response)
		if self._raise_errors and response.status > 299:
			raise HTTPError(request, response, self.hostname)
		return response

	def _handle_cookies(self, response):
		cookie = response.getheader('set-cookie')
		if cookie is None:
			return
		self._headers['Cookie'] = cookie  # FIXME: transform Set-Cookie to Cookie

	def __request(self, request):
		uri = '%s%s' % (self._base_uri, request.path)
		con = self._get_connection()
		con.request(request.method, uri, request.get_body(), headers=request.headers)
		response = con.getresponse()
		if response.status == 404:
			if self._base_uri == '/univention/':
				# UCS 4.1
				self._base_uri = '/univention-management-console/'
				return self.__request(request)
			elif self._base_uri == '/univention-management-console/':
				# UCS 3.X
				self._base_uri = '/umcp/'
				return self.__request(request)
		return response

	def _get_connection(self):
		'''Creates a new connection to the host'''
		# once keep-alive is over, the socket closes
		#   so create a new connection on every request
		return self.ConnectionType(self.hostname, timeout=self._timeout)

	def __build_data(self, data, flavor=None):
		'''Returns a dictionary as expected by the UMC Server'''
		data = {'options': data if data is not None else {}}
		if flavor:
			data['flavor'] = flavor
		return data


class Client(_Client):

	print_response = True
	print_request_data = True

	@classmethod
	def get_test_connection(cls, hostname=None, *args, **kwargs):
		ucr = ConfigRegistry()
		ucr.load()
		username = ucr.get('tests/domainadmin/account')
		username = username.split(',')[0][len('uid='):]
		password = ucr.get('tests/domainadmin/pwd')
		return cls(hostname, username, password, *args, **kwargs)

	def umc_command(self, *args, **kwargs):
		self.print_request_data = kwargs.pop('print_request_data', True)
		self.print_response = kwargs.pop('print_response', True)
		try:
			return super(Client, self).umc_command(*args, **kwargs)
		finally:
			self.print_request_data = True
			self.print_response = True

	def request(self, method, path, data=None, headers=None):
		print ''
		print '*** UMC request: "%s %s" %s' % (method, path, '(%s)' % (data.get('flavor'),) if isinstance(data, dict) else '')
		if self.print_request_data:
			print '  data = %s' % (pprint.pformat(data), )
		try:
			response = super(Client, self).request(method, path, data, headers)
		except:
			print 'UMC request failed: %s' % (sys.exc_info()[1],)
			print ''
			raise
		if self.print_response:
			print '*** UMC response: %s' % (pprint.pformat(response.data),)
		else:
			print '*** UMC reponse received'
		print ''
		return response

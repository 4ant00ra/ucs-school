# -*- coding: utf-8 -*-
"""
URLs
"""
#
# Univention UCS@school
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

from __future__ import unicode_literals
from django.conf.urls import url, include
from django.contrib import admin
from rest_framework import routers
# from rest_framework.documentation import include_docs_urls
from ucsschool.http_api.import_api import views


router = routers.DefaultRouter()
router.register(r'schools', views.SchoolViewSet)
router.register(r'imports/users', views.UserImportJobViewSet)
# router.register(r'imports/logfiles', views.LogFileViewSet)

urlpatterns = [
	url(r'^(?P<version>(v1))/', include(router.urls)),
	url(r'^(?P<version>(v1))/schools/(?P<ou>\w+)/imports/users', views.UserImportJobViewSet.as_view({'post': 'create'})),
	url(r'^(?P<version>(v1))/schools/(?P<ou>\w+)/imports/users', views.UserImportJobViewSet.as_view({'get': 'redirect_get_from_schools'})),
	url(r'^(?P<version>(v1))/imports/users/(?P<pk>\d+)/results', views.LogFileViewSet.as_view({'get': 'list'})),
	url(r'^admin/', admin.site.urls),
	url(r'^api-auth/', include('rest_framework.urls', namespace='rest_framework')),
]

# -*- coding: utf-8 -*-

# Univention Webui
#  menu.py
#
# Copyright (C) 2004-2009 Univention GmbH
#
# http://www.univention.de/
#
# All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.
#
# Binary versions of this file provided by Univention to you as
# well as other copyrighted, protected or trademarked materials like
# Logos, graphics, fonts, specific documentations and configurations,
# cryptographic keys etc. are subject to a license agreement between
# you and Univention.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

from uniconf import *

class menu(uniconf):
    def mytype(self):
        return "menu"

    def init(self,a,b,c):
        for item in self.args["items"]:
            self.subobjs.append(item)
        uniconf.init(self,a,b,c)

class menuitem(menu):
    def mytype(self):
        return "menuitem"
    def init(self,a,b,c):
        self.args["items"]=[self.args["item"]]
        if self.args.get("menu",None)!=None:
            self.args["items"].append(self.args["menu"])
        menu.init(self,a,b,c)

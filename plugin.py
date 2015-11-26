###
# Copyright (c) 2015, Jason Neel
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import supybot.utils as utils
from supybot.commands import *
import requests
import json
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
import logging

logger = logging.getLogger('supybot')

# https://members.iracing.com/membersite/Login

class NoCredentialsException(Exception):
    pass

class IracingConnection(object):

    def __init__(self, username, password):
        self.session = requests.Session()

        if len(username) == 0 or len(password) == 0:
            raise NoCredentialsException('Both username and password must be specified when creating an IracingConnection')

        self.username = username
        self.password = password

        headers = {
            'User-Agent' : 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.17 (KHTML, like Gecko) Chrome/24.0.1312.52 Safari/537.17',
            'Host': 'members.iracing.com',
            'Origin': 'members.iracing.com',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Connection' : 'keep-alive'
        }

        self.session.headers.update(headers)

    def login(self):

        loginData = {
            'username' : self.username,
            'password' : self.password,
            'AUTOLOGIN' : "true",
            'utcoffset' : 800,
            'todaysdate' : ''
        }

        try:
            response = self.session.post("https://members.iracing.com/membersite/Login", data=loginData)

            logger.info("Login response:\n\n" + response.content)

        except Exception as e:
            logger.warning("Caught exception logging in: " + str(e))
            return None

        return response

    def responseRequiresAuthentication(self, response):

        if response.status_code != requests.codes.ok:
            return True

        if "<HTML>" in response.content.upper():
            logger.info("Request looks like HTML.  Needs login?")
            return True

        return False

    def requestURL(self, url):
        # Use a needsRetry flag in case we catch a login failure outside of the SSL exception we seem to always get
        needsRetry = False
        response = None

        try:
            response = self.session.get(url, verify=True)
            logger.debug("Request to " + url + " returned code " + str(response.status_code))
            needsRetry = self.responseRequiresAuthentication(response)

        except Exception as e:
            # If this is an SSL error, we may be being redirected to the login page
            logger.info("Caught exception on " + url + " request." + str(e))
            needsRetry = True

        if needsRetry:
            logger.info("Logging in...")
            response = self.login()

        if response != None and not self.responseRequiresAuthentication(response):
            logger.info("Request returned " + str(response.status_code) + " status code")

            return response

        return None


class Racebot(callbacks.Plugin):
    """Add the help for "@plugin help Racetest" here
    This should describe *how* to use this plugin."""

    def __init__(self, irc):
        self.__parent = super(Racebot, self)
        self.__parent.__init__(irc)

        username = self.registryValue('iRacingUsername')
        password = self.registryValue('iRacingPassword')

        self.iracingConnection = IracingConnection(username, password)


    def raceronline(self, irc, msg, args):
        """takes no arguments

        Does things.
        """

        logger.info("Command sent by " + str(msg.nick))

        try:
            response = self.iracingConnection.requestURL("http://members.iracing.com/membersite/member/GetDriverStatus?friends=1&studied=1&onlineOnly=1")
            info = json.loads(response.text)

            if info != None:

                racers = []
                for racerJSON in info["fsRacers"]:
                    racers.append(racerJSON["name"])

                irc.reply("We found " + utils.str.commaAndify(racers))

        except utils.web.Error as e:
            irc.reply("Unable to open iRacing URL: " + str(e))

    raceronline = wrap(raceronline)


Class = Racebot


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:

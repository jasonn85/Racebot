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
import supybot.schedule as schedule
import supybot.ircmsgs as ircmsgs

logger = logging.getLogger('supybot')

# https://members.iracing.com/membersite/Login

class NoCredentialsException(Exception):
    pass

class Driver(object):

    def __init__(self, json):

        self.json = json
        self.id = json['custid']
        self.name = json['name']

        # Hidden users do not have info such as online status
        if 'hidden' not in json:
            self.isOnline = json['lastSeen'] > 0
        else:
            self.isOnline = False


    def nameForPrinting(self):
        return self.name.replace('+', ' ')

    lastNotifiedSession = None  # The ID of the last race session

class IRacingData:

    driversByID = {}
    latestGetDriverStatusJSON = None

    def __init__(self, iRacingConnection):
        self.iRacingConnection = iRacingConnection

    def grabData(self):
        """Refreshes data from iRacing JSON API."""
        self.latestGetDriverStatusJSON = self.iRacingConnection.fetchDriverStatusJSON()

        # Populate drivers dictionary
        # This could be made possibly more efficient by reusing existing Driver objects, but we'll be destructive and wasteful for now.
        for racerJSON in self.latestGetDriverStatusJSON["fsRacers"]:
            driver = Driver(racerJSON)
            self.driversByID[driver.id] = driver

    def onlineDrivers(self):
        """Returns an array of all online Driver()s"""
        drivers = []

        for driverID, driver in self.driversByID.items():
            if driver.isOnline:
                drivers.append(driver)

        return drivers


class IRacingConnection(object):

    URL_GET_DRIVER_STATUS = 'http://members.iracing.com/membersite/member/GetDriverStatus'

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

    def fetchDriverStatusJSON(self, friends=True, studied=True, onlineOnly=False):
        url = '%s?friends=%d&studied=%d&onlineOnly=%d' % (self.URL_GET_DRIVER_STATUS, friends, studied, onlineOnly)
        response = self.requestURL(url)
        return json.loads(response.text)


class Racebot(callbacks.Plugin):
    """Add the help for "@plugin help Racebot" here
    This should describe *how* to use this plugin."""

    SCHEDULER_TASK_NAME = 'SchedulerTask'
    SCHEDULER_INTERVAL_SECONDS = 300.0     # Every five minutes

    def __init__(self, irc):
        self.__parent = super(Racebot, self)
        self.__parent.__init__(irc)

        username = self.registryValue('iRacingUsername')
        password = self.registryValue('iRacingPassword')

        self.iRacingConnection = IRacingConnection(username, password)
        self.iRacingData = IRacingData(self.iRacingConnection)

        # Check for newly registered racers every x time, (initially five minutes.)
        # This should perhaps ramp down in frequency during non-registration times and ramp up a few minutes
        #  before race start times (four times per hour.)  For now, we fire every five minutes.
        def scheduleTick():
            self.doBroadcastTick(irc)
        schedule.addPeriodicEvent(scheduleTick, self.SCHEDULER_INTERVAL_SECONDS, self.SCHEDULER_TASK_NAME)

    def die(self):
        schedule.removePeriodicEvent(self.SCHEDULER_TASK_NAME)
        super(Racebot, self).die()

    def doBroadcastTick(self, irc):

        # Refresh data
        self.iRacingData.grabData()

        # TODO: Loop through all users, finding those newly registered for races and non-races
        # For each user found, loop through all channels and broadcast as appropriate.
        for channel in irc.state.channels:
            isRaceSession = True # TODO: Replace this placeholder
            relevantConfigValue = 'raceRegistrationAlerts' if isRaceSession else 'nonRaceRegistrationAlerts'
            shouldBroadcast = self.registryValue(relevantConfigValue, channel)

            if shouldBroadcast:
                irc.queueMsg(ircmsgs.privmsg(channel, 'Something about a racer here')) # TODO: Implement message

    def racers(self, irc, msg, args):
        """takes no arguments

        Lists all users currently in sessions (not just races)
        """

        logger.info("Command sent by " + str(msg.nick))

        self.iRacingData.grabData()
        onlineDrivers = self.iRacingData.onlineDrivers()
        onlineDriverNames = []

        for driver in onlineDrivers:
            onlineDriverNames.append(driver.nameForPrinting())

        if len(onlineDriverNames) == 0:
            response = 'No one is racing'
        else:
            response = 'Online racers: %s' % utils.str.commaAndify(onlineDriverNames)

        irc.reply(response)

    racers = wrap(racers)


Class = Racebot


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:

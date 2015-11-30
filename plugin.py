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
import os
from supybot.commands import *
import requests
import json
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
import logging
import supybot.schedule as schedule
import supybot.ircmsgs as ircmsgs
import sqlite3

logger = logging.getLogger('supybot')

class NoCredentialsException(Exception):
    pass

class Session(object):

    def __init__(self, driverJson):
        self.driverJson = driverJson
        self.id = driverJson['sessionId']
        self.startTime = driverJson.get('startTime')
        self.trackId = driverJson.get('trackId')
        self.sessionStatus = driverJson.get('subSessionStatus')
        self.registeredDriverCount = driverJson.get('regCount_0')
        self.seasonId = driverJson.get('seriesId')
        self.eventTypeId = driverJson.get('eventTypeId')

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.id == other.id
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def isRace(self):
        # Session types are test 1, practice 2, qualify 3, time trial 4, race 5.
        # If only Python 2 had enums
        return self.eventTypeId == 5

    def sessionDescription(self):
        if self.eventTypeId == 1:
            return "Test Session"
        elif self.eventTypeId == 2:
            return "Practice Session"
        elif self.eventTypeId == 3:
            return "Qualifying Session"
        elif self.eventTypeId == 4:
            return "Time Trial"
        elif self.eventTypeId == 5:
            return "Race"

        return "Unknown Session Type"


class Driver(object):

    def __init__(self, json, db):
        """
        @type db: RacebotDB
        """

        self.json = json
        self.db = db
        self.id = json['custid']
        self.name = json['name']
        self.sessionId = json.get('sessionId')

        # Hidden users do not have info such as online status
        if 'hidden' not in json:
            self.isOnline = json['lastSeen'] > 0
        else:
            self.isOnline = False

        # Persist the driver (no-op if we have already seen him)
        db.persistDriver(self)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.id == other.id
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    @property
    def nickname(self):
        return self.db.nickForDriver(self)

    @nickname.setter
    def nickname(self, theNickname):
        self.db.persistDriver(self, nick=theNickname)

    @property
    def allowNickReveal(self):
        return self.db.allowNickRevealForDriver(self)

    @allowNickReveal.setter
    def allowNickReveal(self, theAllowNickReveal):
        self.db.persistDriver(self, allowNickReveal=theAllowNickReveal)

    @property
    def allowRaceAlerts(self):
        return self.db.allowRaceAlertsForDriver(self)

    @allowRaceAlerts.setter
    def allowRaceAlerts(self, theAllowRaceAlerts):
        self.db.persistDriver(self, allowRaceAlerts=theAllowRaceAlerts)

    @property
    def allowOnlineQuery(self):
        return self.db.allowOnlineQueryForDriver(self)

    @allowOnlineQuery.setter
    def allowOnlineQuery(self, theAllowOnlineQuery):
        self.db.persistDriver(self, allowOnlineQuery=theAllowOnlineQuery)

    def isInASession(self):
        return 'sessionId' in self.json

    def currentSession(self):
        """
        @rtype: Session

        Returns a newly instantiated Session() object if this racer is registered for a session
        """
        try:
            if self.isInASession():
                return Session(self.json)
        except Exception as e:
            logger.warning('Caught exception parsing session data for %s: %s', self.nameForPrinting(), str(e))

        return None

    def nameForPrinting(self):
        nick = self.nickname

        if nick is not None:
            return nick

        return self.name.replace('+', ' ')

class IRacingData:
    """Aggregates all driver and session data into dictionaries."""

    driversByID = {}
    sessionByID = {}
    latestGetDriverStatusJSON = None

    def __init__(self, iRacingConnection, db):
        self.iRacingConnection = iRacingConnection
        self.db = db

        # TODO: Grab all relevant car/track/season data from the iRacing JSON

    def grabData(self):
        """Refreshes data from iRacing JSON API."""
        self.latestGetDriverStatusJSON = self.iRacingConnection.fetchDriverStatusJSON()

        # Populate drivers and sessions dictionaries
        # This could be made possibly more efficient by reusing existing Driver and Session objects,
        # but we'll be destructive and wasteful for now.
        for racerJSON in self.latestGetDriverStatusJSON["fsRacers"]:
            driver = Driver(racerJSON, self.db)
            self.driversByID[driver.id] = driver

            if driver.isInASession():
                session = driver.currentSession()
                self.sessionByID[session.id] = session


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


class RacebotDB(object):

    def __init__(self, filename):
        self.filename = filename

        if filename == ':memory:' or not os.path.exists(filename):
            self._createDatabase()

    def _createDatabase(self):
        db = sqlite3.connect(self.filename)

        try:
            cursor = db.cursor()

            cursor.execute("""CREATE TABLE `drivers` (
                            `id`	INTEGER NOT NULL UNIQUE,
                            `real_name`	TEXT,
                            `nick`	TEXT,
                            `allow_nick_reveal`	INTEGER DEFAULT 1,
                            `allow_name_reveal`	INTEGER DEFAULT 0,
                            `allow_race_alerts`	INTEGER DEFAULT 1,
                            `allow_online_query`	INTEGER DEFAULT 1,
                            PRIMARY KEY(id)
                            )
                            """)

            db.commit()
            logger.info("Created database and drivers table")
        finally:
            db.close()


    def _getDB(self):
        db = sqlite3.connect(self.filename)
        return db

    def persistDriver(self, driver, nick=None, allowNickReveal=None, allowNameReveal=None, allowRaceAlerts=None, allowOnlineQuery=None):
        """
        @type driver: Driver
        """
        db = self._getDB()

        try:
            cursor = db.cursor()

            cursor.execute("""INSERT OR IGNORE INTO drivers (id, real_name) VALUES (?, ?)""",
                          (driver.id, driver.name))

            if nick is not None:
                cursor.execute("""UPDATE drivers SET nick = ? WHERE id = ?""", (nick, driver.id))

            if allowNickReveal is not None:
                cursor.execute("""UPDATE drivers SET allow_nick_reveal = ? WHERE id = ?""", (allowNickReveal, driver.id))

            if allowNameReveal is not None:
                cursor.execute("""UPDATE drivers SET allow_name_reveal = ? WHERE id = ?""", (allowNameReveal, driver.id))

            if allowRaceAlerts is not None:
                cursor.execute("""UPDATE drivers SET allow_race_alerts = ? WHERE id = ?""", (allowRaceAlerts, driver.id))

            if allowOnlineQuery is not None:
                cursor.execute("""UPDATE drivers SET allow_online_query = ? WHERE id = ?""", (allowOnlineQuery, driver.id))

            db.commit()

        finally:
            db.close()

    def _rowForDriver(self, driver):
        """
        @param driver: Driver
        """

        db = self._getDB()

        try:
            cursor = db.cursor()
            cursor.row_factory = sqlite3.Row
            result = cursor.execute('SELECT * FROM drivers WHERE id=?', (driver.id,))
            row = result.fetchone()

        finally:
            db.close()

        return row

    def nickForDriver(self, driver):
        return self._rowForDriver(driver)['nick']

    def allowNickRevealForDriver(self, driver):
        return self._rowForDriver(driver)['allow_nick_reveal']

    def allowNameRevealForDriver(self, driver):
        return self._rowForDriver(driver)['allow_name_reveal']

    def allowRaceAlertsForDriver(self, driver):
        return self._rowForDriver(driver)['allow_race_alerts']

    def allowOnlineQueryForDriver(self, driver):
        return self._rowForDriver(driver)['allow_online_query']




class Racebot(callbacks.Plugin):
    """Add the help for "@plugin help Racebot" here
    This should describe *how* to use this plugin."""

    SCHEDULER_TASK_NAME = 'RacebotBroadcastSchedulerTask'
    SCHEDULER_INTERVAL_SECONDS = 300.0     # Every five minutes
    DATABASE_FILENAME = 'racebot_db.sqlite3'

    def __init__(self, irc):
        self.__parent = super(Racebot, self)
        self.__parent.__init__(irc)

        db = RacebotDB(self.DATABASE_FILENAME)

        username = self.registryValue('iRacingUsername')
        password = self.registryValue('iRacingPassword')

        connection = IRacingConnection(username, password)
        self.iRacingData = IRacingData(connection, db)

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

        # Loop through all drivers, looking for those in sessions
        for (_, aDriver) in self.iRacingData.driversByID.items():
            driver = aDriver    # After 15 minutes of struggling to get pycharm to recognize driver as a Driver object,
                                #  this stupid reassignment to a redundant var made it happy.  <3 Python
            """:type : Driver"""
            session = driver.currentSession()
            """:type : Session"""

            if session is None:
                continue

            if not driver.allowOnlineQuery or not driver.allowRaceAlerts:
                # This guy does not want to be spied
                continue

            isRaceSession = session.isRace()

            for channel in irc.state.channels:
                relevantConfigValue = 'raceRegistrationAlerts' if isRaceSession else 'nonRaceRegistrationAlerts'
                shouldBroadcast = self.registryValue(relevantConfigValue, channel)

                if shouldBroadcast:
                    message = '%s is registered for a %s' % (driver.nameForPrinting(), session.sessionDescription().lower())
                    irc.queueMsg(ircmsgs.privmsg(channel, message))

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

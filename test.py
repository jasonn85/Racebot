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

from supybot.test import *
import logging
import json
from plugin import IRacingConnection, Racebot, Driver, RacebotDB

logger = logging.getLogger()
logger.level = logging.DEBUG
stream_handler = logging.StreamHandler(sys.stdout)
logger.addHandler(stream_handler)

def grabStockIracingHomepage(self):
    result = None
    with open('Racebot/data/iRacingMainPage.txt', 'r') as mainPage:
        result = mainPage.read()
    return result

def grabEmptyFriendsList(self, friends=True, studied=True, onlineOnly=False):
    return None

def friendsListPrivateSession(self, friends=True, studied=True, onlineOnly=False):
    result = None
    with open('Racebot/data/GetDriverStatus-privateSession.txt', 'r') as friendsList:
        result = friendsList.read()
    return json.loads(result)

def friendsListRaceInProgress(self, friends=True, studied=True, onlineOnly=False):
    result = None
    with open('Racebot/data/GetDriverStatus-publicRace.txt', 'r') as friendsList:
        result = friendsList.read()
    return json.loads(result)

# Replace network operations with one that returns stock car/track data and one that returns no friends online
IRacingConnection.fetchMainPageRawHTML = grabStockIracingHomepage
IRacingConnection.fetchDriverStatusJSON = grabEmptyFriendsList

def alwaysReturnTrue(self):
    return True

# By default, allow all queries for users for testing
Driver.allowNickReveal = alwaysReturnTrue
Driver.allowOnlineQuery = alwaysReturnTrue
Driver.allowRaceAlerts = alwaysReturnTrue

# Make all users with negative IDs return 'IrrelevantGuy' as name, all drivers with ID 1 return 'testTarget,' all other
#  positive IDs return the real name
def nicknamesForTest(self, driver):
    if driver.id == 1:
        return 'testTarget'

    if driver.id <= 0:
        return 'IrrelevantGuy'

    return None

def noNicknames(self, driver):
    return None

RacebotDB.nickForDriver = nicknamesForTest

class RacebotTestCase(PluginTestCase):
    plugins = ('Racebot',)
    conf.supybot.plugins.Racebot.iRacingUsername.setValue('testUser')
    conf.supybot.plugins.Racebot.iRacingPassword.setValue('testPass')

    def testRacersNoOneOnline(self):
        self.assertResponse('racers', Racebot.NO_ONE_ONLINE_RESPONSE)

    def testRacersSomeoneOnline(self):
        try:
            oldFriendsListMethod = IRacingConnection.fetchDriverStatusJSON
            IRacingConnection.fetchDriverStatusJSON = friendsListPrivateSession

            self.assertNotRegexp('racers', re.escape(Racebot.NO_ONE_ONLINE_RESPONSE))

        finally:
            IRacingConnection.fetchDriverStatusJSON = oldFriendsListMethod

    def testRacersSomeoneInRace(self):
        try:
            oldFriendsListMethod = IRacingConnection.fetchDriverStatusJSON
            IRacingConnection.fetchDriverStatusJSON = friendsListRaceInProgress

            self.assertRegexp('racers', 'testTarget \\([\\w\\s]*Race\\)')

        finally:
            IRacingConnection.fetchDriverStatusJSON = oldFriendsListMethod

    def testBroadcastNoNickname(self):
        try:
            oldNickMethod = RacebotDB.nickForDriver
            oldFriendsListMethod = IRacingConnection.fetchDriverStatusJSON
            RacebotDB.nickForDriver = noNicknames
            IRacingConnection.fetchDriverStatusJSON = grabEmptyFriendsList

            cb = self.irc.getCallback('Racebot')
            """:type : Racebot"""
            cb.iRacingData.grabData()
            messages = cb.broadcastMessagesForChannel('testChannel')

            messageCount = len(messages) if messages else 0
            self.assertIs(messageCount, 0)

        finally:
            RacebotDB.nickForDriver = oldNickMethod
            IRacingConnection.fetchDriverStatusJSON = oldFriendsListMethod

    def testBroadcastNoOneOnline(self):
        try:
            oldFriendsListMethod = IRacingConnection.fetchDriverStatusJSON
            IRacingConnection.fetchDriverStatusJSON = grabEmptyFriendsList

            cb = self.irc.getCallback('Racebot')
            """:type : Racebot"""
            cb.iRacingData.grabData()
            messages = cb.broadcastMessagesForChannel('testChannel')

            messageCount = len(messages) if messages else 0
            self.assertIs(messageCount, 0)

        finally:
            IRacingConnection.fetchDriverStatusJSON = oldFriendsListMethod

    def testBroadcastRaceInProgress(self):
        try:
            oldFriendsListMethod = IRacingConnection.fetchDriverStatusJSON
            IRacingConnection.fetchDriverStatusJSON = friendsListPrivateSession

            cb = self.irc.getCallback('Racebot')
            """:type : Racebot"""
            cb.iRacingData.grabData()
            messages = cb.broadcastMessagesForChannel('testChannel')

            self.assertRegexpMatches(messages[0], '.*testTarget.*running for.*')

        finally:
            IRacingConnection.fetchDriverStatusJSON = oldFriendsListMethod

    def testNoDuplicateBroadcast(self):
        try:
            oldFriendsListMethod = IRacingConnection.fetchDriverStatusJSON
            IRacingConnection.fetchDriverStatusJSON = friendsListPrivateSession

            cb = self.irc.getCallback('Racebot')
            """:type : Racebot"""
            cb.iRacingData.grabData()
            messagesIncludingFirstBroadcast = cb.broadcastMessagesForChannel('testChannel')
            cb.iRacingData.setAllHasBeenBroadcastedFlags()
            expectedEmptyMessages = cb.broadcastMessagesForChannel('testChannel')

            secondMessageCount = len(expectedEmptyMessages) if expectedEmptyMessages else 0

            self.assertRegexpMatches(messagesIncludingFirstBroadcast[0], '.*testTarget.*')
            self.assertIs(secondMessageCount, 0)

            # Clear the flags for any future tests
            cb.iRacingData.setAllHasBeenBroadcastedFlags(value=False)

        finally:
            IRacingConnection.fetchDriverStatusJSON = oldFriendsListMethod

    def testBroadcastingSettingsAllOff(self):
        try:
            oldFriendsListMethod = IRacingConnection.fetchDriverStatusJSON
            IRacingConnection.fetchDriverStatusJSON = friendsListPrivateSession
            channel = 'testSilentChannel'

            cb = self.irc.getCallback('Racebot')
            """:type : Racebot"""
            cb.setRegistryValue('raceRegistrationAlerts', False, channel=channel)
            cb.setRegistryValue('nonRaceRegistrationAlerts', False, channel=channel)
            messages = cb.broadcastMessagesForChannel(channel)

            messageCount = len(messages) if messages else 0
            self.assertIs(messageCount, 0)

        finally:
            IRacingConnection.fetchDriverStatusJSON = oldFriendsListMethod

# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:

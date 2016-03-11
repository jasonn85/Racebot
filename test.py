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
from plugin import IRacingConnection, Racebot

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

# Replace network operations with one that returns stock car/track data and one that returns no friends online
IRacingConnection.fetchMainPageRawHTML = grabStockIracingHomepage
IRacingConnection.fetchDriverStatusJSON = grabEmptyFriendsList

class RacebotTestCase(PluginTestCase):
    plugins = ('Racebot',)
    conf.supybot.plugins.Racebot.iRacingUsername.setValue('testUser')
    conf.supybot.plugins.Racebot.iRacingPassword.setValue('testPass')

    def testNoOneOnline(self):
        self.assertResponse('racers', Racebot.NO_ONE_ONLINE_RESPONSE)

    def testSomeoneOnline(self):

        def friendsListPrivateSession(self, friends=True, studied=True, onlineOnly=False):
            result = None
            with open('Racebot/data/GetDriverStatus-privateSession.txt', 'r') as friendsList:
                result = friendsList.read()
            return json.loads(result)

        try:
            oldFriendsListMethod = IRacingConnection.fetchDriverStatusJSON
            IRacingConnection.fetchDriverStatusJSON = friendsListPrivateSession

            self.assertNotRegexp('racers', re.escape(Racebot.NO_ONE_ONLINE_RESPONSE))

        finally:
            IRacingConnection.fetchDriverStatusJSON = oldFriendsListMethod


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:

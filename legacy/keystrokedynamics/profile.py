import digraph
import storage

class Etalon:
    def __init__(self):
        self.keylog = {} # formed digraphs

    def addToEtalon(self, data):
        newDigraph = digraph.Digraph()
        for item in data:
            #key, value = newDigraph.addModif(item)
            key, value = newDigraph.add(item)
            if key is not None and value is not None:
                if self.keylog.has_key(key):
                    self.keylog[key][2] = int(self.keylog.get(key)[2]) + 1
                    self.keylog[key][0] = float(self.keylog[key][0] + value) / float(self.keylog[key][2])
                    self.keylog[key][1] = float((value - self.keylog[key][0]) ** 2) / float(self.keylog[key][2] - 1)
                else:
                    self.keylog[key] = [value, "0", "1"]
    def getitems(self):
        return self.keylog.items()
    def getkeys(self):
        return self.keylog.keys()
    def getvalues(self):
        return self.keylog.values()

    def printEtalon(self):
        for item in self.keylog.items():
            print item

class Profile:
    def __init__(self):
        self.profilelist = {}

    def createProfile(self, username, rawdata):
        self.profilelist[username] = Etalon()
        self.profilelist[username].addToEtalon(rawdata)
        return self.profilelist

    def printProfile(self):
        for item in self.profilelist.items():
            print item[0]
            item[1].printEtalon()

def new_profile(username, rawdata):
    """username: the profile owner. rawdata: list of [key+action,
    timestamp] pairs, as extracted by getpost.parse_keystroke_payload.
    Returns False (without touching storage) if username already has
    a profile.
    """
    myprofile = Profile()
    user_profile = myprofile.createProfile(username, rawdata)
    etalon = user_profile[username]

    items = [
        (digraph_id, expected_value, variance, frequency)
        for digraph_id, (expected_value, variance, frequency) in etalon.getitems()
    ]
    return storage.save_profile(username, items)

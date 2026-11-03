import digraph
import storage
import math

class Auth:
    def __init__(self):
        self.temp = digraph.Digraph()

    def authentication(self, user, data):
        V = 0
        print "For ", user, "  V = ", V, " data length: ", len(data)
        for item in data:
            key, value = self.temp.add(item)
            if key is not None and value is not None:
                expected_value, variance = storage.get_digraph(user, key)

                if expected_value is None or variance is None:
                    print user, "is a new user. Thre is no record in data base"
                    return False
                else:
                    if (expected_value - (3 * math.sqrt(variance))) <= value and value <= (expected_value + (3 * math.sqrt(variance))):
                        print str(expected_value - (3 * math.sqrt(variance)))," <= ", value , " <= ", str(expected_value + (3 * math.sqrt(variance)))
                        V += 1
                        #print V

        mV = float(V)/float(storage.count_digraphs(user))
        print V, "/", storage.count_digraphs(user), " = ", mV
        if mV <= 0.5:
            print "Access Denied", mV, " <= ", 0.5
            V = 0
            return "Access Denied: " + str(mV) + " <= " + str(0.5)
            #return "Access Denied"
        elif mV >= 0.6:
            print "Access Permitted", mV, " >= ", 0.6
            V = 0
            return "Access Permitted: " + str(mV) + " >= " + str(0.6)
            #return "Access Permitted"
        else:
            return "Wait"

def start_auth(user, data):
    bioAuth = Auth()
    return bioAuth.authentication(user, data)

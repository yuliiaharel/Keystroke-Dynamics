def parse_keystroke_payload(postdata):
    """postdata: the parsed JSON body Flask already gives us, shaped
    like {username: [{"Keys": "...", "Times": "..."}]}.

    Returns (username, rdata), where rdata is a list of
    [key+action, timestamp] pairs, oldest first. Works directly on
    the parsed dict -- no file read/write involved, unlike the
    original get_post_data/get_postAuth_data (which wrote the raw
    request body to a file named from client input before reading it
    straight back; the two were otherwise identical).
    """
    username = "".join(postdata.keys())
    rdata = []
    for item in postdata[username]:
        values = item.values()
        keylog = values[0].split(",")
        timelog = values[1].split(",")
        for i in xrange(len(keylog)):
            rdata.append([keylog[i], timelog[i]])
    return username, rdata

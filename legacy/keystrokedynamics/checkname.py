import storage

def is_record_exists(name):
    return storage.user_exists(name)

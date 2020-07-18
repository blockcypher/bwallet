import requests
import re


GITHUB_URL = 'https://github.com/blockcypher/bcwallet'
VERSION_URL = 'https://raw.githubusercontent.com/blockcypher/bcwallet/master/setup.py'


def get_latest_bcwallet_version():
    r = requests.get(VERSION_URL)
    assert r.status_code == 200, 'Could Not Connect to GitHub (status code %s)' % r.status_code
    matches = re.findall("version='(.*?)\'", r.content.decode('utf-8'))
    assert matches, 'bcwallet version not found on github'
    return matches[0]

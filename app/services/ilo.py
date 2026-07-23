import requests
import urllib3

from config import ILO_HOST, ILO_USERNAME, ILO_PASSWORD

urllib3.disable_warnings()


def get_ilo_session():

    session = requests.Session()

    session.auth = (
        ILO_USERNAME,
        ILO_PASSWORD
    )

    session.verify = False

    return session


def get_chassis():

    session = get_ilo_session()

    url = (
        f"https://{ILO_HOST}"
        "/redfish/v1/Chassis/1/"
    )

    response = session.get(url)

    response.raise_for_status()

    return response.json()

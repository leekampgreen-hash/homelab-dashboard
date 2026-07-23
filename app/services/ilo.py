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


def get_thermal():

    session = get_ilo_session()

    url = (
        f"https://{ILO_HOST}"
        "/redfish/v1/Chassis/1/Thermal/"
    )

    response = session.get(url)

    response.raise_for_status()

    return response.json()


def parse_thermal(thermal):

    fans = thermal.get("Fans", [])
    temperatures = thermal.get("Temperatures", [])

    fan_health = "OK"

    for fan in fans:

        health = fan.get("Status", {}).get("Health")

        if health != "OK":
            fan_health = "Critical"
            break


    cpu_temp = None
    ambient_temp = None
    storage_temp = None


    for sensor in temperatures:

        name = sensor.get("Name", "")
        temp = sensor.get("ReadingCelsius")


        if "CPU 1" in name:
            cpu_temp = temp

        elif "Ambient" in name:
            ambient_temp = temp

        elif "HD Controller" in name:
            storage_temp = temp


    return {
        "fan": {
            "status": fan_health,
            "count": len(fans)
        },
        "temperature": {
            "cpu": cpu_temp,
            "ambient": ambient_temp,
            "storage": storage_temp
        }
    }


def get_power():

    session = get_ilo_session()

    url = (
        f"https://{ILO_HOST}"
        "/redfish/v1/Chassis/1/Power/"
    )

    response = session.get(url)

    response.raise_for_status()

    return response.json()


def parse_power(power):

    power_supplies = power.get("PowerSupplies", [])

    psu_health = "OK"

    for psu in power_supplies:

        health = psu.get("Status", {}).get("Health")

        if health != "OK":
            psu_health = "Critical"
            break


    metrics = power.get("PowerMetrics", {})


    return {
        "power": {
            "current": power.get("PowerConsumedWatts"),
            "average": metrics.get("AverageConsumedWatts"),
            "max": metrics.get("MaxConsumedWatts")
        },
        "psu": {
            "status": psu_health,
            "count": len(power_supplies)
        }
    }


def get_ilo_health():

    chassis = get_chassis()
    thermal = parse_thermal(get_thermal())
    power = parse_power(get_power())

    return {
        "status": chassis.get("Status", {}).get("Health") or "Unknown",
        "chassis": {
            "model": chassis.get("Model", "Unknown")
        },
        "fan": thermal["fan"],
        "temperature": thermal["temperature"],
        "power": power["power"],
        "psu": power["psu"]
    }

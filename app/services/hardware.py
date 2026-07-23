from pyVim.connect import Disconnect

from services.vmware import connect_esxi
from services.logger import logger

def convert_value(value, modifier):
    return round(value * (10 ** modifier), 2)


def get_hardware_summary():

    si = connect_esxi()

    try:
        content = si.RetrieveContent()

        host = (
            content.rootFolder
            .childEntity[0]
            .hostFolder
            .childEntity[0]
            .host[0]
        )

        runtime = host.runtime.healthSystemRuntime

        if runtime is None or runtime.systemHealthInfo is None:
            return {}

        sensors = runtime.systemHealthInfo.numericSensorInfo

        result = {
            "health": {
                "storage": "Unknown",
                "memory": "Unknown",
                "fan": "Unknown",
                "power": "Unknown"
            },
            "power": {
                "watt": 0
            },
            "temperature": {
                "cpu": None,
                "ambient": None,
                "storage": None
            }
        }

        for sensor in sensors:

            name = sensor.name.lower()
            status = sensor.healthState.key

            # Health
            if sensor.sensorType == "storage":

                result["health"]["storage"] = status

            elif sensor.sensorType == "memory":

                result["health"]["memory"] = status

            elif sensor.sensorType == "fan":

                result["health"]["fan"] = status

            elif sensor.sensorType == "power":

                if status != "Green":
                    result["health"]["power"] = status

                elif result["health"]["power"] == "Unknown":
                    result["health"]["power"] = "Green"


                # Power Consumption
                if "ps 1 output" in name:

                    result["power"]["watt"] = convert_value(
                        sensor.currentReading,
                        sensor.unitModifier
                    )


            # Temperature
            if sensor.sensorType == "temperature":

                value = convert_value(
                    sensor.currentReading,
                    sensor.unitModifier
                )

                if "cpu" in name:

                    result["temperature"]["cpu"] = value

                elif "ambient" in name:

                    result["temperature"]["ambient"] = value

                elif "hd controller" in name:

                    result["temperature"]["storage"] = value


        return result

    finally:
        Disconnect(si)

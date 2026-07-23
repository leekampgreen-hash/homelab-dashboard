def generate_alerts(hardware):

    alerts = []
    ilo = hardware.get("ilo", {})

    if ilo.get("status") != "OK":
        alerts.append({
            "severity": "critical",
            "source": "iLO",
            "message": "iLO health check failed"
        })

    if ilo.get("fan", {}).get("status") != "OK":
        alerts.append({
            "severity": "critical",
            "source": "iLO",
            "message": "Fan failure detected"
        })

    if ilo.get("psu", {}).get("status") != "OK":
        alerts.append({
            "severity": "critical",
            "source": "iLO",
            "message": "PSU failure detected"
        })

    if (ilo.get("temperature", {}).get("cpu") or 0) > 70:
        alerts.append({
            "severity": "warning",
            "source": "iLO",
            "message": "CPU temperature is above 70°C"
        })

    if (ilo.get("temperature", {}).get("ambient") or 0) > 40:
        alerts.append({
            "severity": "warning",
            "source": "iLO",
            "message": "Ambient temperature is above 40°C"
        })

    return alerts

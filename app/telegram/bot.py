import os
from functools import wraps

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


load_dotenv()
ALLOWED_USER_IDS = set()


def parse_allowed_user_ids():
    values = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
    try:
        return {
            int(user_id.strip())
            for user_id in values.split(",")
            if user_id.strip()
        }
    except ValueError:
        return set()


def require_authorized_user(handler):
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user is None or user.id not in ALLOWED_USER_IDS:
            await update.effective_message.reply_text("Unauthorized")
            return
        return await handler(update, context)

    return wrapper


@require_authorized_user
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the Homelab Dashboard Telegram bot."
    )


@require_authorized_user
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Welcome message\n"
        "/help - Show available commands\n"
        "/status - Check dashboard status\n"
        "/docker - Show Docker container status\n"
        "/health - Show homelab health"
    )


@require_authorized_user
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dashboard_url = os.getenv("DASHBOARD_URL", "http://dashboard:8000").rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{dashboard_url}/api/vm")
            response.raise_for_status()
            payload = response.json()

        vms = payload.get("data")
        if payload.get("success") is not True or not isinstance(vms, list):
            raise ValueError("Invalid dashboard response")

        running = sum(vm.get("power_state") == "poweredOn" for vm in vms if isinstance(vm, dict))
        powered_off = sum(vm.get("power_state") == "poweredOff" for vm in vms if isinstance(vm, dict))

        await update.message.reply_text(
            "🏠 Homelab Status\n\n"
            f"VM Total: {len(vms)}\n"
            f"🟢 Running: {running}\n"
            f"🔴 Powered Off: {powered_off}"
        )
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        await update.message.reply_text(
            "Unable to retrieve homelab status from the dashboard."
        )


async def _dashboard_json(path):
    dashboard_url = os.getenv("DASHBOARD_URL", "http://dashboard:8000").rstrip("/")
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"{dashboard_url}{path}")
        response.raise_for_status()
        return response.json()


@require_authorized_user
async def docker_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        payload = await _dashboard_json("/api/docker")
        containers = payload.get("data")

        if payload.get("success") is not True or not isinstance(containers, list):
            raise ValueError("Invalid dashboard response")

        names = {item.get("name"): item for item in containers if isinstance(item, dict)}
        lines = ["🐳 Docker Status", ""]
        for name in ("dashboard", "collector", "telegram-bot"):
            container = names.get(name)
            if container is None:
                lines.extend([f"🔴 {name}", "Status: unavailable", ""])
                continue
            status = container.get("status", "unknown")
            icon = "🟢" if status == "running" else "🔴"
            lines.extend([f"{icon} {name}", f"Status: {status}", ""])

        await update.message.reply_text("\n".join(lines).rstrip())
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        await update.message.reply_text("Unable to retrieve Docker container status.")


@require_authorized_user
async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dashboard_data = await _dashboard_json("/api/dashboard")
        ilo = dashboard_data.get("hardware", {}).get("ilo")
        if not isinstance(ilo, dict):
            raise ValueError("iLO health data unavailable")

        chassis = ilo.get("chassis", {})
        fan = ilo.get("fan", {})
        psu = ilo.get("psu", {})
        temperature = ilo.get("temperature", {})
        power = ilo.get("power", {})

        status_icon = "🟢" if ilo.get("status") == "OK" else "🔴"
        fan_icon = "🟢" if fan.get("status") == "OK" else "🔴"
        psu_icon = "🟢" if psu.get("status") == "OK" else "🔴"

        await update.message.reply_text(
            "🏥 Hardware Health\n\n"
            f"Status:\n{status_icon} {ilo.get('status', 'Unavailable')}\n\n"
            f"Chassis:\n{chassis.get('model', 'Unavailable')}\n\n"
            f"Fan:\n{fan_icon} {fan.get('status', 'Unavailable')} ({fan.get('count', 0)})\n\n"
            f"PSU:\n{psu_icon} {psu.get('status', 'Unavailable')} ({psu.get('count', 0)})\n\n"
            f"CPU Temperature:\n{temperature.get('cpu', 'Unavailable')}°C\n\n"
            f"Ambient:\n{temperature.get('ambient', 'Unavailable')}°C\n\n"
            f"Power:\n{power.get('current', 'Unavailable')} W"
        )
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        await update.message.reply_text("Unable to retrieve homelab health.")


def create_application():
    global ALLOWED_USER_IDS
    ALLOWED_USER_IDS = parse_allowed_user_ids()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("docker", docker_command))
    application.add_handler(CommandHandler("health", health_command))
    return application


def main():
    create_application().run_polling()


if __name__ == "__main__":
    main()

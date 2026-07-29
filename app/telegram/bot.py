import os

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


load_dotenv()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the Homelab Dashboard Telegram bot."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Welcome message\n"
        "/help - Show available commands\n"
        "/status - Check dashboard status"
    )


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


def create_application():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    return application


def main():
    create_application().run_polling()


if __name__ == "__main__":
    main()

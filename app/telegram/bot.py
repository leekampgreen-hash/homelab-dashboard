import os
import asyncio
import logging
import time
from functools import wraps
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


load_dotenv()
ALLOWED_USER_IDS = set()
VM_SESSIONS = {}
VM_SESSION_TTL_SECONDS = 5 * 60
VM_TASK_TIMEOUT_SECONDS = 30
VM_TASK_POLL_INTERVAL_SECONDS = 2
STAGE_SELECT_VM = "select_vm"
STAGE_SELECT_ACTION = "select_action"
STAGE_CONFIRM = "confirm"
STAGE_SUBMITTING = "submitting"
logger = logging.getLogger(__name__)


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
        "/health - Show homelab health\n"
        "/vms - Control a virtual machine"
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


async def _dashboard_request(method, path):
    dashboard_url = os.getenv("DASHBOARD_URL", "http://dashboard:8000").rstrip("/")
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.request(method, f"{dashboard_url}{path}")
        response.raise_for_status()
        return response.json()


def _get_vm_session(user_id):
    session = VM_SESSIONS.get(user_id)
    if session is None:
        return None, False
    if time.monotonic() - session["created_at"] >= VM_SESSION_TTL_SECONDS:
        VM_SESSIONS.pop(user_id, None)
        return None, True
    return session, False


def _clear_vm_session(user_id, expected_session=None):
    if expected_session is None or VM_SESSIONS.get(user_id) is expected_session:
        VM_SESSIONS.pop(user_id, None)


async def _get_vms():
    payload = await _dashboard_json("/api/vm")
    vms = payload.get("data")
    if payload.get("success") is not True or not isinstance(vms, list):
        raise ValueError("Invalid dashboard response")
    return [vm for vm in vms if isinstance(vm, dict) and vm.get("id")]


def _vm_actions(power_state):
    if power_state == "poweredOff":
        return [("poweron", "Power On")]
    if power_state == "poweredOn":
        return [
            ("shutdown", "Shutdown Guest"),
            ("poweroff", "Force Power Off (destructive)"),
        ]
    return []


def _action_endpoint(vm_id, action):
    encoded_vm_id = quote(str(vm_id), safe="")
    return {
        "poweron": f"/api/vm/{encoded_vm_id}/poweron",
        "shutdown": f"/api/vm/{encoded_vm_id}/shutdown",
        "poweroff": f"/api/vm/{encoded_vm_id}/poweroff",
    }[action]


def _action_task_id(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid action response")

    task_id = payload.get("task_id")
    if task_id:
        return task_id

    for key in ("data", "task"):
        task = payload.get(key)
        if isinstance(task, dict) and task.get("id"):
            return task["id"]

    raise ValueError("Invalid action response")


async def _poll_vm_task(task_id):
    deadline = time.monotonic() + VM_TASK_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        payload = await _dashboard_json(f"/api/tasks/{quote(str(task_id), safe='')}")
        task = payload.get("data")
        if payload.get("success") is not True or not isinstance(task, dict):
            raise ValueError("Invalid task response")
        if task.get("state") == "success":
            return "success"
        if task.get("state") == "error":
            return "error"
        await asyncio.sleep(VM_TASK_POLL_INTERVAL_SECONDS)
    return "timeout"


async def _submit_vm_action(update, user_id, session):
    action = session["action"]
    vm_id = session["vm_id"]
    vm_name = session["vm_name"]
    session["stage"] = STAGE_SUBMITTING
    started_at = time.monotonic()
    result = "error"

    try:
        payload = await _dashboard_request("POST", _action_endpoint(vm_id, action))
        task_id = _action_task_id(payload)

        await update.effective_message.reply_text("VM action submitted. Checking status...")
        result = await _poll_vm_task(task_id)
        if result == "success":
            await update.effective_message.reply_text("VM action completed.")
        elif result == "error":
            await update.effective_message.reply_text("VM action failed.")
        else:
            await update.effective_message.reply_text(
                "The VM action is still processing. Please check the dashboard."
            )
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        await update.effective_message.reply_text("Unable to submit or verify the VM action.")
    finally:
        duration_seconds = time.monotonic() - started_at
        log_method = logger.info if result != "error" else logger.warning
        log_method(
            "Telegram VM action telegram_user=%s vm_id=%s vm_name=%s "
            "action=%s result=%s duration_seconds=%.2f",
            user_id,
            vm_id,
            vm_name,
            action,
            result,
            duration_seconds,
        )
        _clear_vm_session(user_id, session)


@require_authorized_user
async def vms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    _clear_vm_session(user_id)
    try:
        vms = await _get_vms()
        if not vms:
            await update.message.reply_text("No virtual machines are available.")
            return

        vm_map = {index: vm["id"] for index, vm in enumerate(vms, start=1)}
        VM_SESSIONS[user_id] = {
            "created_at": time.monotonic(),
            "stage": STAGE_SELECT_VM,
            "vm_map": vm_map,
        }
        lines = ["Virtual Machines", ""]
        for index, vm in enumerate(vms, start=1):
            lines.append(f"{index}. {vm.get('name', 'Unnamed VM')} - {vm.get('power_state', 'unknown')}")
        lines.extend(["0. Cancel", "", "Reply with a VM number."])
        await update.message.reply_text("\n".join(lines))
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        await update.message.reply_text("Unable to retrieve virtual machines from the dashboard.")


@require_authorized_user
async def vm_session_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = (update.effective_message.text or "").strip()
    session, expired = _get_vm_session(user_id)
    if session is None:
        if expired:
            await update.effective_message.reply_text(
                "VM session expired and was cancelled. Run /vms again."
            )
        else:
            await update.effective_message.reply_text("No active VM session. Run /vms to begin.")
        return

    if session["stage"] == STAGE_SUBMITTING:
        await update.effective_message.reply_text("A VM action is already being submitted.")
        return

    try:
        selection = int(message)
    except ValueError:
        await update.effective_message.reply_text("Reply with a valid number, or run /vms to start again.")
        return

    if selection == 0:
        if "vm_id" in session:
            logger.info(
                "Telegram VM action telegram_user=%s vm_id=%s vm_name=%s "
                "action=%s result=cancelled duration_seconds=0.00",
                user_id,
                session["vm_id"],
                session["vm_name"],
                session.get("action", "cancel"),
            )
        _clear_vm_session(user_id)
        await update.effective_message.reply_text("VM session cancelled.")
        return

    if session["stage"] == STAGE_SELECT_VM:
        vm_id = session["vm_map"].get(selection)
        if vm_id is None:
            await update.effective_message.reply_text("Invalid VM number. Reply with a number from the list.")
            return
        try:
            vm = next((item for item in await _get_vms() if item["id"] == vm_id), None)
            if vm is None:
                raise ValueError("VM no longer available")
            actions = _vm_actions(vm.get("power_state"))
            if not actions:
                _clear_vm_session(user_id)
                await update.effective_message.reply_text("This VM is not in a state that supports these actions. Run /vms again.")
                return
            session.update({
                "stage": STAGE_SELECT_ACTION,
                "vm_id": vm_id,
                "vm_name": vm.get("name", "Unnamed VM"),
                "actions": actions,
            })
            lines = [f"{vm.get('name', 'VM')} ({vm.get('power_state', 'unknown')})", ""]
            lines.extend(f"{index}. {label}" for index, (_, label) in enumerate(actions, start=1))
            lines.append("0. Cancel")
            await update.effective_message.reply_text("\n".join(lines))
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            _clear_vm_session(user_id)
            await update.effective_message.reply_text("Unable to refresh VM details. Run /vms again.")
        return

    if session["stage"] == STAGE_SELECT_ACTION:
        if selection < 1:
            await update.effective_message.reply_text("Invalid action number.")
            return
        try:
            action, label = session["actions"][selection - 1]
        except IndexError:
            await update.effective_message.reply_text("Invalid action number.")
            return
        session["action"] = action
        if action in {"shutdown", "poweroff"}:
            session["stage"] = STAGE_CONFIRM
            if action == "poweroff":
                await update.effective_message.reply_text(
                    "⚠️ WARNING\n\n"
                    "Force Power Off may cause data loss or filesystem corruption.\n\n"
                    "1. Confirm\n"
                    "0. Cancel"
                )
            else:
                await update.effective_message.reply_text(
                    f"Confirm {label}?\n1. Confirm\n0. Cancel"
                )
            return
        await _submit_vm_action(update, user_id, session)
        return

    if session["stage"] == STAGE_CONFIRM:
        if selection != 1:
            await update.effective_message.reply_text("Reply 1 to confirm or 0 to cancel.")
            return
        await _submit_vm_action(update, user_id, session)


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
    application.add_handler(CommandHandler("vms", vms_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, vm_session_message))
    return application


def main():
    create_application().run_polling()


if __name__ == "__main__":
    main()

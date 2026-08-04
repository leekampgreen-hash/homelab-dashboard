import ssl
import time
import uuid
from datetime import datetime, timezone

from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim

from config import ESXI_HOST, ESXI_USERNAME, ESXI_PASSWORD
from services.logger import logger


_submitted_non_task_statuses = {}
_SUBMITTED_NON_TASK_STATUS_TTL_SECONDS = 10 * 60


def connect_esxi():

    context = ssl._create_unverified_context()

    si = SmartConnect(
        host=ESXI_HOST,
        user=ESXI_USERNAME,
        pwd=ESXI_PASSWORD,
        sslContext=context
    )

    return si


def _task_state(state):
    state = str(state or "queued")
    if state in {"queued", "running", "success", "error"}:
        return state
    return "running"


def _serialize_task_error(error):
    if error is None:
        return None

    return str(getattr(error, "msg", error))


def get_task_status(task):
    """Return the normalized status for a pyVmomi task object."""
    info = task.info
    state = _task_state(info.state)
    progress = info.progress if info.progress is not None else 0

    if state == "success":
        progress = 100

    return {
        "id": info.key,
        "state": state,
        "progress": max(0, min(100, progress)),
        "start_time": info.startTime.isoformat() if info.startTime else None,
        "complete_time": info.completeTime.isoformat() if info.completeTime else None,
        "error": _serialize_task_error(info.error) if state == "error" else None
    }


def wait_for_task(task, timeout=None):
    """Wait for a VMware task and return its normalized final status."""
    started = time.monotonic()

    while True:
        status = get_task_status(task)
        if status["state"] in {"success", "error"}:
            return status

        if timeout is not None and time.monotonic() - started >= timeout:
            raise TimeoutError("VMware task timed out")

        time.sleep(1)


def serialize_task(task):
    if isinstance(task, dict):
        return task

    return get_task_status(task)


def _cleanup_submitted_non_task_statuses():
    now = time.monotonic()
    expired_task_ids = [
        task_id
        for task_id, (created_at, _) in _submitted_non_task_statuses.items()
        if now - created_at >= _SUBMITTED_NON_TASK_STATUS_TTL_SECONDS
    ]
    for task_id in expired_task_ids:
        del _submitted_non_task_statuses[task_id]


def _serialize_submitted_non_task():
    _cleanup_submitted_non_task_statuses()
    now = datetime.now(timezone.utc).isoformat()
    task_id = f"guest-shutdown-{uuid.uuid4()}"
    status = {
        "id": task_id,
        "state": "success",
        "progress": 100,
        "start_time": now,
        "complete_time": now,
        "error": None
    }
    _submitted_non_task_statuses[task_id] = (time.monotonic(), status)
    return status


def _find_task(content, task_id):
    task_manager = content.taskManager

    for task in task_manager.recentTask or []:
        if task.info.key == task_id:
            return task

    raise ValueError("VMware task not found")


def get_task(task_id):
    si = connect_esxi()

    try:
        return _find_task(si.RetrieveContent(), task_id)
    finally:
        Disconnect(si)


def get_task_status_by_id(task_id):
    _cleanup_submitted_non_task_statuses()
    submitted_status = _submitted_non_task_statuses.get(task_id)
    if submitted_status:
        return submitted_status[1]

    si = connect_esxi()

    try:
        task = _find_task(si.RetrieveContent(), task_id)
        return serialize_task(task)
    finally:
        Disconnect(si)


def get_host():

    si = connect_esxi()

    try:
        content = si.RetrieveContent()

        host = content.rootFolder.childEntity[0].hostFolder.childEntity[0].host[0]

        return host

    finally:
        Disconnect(si)


def get_host_summary():

    si = connect_esxi()

    try:
        content = si.RetrieveContent()

        host = content.rootFolder.childEntity[0].hostFolder.childEntity[0].host[0]

        summary = host.summary

        cpu_usage = summary.quickStats.overallCpuUsage
        cpu_total = summary.hardware.numCpuCores * summary.hardware.cpuMhz

        cpu_percent = round((cpu_usage / cpu_total) * 100, 1)

        memory_usage = summary.quickStats.overallMemoryUsage
        memory_total = summary.hardware.memorySize / 1024 / 1024

        memory_percent = round((memory_usage / memory_total) * 100, 1)

        datastores = []
        for datastore in host.datastore or []:
            try:
                capacity_bytes = datastore.summary.capacity
                free_bytes = datastore.summary.freeSpace
                if (
                    not datastore._moId
                    or not isinstance(capacity_bytes, (int, float))
                    or isinstance(capacity_bytes, bool)
                    or capacity_bytes <= 0
                    or not isinstance(free_bytes, (int, float))
                    or isinstance(free_bytes, bool)
                    or free_bytes < 0
                    or free_bytes > capacity_bytes
                ):
                    continue
                usage_percent = round(
                    ((capacity_bytes - free_bytes) / capacity_bytes) * 100,
                    1,
                )
            except (AttributeError, TypeError):
                continue
            datastores.append({
                "id": datastore._moId,
                "name": datastore.name or datastore._moId,
                "capacity_bytes": capacity_bytes,
                "free_bytes": free_bytes,
                "usage_percent": usage_percent,
            })

        datastore_percent = datastores[0]["usage_percent"] if datastores else 0

        return {
            "host_name": host.name or ESXI_HOST,
            "status": "online",
            "cpu": cpu_percent,
            "memory": memory_percent,
            "datastore": datastore_percent,
            "datastores": datastores,
        }

    finally:
        Disconnect(si)


def format_uptime(seconds):

    if seconds is None or seconds == "--":
        return "--"

    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24

    if days:
        return f"{days}d {hours % 24}h"
    elif hours:
        return f"{hours}h {minutes % 60}m"

    return f"{minutes}m"


def _snapshot_count(snapshot_list):
    return sum(1 + _snapshot_count(snapshot.childSnapshotList) for snapshot in snapshot_list or [])


def serialize_virtual_machine(vm):
    """Return the canonical VM inventory model used by API and dashboard consumers."""
    power_state = str(vm.runtime.powerState)
    status = {
        "poweredOn": "🟢 Running",
        "poweredOff": "🔴 Powered Off",
        "suspended": "🟡 Suspended"
    }.get(power_state, "Unknown")

    try:
        cpu = vm.config.hardware.numCPU
        memory_mb = vm.config.hardware.memoryMB
    except (AttributeError, TypeError):
        cpu = memory_mb = "--"

    try:
        guest_os = vm.config.guestFullName or "--"
    except (AttributeError, TypeError):
        guest_os = "--"
    try:
        ip_address = vm.guest.ipAddress or "--"
        hostname = vm.guest.hostName or "--"
        tools_status = vm.guest.toolsRunningStatus or "unknown"
    except (AttributeError, TypeError):
        ip_address = hostname = "--"
        tools_status = "unknown"

    try:
        uptime = format_uptime(vm.summary.quickStats.uptimeSeconds)
    except (AttributeError, TypeError):
        uptime = "--"

    datastore = ", ".join(item.name for item in (vm.datastore or [])) or "--"
    cluster = "--"
    try:
        parent = vm.runtime.host.parent
        if isinstance(parent, vim.ClusterComputeResource):
            cluster = parent.name
    except (AttributeError, TypeError):
        pass

    try:
        resource_pool = vm.resourcePool.name or "--"
    except (AttributeError, TypeError):
        resource_pool = "--"

    try:
        esxi_host = vm.runtime.host.name or "--"
    except (AttributeError, TypeError):
        esxi_host = "--"

    provisioned = used = 0
    try:
        for usage in vm.storage.perDatastoreUsage:
            used += usage.committed or 0
            provisioned += (usage.committed or 0) + (usage.uncommitted or 0)
    except (AttributeError, TypeError):
        pass

    provisioned_storage_gb = round(provisioned / 1024**3, 2)
    used_storage_gb = round(used / 1024**3, 2)

    return {
        "id": vm._moId,
        "name": vm.name,
        "power_state": power_state,
        "guest_os": guest_os,
        "ip_address": ip_address,
        "hostname": hostname,
        "cpu": cpu,
        "memory_mb": memory_mb,
        "provisioned_storage_gb": provisioned_storage_gb,
        "used_storage_gb": used_storage_gb,
        "snapshot_count": _snapshot_count(vm.snapshot.rootSnapshotList) if vm.snapshot else 0,
        "tools_status": tools_status,
        "uptime": uptime,
        "datastore": datastore,
        "cluster": cluster,
        "resource_pool": resource_pool,
        "esxi_host": esxi_host,
        # Backward-compatible aliases used by the existing dashboard.
        "status": status,
        "memory": memory_mb,
        "ip": ip_address,
        "guest": guest_os,
        "host": hostname
    }


def get_vm_list():

    si = connect_esxi()

    try:
        content = si.RetrieveContent()

        container = content.rootFolder

        view = content.viewManager.CreateContainerView(
            container,
            [vim.VirtualMachine],
            True
        )

        vms = []

        for vm in view.view:

            vms.append(serialize_virtual_machine(vm))
            continue

            power_state = str(vm.runtime.powerState)
            status = "🟢 Running"

            cpu = "--"
            memory = "--"
            ip = "--"
            guest = "--"
            host = "--"
            uptime = "--"

            try:
                cpu = vm.config.hardware.numCPU
            except (AttributeError, TypeError):
                pass

            try:
                memory = vm.config.hardware.memoryMB
            except (AttributeError, TypeError):
                pass

            try:
                ip = vm.guest.ipAddress or "--"
            except (AttributeError, TypeError):
                pass

            try:
                guest = vm.config.guestFullName or "--"
            except (AttributeError, TypeError):
                pass

            try:
                host = vm.runtime.host.name or "--"
            except (AttributeError, TypeError):
                pass

            try:
                uptime = vm.summary.quickStats.uptimeSeconds
            except (AttributeError, TypeError):
                pass

            if power_state == "poweredOff":
                status = "🔴 Powered Off"
            elif power_state == "suspended":
                status = "🟡 Suspended"

            uptime = format_uptime(uptime)

            vms.append({
                "id": vm._moId,
                "name": vm.name,
                "status": status,
                "power_state": power_state,
                "cpu": cpu,
                "memory": memory,
                "ip": ip,
                "guest": guest,
                "host": host,
                "uptime": uptime
            })

        power_state_order = {
            "poweredOn": 0,
            "suspended": 1,
            "poweredOff": 2
        }

        return sorted(
            vms,
            key=lambda x: (
                power_state_order[x["power_state"]],
                x["name"].lower()
            )
        )

    finally:
        Disconnect(si)


def list_virtual_machines():
    return get_vm_list()


def _get_vm_from_content(content, vm_identifier):
    view = content.viewManager.CreateContainerView(
        content.rootFolder,
        [vim.VirtualMachine],
        True
    )

    try:
        for vm in view.view:
            if vm._moId == vm_identifier or vm.name == vm_identifier:
                return vm
    finally:
        view.Destroy()

    raise ValueError("Virtual machine not found")


def get_virtual_machine(vm_identifier):
    si = connect_esxi()

    try:
        return _get_vm_from_content(si.RetrieveContent(), vm_identifier)
    finally:
        Disconnect(si)


def get_vm_metrics(vm_name):
    si = connect_esxi()

    try:
        vm = _get_vm_from_content(si.RetrieveContent(), vm_name)
        if vm.name != vm_name:
            raise ValueError("Virtual machine not found")

        quick_stats = getattr(vm.runtime, "quickStats", None)
        if quick_stats is None:
            quick_stats = getattr(vm.summary, "quickStats", None)
        cpu_usage_mhz = getattr(quick_stats, "overallCpuUsage", None)
        cpu_capacity_mhz = getattr(vm.runtime, "maxCpuUsage", None)
        memory_usage_mb = getattr(quick_stats, "guestMemoryUsage", None)
        memory_capacity_mb = getattr(vm.config.hardware, "memoryMB", None)

        cpu_usage_percent = None
        if (
            isinstance(cpu_usage_mhz, (int, float))
            and isinstance(cpu_capacity_mhz, (int, float))
            and cpu_capacity_mhz > 0
        ):
            cpu_usage_percent = round((cpu_usage_mhz / cpu_capacity_mhz) * 100, 1)

        memory_usage_percent = None
        if (
            isinstance(memory_usage_mb, (int, float))
            and isinstance(memory_capacity_mb, (int, float))
            and memory_capacity_mb > 0
        ):
            memory_usage_percent = round(
                (memory_usage_mb / memory_capacity_mb) * 100, 1
            )

        return {
            "name": vm.name,
            "power_state": str(vm.runtime.powerState),
            "cpu_usage_mhz": cpu_usage_mhz,
            "cpu_usage_percent": cpu_usage_percent,
            "memory_usage_mb": memory_usage_mb,
            "memory_usage_percent": memory_usage_percent,
            "memory_capacity_mb": memory_capacity_mb,
        }
    finally:
        Disconnect(si)


def _submit_vm_action(vm_id, action, submit, valid_states, requester="unknown"):
    si = connect_esxi()

    try:
        vm = _get_vm_from_content(si.RetrieveContent(), vm_id)
        power_state = str(vm.runtime.powerState)
        if power_state not in valid_states:
            expected = ", ".join(sorted(valid_states))
            raise ValueError(
                f"Cannot {action} virtual machine in state {power_state}; "
                f"expected one of: {expected}"
            )

        task = submit(vm)
        task_status = serialize_task(task)
        task_status["vm_id"] = vm._moId
        task_status["vm_name"] = vm.name
        logger.info(
            "VM action submitted vm_name=%s action=%s requester=%s "
            "timestamp=%s task_id=%s",
            vm.name,
            action,
            requester,
            datetime.now(timezone.utc).isoformat(),
            task_status["id"]
        )
        return task_status
    finally:
        Disconnect(si)


def power_on_vm(vm_id, requester="unknown"):
    return _submit_vm_action(
        vm_id,
        "power_on",
        lambda vm: vm.PowerOnVM_Task(),
        {"poweredOff", "suspended"},
        requester
    )


def power_off_vm(vm_id, force=False, requester="unknown"):
    action = "power_off_force" if force else "power_off"
    return _submit_vm_action(
        vm_id,
        action,
        lambda vm: vm.PowerOffVM_Task(),
        {"poweredOn", "suspended"},
        requester
    )


def reset_vm(vm_id, requester="unknown"):
    return _submit_vm_action(
        vm_id,
        "reset",
        lambda vm: vm.ResetVM_Task(),
        {"poweredOn"},
        requester
    )


def shutdown_guest(vm_id, requester="unknown"):
    def submit(vm):
        tools_status = getattr(vm.guest, "toolsRunningStatus", None)
        if tools_status != "guestToolsRunning":
            logger.warning(
                "Guest shutdown not requested for vm_name=%s: VMware Tools unavailable",
                vm.name
            )
            raise ValueError(
                "VMware Tools is not running; guest shutdown was not requested"
            )

        try:
            vm.ShutdownGuest()
        except Exception as exc:
            logger.warning("Guest shutdown failed for vm_name=%s", vm.name)
            raise ValueError("Guest shutdown failed; no forced power-off was issued") from exc

        return _serialize_submitted_non_task()

    return _submit_vm_action(
        vm_id,
        "shutdown_guest",
        submit,
        {"poweredOn"},
        requester
    )


def suspend_vm(vm_id, requester="unknown"):
    return _submit_vm_action(
        vm_id,
        "suspend",
        lambda vm: vm.SuspendVM_Task(),
        {"poweredOn"},
        requester
    )


def _snapshot_data(snapshot, parent_name=None):
    info = snapshot.snapshot
    return {
        "id": info._moId,
        "name": snapshot.name,
        "description": snapshot.description or "",
        "created": snapshot.createTime.isoformat() if snapshot.createTime else None,
        "state": str(snapshot.state),
        "parent_id": parent_name
    }


def _flatten_snapshots(snapshot_list, parent_id=None):
    snapshots = []

    for snapshot in snapshot_list or []:
        snapshots.append(_snapshot_data(snapshot, parent_id))
        snapshots.extend(_flatten_snapshots(snapshot.childSnapshotList, snapshot.snapshot._moId))

    return snapshots


def list_snapshots(vm_identifier):
    si = connect_esxi()

    try:
        vm = _get_vm_from_content(si.RetrieveContent(), vm_identifier)
        return _flatten_snapshots(vm.snapshot.rootSnapshotList)
    finally:
        Disconnect(si)


def get_snapshot_inventory():
    """Return all VM snapshots keyed by stable VM and snapshot identifiers."""
    si = connect_esxi()
    view = None

    try:
        content = si.RetrieveContent()
        view = content.viewManager.CreateContainerView(
            content.rootFolder,
            [vim.VirtualMachine],
            True
        )
        inventory = {}
        for vm in view.view:
            snapshots = _flatten_snapshots(
                vm.snapshot.rootSnapshotList if vm.snapshot else []
            )
            inventory[vm._moId] = {
                "vm_name": vm.name,
                "snapshots": {snapshot["id"]: snapshot for snapshot in snapshots},
            }
        return inventory
    finally:
        if view is not None:
            view.Destroy()
        Disconnect(si)


def _get_snapshot_from_vm(vm, snapshot_identifier):
    def find(snapshot_list):
        for snapshot in snapshot_list or []:
            if snapshot.snapshot._moId == snapshot_identifier or snapshot.name == snapshot_identifier:
                return snapshot.snapshot
            found = find(snapshot.childSnapshotList)
            if found:
                return found
        return None

    snapshot = find(vm.snapshot.rootSnapshotList)
    if snapshot is None:
        raise ValueError("Snapshot not found")
    return snapshot


def create_snapshot(vm_identifier, name, description="", memory=False, quiesce=False):
    si = connect_esxi()

    try:
        vm = _get_vm_from_content(si.RetrieveContent(), vm_identifier)
        task = vm.CreateSnapshot_Task(name, description, memory, quiesce)
        logger.info("Snapshot creation requested for VM %s", vm._moId)
        return serialize_task(task)
    finally:
        Disconnect(si)


def restore_snapshot(vm_identifier, snapshot_identifier):
    si = connect_esxi()

    try:
        vm = _get_vm_from_content(si.RetrieveContent(), vm_identifier)
        snapshot = _get_snapshot_from_vm(vm, snapshot_identifier)
        task = snapshot.RevertToSnapshot_Task()
        logger.info("Snapshot restore requested for VM %s", vm._moId)
        return serialize_task(task)
    finally:
        Disconnect(si)


def delete_snapshot(vm_identifier, snapshot_identifier):
    si = connect_esxi()

    try:
        vm = _get_vm_from_content(si.RetrieveContent(), vm_identifier)
        snapshot = _get_snapshot_from_vm(vm, snapshot_identifier)
        task = snapshot.RemoveSnapshot_Task(removeChildren=False)
        logger.info("Snapshot deletion requested for VM %s", vm._moId)
        return serialize_task(task)
    finally:
        Disconnect(si)


def power_vm(vm_id, action):

    si = connect_esxi()

    try:
        content = si.RetrieveContent()

        container = content.rootFolder

        vm = _get_vm_from_content(content, vm_id)

        power_state = str(vm.runtime.powerState)

        if action == "start":
            if power_state != "poweredOff":
                raise ValueError("Virtual machine is not powered off")

            task = vm.PowerOnVM_Task()

        elif action == "stop":
            if power_state != "poweredOn":
                raise ValueError("Virtual machine is not powered on")

            task = vm.PowerOffVM_Task()

        elif action == "restart":
            if power_state != "poweredOn":
                raise ValueError("Virtual machine is not powered on")

            task = vm.ResetVM_Task()

        else:
            raise ValueError("Invalid power action")

        return task.info.key

    finally:
        Disconnect(si)

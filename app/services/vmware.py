import ssl

from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim

from config import ESXI_HOST, ESXI_USERNAME, ESXI_PASSWORD


def connect_esxi():

    context = ssl._create_unverified_context()

    si = SmartConnect(
        host=ESXI_HOST,
        user=ESXI_USERNAME,
        pwd=ESXI_PASSWORD,
        sslContext=context
    )

    return si


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

        datastore = host.datastore[0]

        datastore_used = datastore.summary.capacity - datastore.summary.freeSpace

        datastore_percent = round(
            (datastore_used / datastore.summary.capacity) * 100,
            1
        )

        return {
            "cpu": cpu_percent,
            "memory": memory_percent,
            "datastore": datastore_percent
        }

    finally:
        Disconnect(si)


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

            power_state = str(vm.runtime.powerState)
            status = "🟢 Running"

            if power_state == "poweredOff":
                status = "🔴 Powered Off"
            elif power_state == "suspended":
                status = "🟡 Suspended"

            vms.append({
                "id": vm._moId,
                "name": vm.name,
                "status": status,
                "power_state": power_state
            })

        return sorted(vms, key=lambda x: x["name"].lower())

    finally:
        Disconnect(si)


def power_vm(vm_id, action):

    si = connect_esxi()

    try:
        content = si.RetrieveContent()
        vm = content.searchIndex.FindByMoId(vm_id)

        if vm is None or not isinstance(vm, vim.VirtualMachine):
            raise ValueError("Virtual machine not found")

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

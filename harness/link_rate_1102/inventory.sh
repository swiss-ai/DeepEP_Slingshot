#!/usr/bin/env bash
echo "host=$(hostname) date=$(date -u +%FT%TZ) kernel=$(uname -r)"
echo "cxi_write_bw: $(cxi_write_bw -V 2>&1 | head -1) pkg: $(rpm -qf /usr/bin/cxi_write_bw 2>/dev/null)"
echo "libcxi: $(rpm -qa 2>/dev/null | grep -i libcxi | tr '\n' ' ')"
echo "cxi driver: $(modinfo -F version cxi_core 2>/dev/null) ss: $(modinfo -F version cxi_ss1 2>/dev/null)"
for d in /sys/class/cxi/cxi*; do n=$(basename $d); echo "$n numa=$(cat $d/device/numa_node 2>/dev/null) fw=$(cat $d/device/fw_version 2>/dev/null) link=$(cat $d/device/properties/link 2>/dev/null) speed=$(cat $d/device/properties/speed 2>/dev/null) nid=$(cat $d/device/properties/nid 2>/dev/null)"; done
echo "SLINGSHOT_DEVICES=${SLINGSHOT_DEVICES:-} SLINGSHOT_SVC_IDS=${SLINGSHOT_SVC_IDS:-} SLINGSHOT_VNIS=${SLINGSHOT_VNIS:-}"
nvidia-smi --query-gpu=index,name,pci.bus_id --format=csv 2>&1 | head -6
nvidia-smi topo -m 2>&1 | head -12

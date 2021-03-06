"""
Copyright 2020 The Magma Authors.

This source code is licensed under the BSD-style license found in the
LICENSE file in the root directory of this source tree.

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Allocates IP address as per DHCP server in the uplink network.
"""
import datetime
import logging
import threading
import time
from typing import Optional, MutableMapping


from ipaddress import IPv4Network, ip_address
from scapy.all import AsyncSniffer
from scapy.layers.dhcp import BOOTP, DHCP
from scapy.layers.l2 import Ether
from scapy.layers.inet import IP, UDP
from scapy.sendrecv import sendp
from threading import Condition

from magma.mobilityd.mac import MacAddress, create_mac_from_sid
from magma.mobilityd.dhcp_desc import DHCPState, DHCPDescriptor
from magma.mobilityd.uplink_gw import UplinkGatewayInfo

LOG = logging.getLogger('mobilityd.dhcp.sniff')


class DHCPClient:
    THREAD_YIELD_TIME = .1

    def __init__(self,
                 dhcp_store: MutableMapping[str, DHCPDescriptor],
                 gw_info: UplinkGatewayInfo,
                 dhcp_wait: Condition,
                 iface: str = "dhcp0",
                 lease_renew_wait_min: int = 30):
        """
        Implement DHCP client to allocate IP for given Mac address.
        DHCP client state is maintained in user provided hash table.
        Args:
            dhcp_store: maintain DHCP transactions, key is mac address.
            gw_info_map: stores GW IP info from DHCP server
            dhcp_wait: notify users on new DHCP packet
            iface: DHCP egress and ingress interface.
        """
        self._sniffer = AsyncSniffer(iface=iface,
                                     filter="udp and (port 67 or 68)",
                                     prn=self._rx_dhcp_pkt)

        self.dhcp_client_state = dhcp_store  # mac => DHCP_State
        self.dhcp_gw_info = gw_info
        self._dhcp_notify = dhcp_wait
        self._dhcp_interface = iface
        self._msg_xid = 0
        self._lease_renew_wait_min = lease_renew_wait_min
        self._monitor_thread = threading.Thread(target=self._monitor_dhcp_state)
        self._monitor_thread.daemon = True
        self._monitor_thread_event = threading.Event()

    def run(self):
        """
        Start DHCP sniffer thread.
        This initializes state required for DHCP sniffer thread anf starts it.
        Returns: None
        """
        self._sniffer.start()
        LOG.info("DHCP sniffer started")
        # give it time to schedule the thread and start sniffing.
        time.sleep(self.THREAD_YIELD_TIME)
        self._monitor_thread.start()

    def stop(self):
        self._sniffer.stop()
        self._monitor_thread_event.set()

    def send_dhcp_packet(self, mac: MacAddress, state: DHCPState,
                         dhcp_desc: DHCPDescriptor = None):
        """
        Send DHCP packet and record state in dhcp_client_state.

        Args:
            mac: MAC address of interface
            state: state of DHCP packet
            dhcp_desc: DHCP protocol state.
        Returns:
        """
        ciaddr = None

        # generate DHCP request packet
        if state == DHCPState.DISCOVER:
            dhcp_opts = [("message-type", "discover")]
            dhcp_desc = DHCPDescriptor(mac=mac, ip="",
                                       state_requested=DHCPState.DISCOVER)
            self._msg_xid = self._msg_xid + 1
            pkt_xid = self._msg_xid
        elif state == DHCPState.REQUEST:
            dhcp_opts = [("message-type", "request"),
                         ("requested_addr", dhcp_desc.ip),
                         ("server_id", dhcp_desc.server_ip)]
            dhcp_desc.state_requested = DHCPState.REQUEST
            pkt_xid = dhcp_desc.xid
            ciaddr = dhcp_desc.ip
        elif state == DHCPState.RELEASE:
            dhcp_opts = [("message-type", "release"),
                         ("server_id", dhcp_desc.server_ip)]
            dhcp_desc.state_requested = DHCPState.RELEASE
            self._msg_xid = self._msg_xid + 1
            pkt_xid = self._msg_xid
            ciaddr = dhcp_desc.ip
        else:
            LOG.warning("Unknown egress request mac %s state %s", str(mac), state)
            return

        dhcp_opts.append("end")

        with self._dhcp_notify:
            self.dhcp_client_state[mac.as_redis_key()] = dhcp_desc

        pkt = Ether(src=str(mac), dst="ff:ff:ff:ff:ff:ff")
        pkt /= IP(src="0.0.0.0", dst="255.255.255.255")
        pkt /= UDP(sport=68, dport=67)
        pkt /= BOOTP(op=1, chaddr=mac.as_hex(), xid=pkt_xid, ciaddr=ciaddr)
        pkt /= DHCP(options=dhcp_opts)
        LOG.debug("DHCP pkt %s", pkt.show(dump=True))

        sendp(pkt, iface=self._dhcp_interface, verbose=0)

    def get_dhcp_desc(self, mac: MacAddress) -> Optional[DHCPDescriptor]:
        """
                Get DHCP description for given MAC.
        Args:
            mac: Mac address of the client

        Returns: Current DHCP info.
        """

        key = mac.as_redis_key()
        if key in self.dhcp_client_state:
            return self.dhcp_client_state[key]

        LOG.debug("lookup error for %s", str(mac))
        return None

    def release_ip_address(self, mac: MacAddress):
        """
                Release DHCP allocated IP.
        Args:
            mac: MAC address of the IP allocated.

        Returns: None
        """

        if mac.as_redis_key() not in self.dhcp_client_state:
            LOG.error("Unallocated DHCP release for MAC: %s", str(mac))
            return

        dhcp_desc = self.dhcp_client_state[mac.as_redis_key()]
        self.send_dhcp_packet(mac, DHCPState.RELEASE, dhcp_desc)

    def _monitor_dhcp_state(self):
        """
        monitor DHCP client state.
        """
        while True:
            wait_time = self._lease_renew_wait_min
            with self._dhcp_notify:
                for dhcp_record in self.dhcp_client_state.values():
                    # Only process active records.
                    if dhcp_record.state != DHCPState.ACK and \
                       dhcp_record.state != DHCPState.REQUEST:
                        continue
                    # ignore already released IPs.
                    if dhcp_record.state == DHCPState.RELEASE:
                        continue
                    now = datetime.datetime.now()
                    request_state = DHCPState.REQUEST
                    # in case of lost DHCP lease rediscover it.
                    if now >= dhcp_record.lease_expiration_time:
                        request_state = DHCPState.DISCOVER

                    if now >= dhcp_record.lease_renew_deadline:
                        logging.debug("sending lease renewal")
                        self.send_dhcp_packet(dhcp_record.mac, request_state, dhcp_record)
                    else:
                        time_to_renew = dhcp_record.lease_renew_deadline - now
                        wait_time = min(wait_time, time_to_renew.total_seconds())

            # default in wait is 30 sec
            wait_time = max(wait_time, self._lease_renew_wait_min)
            logging.debug("lease renewal check after: %s sec" % wait_time)
            self._monitor_thread_event.wait(wait_time)
            if self._monitor_thread_event.is_set():
                break

    @staticmethod
    def _get_option(packet, name):
        for opt in packet[DHCP].options:
            if opt[0] == name:
                return opt[1]
        return None

    def _process_dhcp_pkt(self, packet, state: DHCPState):
        mac_addr = create_mac_from_sid(packet[Ether].dst)
        mac_addr_key = mac_addr.as_redis_key()

        with self._dhcp_notify:
            if mac_addr_key in self.dhcp_client_state:
                state_requested = self.dhcp_client_state[mac_addr_key].state_requested
                ip_offered = packet[BOOTP].yiaddr
                subnet_mask = self._get_option(packet, "subnet_mask")
                if subnet_mask is not None:
                    ip_subnet = IPv4Network(ip_offered + "/" + subnet_mask, strict=False)
                else:
                    ip_subnet = None

                dhcp_router_opt = self._get_option(packet, "router")
                if dhcp_router_opt is not None:
                    router_ip_addr = ip_address(dhcp_router_opt)
                else:
                    router_ip_addr = None

                lease_expiration_time = self._get_option(packet, "lease_time")
                dhcp_state = DHCPDescriptor(mac=mac_addr,
                                             ip=ip_offered,
                                             state=state,
                                             state_requested=state_requested,
                                             subnet=str(ip_subnet),
                                             server_ip=packet[IP].src,
                                             router_ip=router_ip_addr,
                                             lease_expiration_time=lease_expiration_time,
                                             xid=packet[BOOTP].xid)
                LOG.info("Record mac %s IP %s", mac_addr_key, dhcp_state)

                self.dhcp_client_state[mac_addr_key] = dhcp_state

                self.dhcp_gw_info.update_ip(router_ip_addr)
                self._dhcp_notify.notifyAll()

                if state == DHCPState.OFFER:
                    #  let other thread work on fulfilling IP allocation request.
                    threading.Event().wait(self.THREAD_YIELD_TIME)
                    self.send_dhcp_packet(mac_addr, DHCPState.REQUEST, dhcp_state)
            else:
                LOG.debug("Unknown MAC: %s " % packet.summary())
                return

    # ref: https://fossies.org/linux/scapy/scapy/layers/dhcp.py
    def _rx_dhcp_pkt(self, packet):
        if DHCP not in packet:
            return

        LOG.debug("DHCP type %s", packet[DHCP].options[0][1])

        # Match DHCP offer
        if packet[DHCP].options[0][1] == int(DHCPState.OFFER):
            LOG.debug("Offer %s (%s) ", packet[IP].src, packet[Ether].src)
            self._process_dhcp_pkt(packet, DHCPState.OFFER)

        # Match DHCP ack
        elif packet[DHCP].options[0][1] == int(DHCPState.ACK):
            LOG.debug("Acked %s (%s) ", packet[IP].src, packet[Ether].src)
            self._process_dhcp_pkt(packet, DHCPState.ACK)

        # TODO handle other DHCP protocol events.

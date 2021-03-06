#!/usr/bin/env python3

"""

PyBGP, Python BGP implmentation version 0.1 - 2020, Sebastian Majewski
bgp_network_io.py - module containing FSM class mthods responsible for network communication with BGP peers

"""

import asyncio

import bgp_message
from bgp_event import BgpEvent


async def open_connection(self):
    """ Open TCP connection to the BGP peer """

    self.logger.opt(depth=0).debug("Opening connection to peer")
    try:
        reader, writer = await asyncio.open_connection(self.peer_ip, 179)
        self.enqueue_event(BgpEvent("Event 16: Tcp_CR_Acked", reader=reader, writer=writer, peer_ip=self.peer_ip, peer_port=179))

    except OSError:
        self.tcp_connection_established = False
        self.enqueue_event(BgpEvent("Event 18: TcpConnectionFails"))


def close_connection(self):
    """ Close TCP connection to the BGP peer """

    self.logger.opt(depth=1).debug("Closing connection to peer")

    if hasattr(self, "task_open_connection"):
        self.task_open_connection.cancel()

    if self.writer:
        self.writer.close()

    self.tcp_connection_established = False
    self.reader = None
    self.writer = None


async def send_keepalive_message(self):
    """ Send Keepalive message """

    if self.tcp_connection_established:
        message = bgp_message.Keepalive()

        try:
            self.writer.write(message.write())
            await self.writer.drain()

        except OSError:
            self.logger.opt(ansi=True, depth=1).info("<magenta>[TX-ERR]</magenta> Keepalive message")
            self.enqueue_event(BgpEvent("Event 18: TcpConnectionFails"))
            self.tcp_connection_established = False
            await asyncio.sleep(1)
            return

        self.logger.opt(ansi=True, depth=1).info("<magenta>[TX]</magenta> Keepalive message")

    else:
        self.logger.opt(ansi=True, depth=1).info("<magenta>[TX-ERR]</magenta> Keepalive message")


async def send_notification_message(self, error_code, error_subcode=0, data=b""):
    """ Send Notification message """

    if self.tcp_connection_established:
        message = bgp_message.Notification(error_code, error_subcode, data)

        try:
            self.writer.write(message.write())
            await self.writer.drain()

        except OSError:
            self.logger.opt(ansi=True, depth=1).info(f"<magenta>[TX-ERR]</magenta> Notification message ({error_code}, {error_subcode})")
            self.enqueue_event(BgpEvent("Event 18: TcpConnectionFails"))
            self.tcp_connection_established = False
            await asyncio.sleep(1)
            return

        self.logger.opt(ansi=True, depth=1).info(f"<magenta>[TX]</magenta> Notification message ({error_code}, {error_subcode})")

    else:
        self.logger.opt(ansi=True, depth=1).info(f"<magenta>[TX-ERR]</magenta> Notification message ({error_code}, {error_subcode})")


async def send_open_message(self):
    """ Send Open message """

    if self.tcp_connection_established:
        message = bgp_message.Open(local_id=self.local_id, local_asn=self.local_asn, local_hold_time=self.local_hold_time)

        try:
            self.writer.write(message.write())
            await self.writer.drain()

        except OSError:
            self.logger.opt(ansi=True, depth=1).info("<magenta>[TX-ERR]</magenta> Open message")
            self.enqueue_event(BgpEvent("Event 18: TcpConnectionFails"))
            self.tcp_connection_established = False
            await asyncio.sleep(1)
            return

        self.logger.opt(ansi=True, depth=1).info("<magenta>[TX]</magenta> Open message")

    else:
        self.logger.opt(ansi=True, depth=1).info("<magenta>[TX-ERR]</magenta> Open message")


async def send_update_message(self):
    """ Send Open message """

    # <!!!> Need valid implementation here
    pass


async def message_input_loop(self):
    """ Receive messages from the peer and add them to the input queue """

    self.logger.debug("Starting message input loop")

    while True:

        if self.tcp_connection_established is False:
            await asyncio.sleep(1)
            continue

        data = await self.reader.read(4096)
        self.logger.debug(f"Received {len(data)} bytes of data")

        if len(data) == 0:
            self.enqueue_event(BgpEvent("Event 18: TcpConnectionFails"))
            self.tcp_connection_established = False
            await asyncio.sleep(1)
            continue

        while len(data) >= 19:
            message = bgp_message.DecodeMessage(data, local_id=self.local_id, peer_asn=self.peer_asn)

            if message.data_length_error:
                self.logger.warning(f"Received {message.data_length_received} bytes of data, expected at least {message.data_length_expected}")
                self.tcp_connection_established = False
                self.enqueue_event(BgpEvent("Event 18: TcpConnectionFails"))
                await asyncio.sleep(1)
                break

            data = data[message.length:]

            if message.message_error_code == bgp_message.MESSAGE_HEADER_ERROR:
                self.enqueue_event(BgpEvent("Event 21: BGPHeaderErr", message))
                break

            if message.message_error_code == bgp_message.OPEN_MESSAGE_ERROR:
                self.enqueue_event(BgpEvent("Event 22: BGPOpenMsgErr", message))
                break

            if message.type == bgp_message.OPEN:
                self.logger.opt(ansi=True).info(f"<magenta>[RX]</magenta> Open message (peer_id: {message.id})")
                self.enqueue_event(BgpEvent("Event 19: BGPOpen", message))

            if message.type == bgp_message.UPDATE:
                self.logger.opt(ansi=True).info("<magenta>[RX]</magenta> Update message")
                # <!!!> Requires proper handler here

            if message.type == bgp_message.NOTIFICATION:
                self.logger.opt(ansi=True).info(f"<magenta>[RX]</magenta> Notification message ({message.error_code}, {message.error_subcode})")

                if message.error_code == bgp_message.MESSAGE_HEADER_ERROR:
                    self.enqueue_event(BgpEvent("Event 25: NotifMsg"))

                if message.error_code == bgp_message.OPEN_MESSAGE_ERROR and message.error_subcode == bgp_message.UNSUPPORTED_VERSION_NUMBER:
                    self.enqueue_event(BgpEvent("Event 24: NotifMsgVerErr"))

                if message.error_code == bgp_message.OPEN_MESSAGE_ERROR and message.error_subcode != bgp_message.UNSUPPORTED_VERSION_NUMBER:
                    self.enqueue_event(BgpEvent("Event 25: NotifMsg"))

                if message.error_code == bgp_message.UPDATE_MESSAGE_ERROR:
                    self.enqueue_event(BgpEvent("Event 25: NotifMsg"))

                if message.error_code == bgp_message.HOLD_TIMER_EXPIRED:
                    self.enqueue_event(BgpEvent("Event 25: NotifMsg"))

                if message.error_code == bgp_message.FINITE_STATE_MACHINE_ERROR:
                    self.enqueue_event(BgpEvent("Event 25: NotifMsg"))

                if message.error_code == bgp_message.CEASE:
                    self.enqueue_event(BgpEvent("Event 25: NotifMsg"))

            if message.type == bgp_message.KEEPALIVE:
                self.logger.opt(ansi=True).info("<magenta>[RX]</magenta> Keepalive message")
                self.enqueue_event(BgpEvent("Event 26: KeepAliveMsg"))

            await asyncio.sleep(1)

        else:
            await asyncio.sleep(1)

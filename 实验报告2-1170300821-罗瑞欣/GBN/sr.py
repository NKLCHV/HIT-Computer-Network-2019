import socket
import random
import select
import threading
import time

LENGTH_SEQUENCE = 256  # 序列号有效范围 0~255
RECEIVE_WINDOW = 5  # 接收窗口大小(SR协议中使用)
SEND_WINDOW = 5  # 发送窗口大小

MAX_TIMER = 3  # 计时器最大超时时间

PORT_CONFIG = [
    [("127.0.0.1", 12138), ("127.0.0.1", 12139)],
    [("127.0.0.1", 12140), ("127.0.0.1", 12141)]
]

BUFFER_SIZE = 2048  # 缓存大小


def make_pkt(next_seq_num, data):
    """数据帧格式
     SEQ' 'data
     """
    pkt_s = str(next_seq_num) + ' ' + str(data)
    return pkt_s.encode()


def make_ack_pkt(ack_num):
    """ACK帧格式
    ACK' 'ack_num
    """
    return ('ACK ' + str(ack_num)).encode()


class SRClient(object):
    SEND_PORT = 0
    RECEIVE_PORT = 1

    def __init__(self, client_name, config_id):
        self.client_name = client_name
        self.config_id = config_id
        self.target_id = 1 - config_id
        self.send_base = 0
        self.next_seq_num = 0
        self.receive_base = 0
        self.SEND_WINDOW = SEND_WINDOW  # 发送窗口大小
        self.RECEIVE_WINDOW = RECEIVE_WINDOW  # 接收窗口大小
        self.timer = [0] * LENGTH_SEQUENCE
        self.socket_1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_1.bind(PORT_CONFIG[self.config_id][SRClient.SEND_PORT])
        self.socket_2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_2.bind(PORT_CONFIG[self.config_id][SRClient.RECEIVE_PORT])
        self.data_seq = [b'0'] * LENGTH_SEQUENCE  # 作为已发送数据的缓存
        self.data_receive_seq = [0] * LENGTH_SEQUENCE  # 作为接收数据的缓存
        self.ack_seq = [False] * LENGTH_SEQUENCE  # 作为发送端窗口 确认ACK
        self.correct_receive = [False] * LENGTH_SEQUENCE  # 正确接收的包的序列

    def send(self):
        while self.next_seq_num <= (self.send_base + self.SEND_WINDOW) % LENGTH_SEQUENCE:
            pkt = make_pkt(self.next_seq_num, str(self.next_seq_num + LENGTH_SEQUENCE))
            self.ack_seq[self.next_seq_num] = False  # 将对应位置的ACK标志设为0
            self.timer[self.next_seq_num] = 0  # 重启即将发送分组的timer
            self.data_seq[self.next_seq_num] = pkt  # 将即将发送的包进行缓存
            self.socket_1.sendto(pkt, PORT_CONFIG[self.target_id][SRClient.RECEIVE_PORT])
            print("Client Send", str(pkt)[2:-4])
            self.next_seq_num += 1

        self.next_seq_num %= LENGTH_SEQUENCE  # 此处直接+1时取模 是为了避免特殊情况最后一个序号无法发送

        readable, writeable, errors = select.select([self.socket_1, ], [], [], 1)
        if len(readable) > 0:
            mgs_byte, address = self.socket_1.recvfrom(BUFFER_SIZE)
            message = mgs_byte.decode()
            if 'ACK' in message:  # 如果收到ACK
                messages = message.split()
                receive_ack_num = int(messages[1])
                if self.send_base <= receive_ack_num < self.next_seq_num:
                    # 在已发送的包中
                    # print("Client Receive", message)
                    print("Client Receive", str(message))
                    self.ack_seq[receive_ack_num] = True
                    self.timer[receive_ack_num] = -1  # 可能无需置为-1
                temp_send_base = self.send_base
                if receive_ack_num == self.send_base:
                    # 如果收到ACK分组的序号等于send_base 则移动窗口至具有最小序号的未确认分组处
                    for i in range(self.send_base,
                                   self.next_seq_num if self.next_seq_num > self.send_base
                                   else self.next_seq_num + LENGTH_SEQUENCE):
                        if self.ack_seq[i % LENGTH_SEQUENCE]:
                            temp_send_base = i % LENGTH_SEQUENCE
                        else:
                            break
                    self.send_base = (temp_send_base + 1) % LENGTH_SEQUENCE
        else:
            # 如果没有收到ACK报文 则将所有已发送但未确认的分组的计时器全部+1
            for i in range(self.send_base,
                           self.next_seq_num if self.next_seq_num > self.send_base
                           else self.next_seq_num + LENGTH_SEQUENCE):
                index = i % LENGTH_SEQUENCE
                if not self.ack_seq[index]:
                    self.timer[index] += 1
                    if self.timer[index] > MAX_TIMER:
                        # 如果某个分组的计时器超时 则重新发送对应的分组并且重启计时器
                        print("Client Timer", index, "out, Resend")
                        self.socket_1.sendto(self.data_seq[index], PORT_CONFIG[self.target_id][SRClient.RECEIVE_PORT])
                        self.timer[index] = 0

    def begin_send(self):
        while True:
            self.send()

    # 接收方 事件

    # 序号在[rcv_base, rcv_base + N - 1]
    # 内的分组被正确接收。在此情况下，收到的分组落在接收方的窗口内，一个选择 ACK
    # 被回送给发送方。如果该分组以前没收到过，则缓存该分组。如果该分组的序号等于接收端的基序号（rcv_base），
    # 则该分组以及以前缓存的序号连续的（起始于 rcv_base的）分组交付给上层。然后，接收窗口按向前移动分组的编号向上交付这些分组。

    # 序号在[rcv_base - N, rcv_base - 1]内的分组被正确收到。在此情况下，必须产生一个ACK，即使该分组是接收方以前确认过的分组。

    # 其他情况。忽略该分组。
    def receive(self, throw):
        time.sleep(random.random())  # 用于测试时模拟网络延迟
        readable, writable, errors = select.select([self.socket_2, ], [], [], 1)
        if len(readable) > 0:
            mgs_byte, address = self.socket_2.recvfrom(BUFFER_SIZE)
            messages = mgs_byte.decode().split()
            pkt_num = int(messages[0])
            if self.receive_base <= pkt_num <= (self.receive_base + self.RECEIVE_WINDOW - 1) % LENGTH_SEQUENCE:
                if self.correct_receive[pkt_num]:
                    # 如果已经正确接收该分组 重发ACK
                    print("Client Has Received", mgs_byte, "Resend ACK", pkt_num)
                    self.socket_2.sendto(make_ack_pkt(pkt_num), PORT_CONFIG[self.target_id][SRClient.SEND_PORT])
                else:
                    # 如果在接收窗口内但从未正确接收 缓存并发送ACK
                    self.correct_receive[pkt_num] = True
                    self.data_seq[pkt_num] = mgs_byte
                    # time.sleep(random.uniform(0, 1))    # 模拟丢包延时
                    if throw:
                        if random.randint(0, 1) == 0:  # 以50%概率发送ACK
                            self.socket_2.sendto(make_ack_pkt(pkt_num), PORT_CONFIG[self.target_id][SRClient.SEND_PORT])
                            print("Client Received", str(mgs_byte)[2:-4], "Send ACK", pkt_num)
                    else:
                        self.socket_2.sendto(make_ack_pkt(pkt_num), PORT_CONFIG[self.target_id][SRClient.SEND_PORT])
                        print("Client Received",str(mgs_byte)[2:-4], "Send ACK", pkt_num)
                    temp_receive_base = self.receive_base
                    if pkt_num == self.receive_base:
                        # 如果接收到的是窗口的第一个 此时向上层上交自base开始的已经缓存的分组
                        # 将窗口向右移动
                        for i in range(self.receive_base,
                                       (self.receive_base + self.RECEIVE_WINDOW - 1) % LENGTH_SEQUENCE
                                       if (self.receive_base + self.RECEIVE_WINDOW - 1)
                                          % LENGTH_SEQUENCE > self.receive_base
                                       else self.receive_base + self.RECEIVE_WINDOW - 1):
                            index = i % LENGTH_SEQUENCE
                            if self.correct_receive[index]:
                                temp_receive_base = index
                                self.correct_receive[index] = False
                                self.data_receive_seq[index] = 0
                            else:
                                break
                        self.receive_base = (temp_receive_base + 1) % LENGTH_SEQUENCE
            elif (self.receive_base - self.RECEIVE_WINDOW - 1) <= pkt_num <= (self.receive_base - 1):
                # 如果在[rev_base - N, rev_base - 1]内的分组正确到达 重新发送ACK
                # 此处与书上的SR略有不同 对于下界
                self.socket_2.sendto(make_ack_pkt(pkt_num), PORT_CONFIG[self.target_id][SRClient.SEND_PORT])
                print("Client Has Received", str(mgs_byte)[2:-4], "Resend ACK", pkt_num)

    def begin_receive(self):
        while True:
            # self.receive(False)
            self.receive(True)


def sr():
    client = SRClient('CLIENT', 0)
    server = SRClient('SERVER', 1)
    threading.Thread(target=client.begin_send).start()
    threading.Thread(target=client.begin_receive).start()
    time.sleep(2)
    threading.Thread(target=client.begin_send).start()
    threading.Thread(target=server.begin_receive).start()



if __name__ == '__main__':
    sr()

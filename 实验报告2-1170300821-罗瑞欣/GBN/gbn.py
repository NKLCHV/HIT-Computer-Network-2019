import socket
import random
import select
import threading
import time

LENGTH_SEQUENCE = 256  # 序列号有效范围 0~255
RECEIVE_WINDOW = 128  # 接收窗口大小(SR协议中使用)
# 当GBN窗口长度为1的时候 就是停等协议i
SEND_WINDOW = 5  # 发送窗口大小

MAX_TIMER = 3  # 计时器最大超时时间

LOSS_CYCLE = 3

PORT_CONFIG = [
    [("127.0.0.1", 12138), ("127.0.0.1", 12139)],
    [("127.0.0.1", 12140), ("127.0.0.1", 12141)]
]

# SERVER_PORT_1 = 12138
# SERVER_PORT_2 = 12139
#
# CLIENT_PORT_1 = 12140
# CLIENT_PORT_2 = 12141
#
# SERVER_IP = '127.0.0.1'
# CLIENT_IP = '127.0.0.1'

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


class GBNClient(object):
    SEND_PORT = 0
    RECEIVE_PORT = 1

    def __init__(self, client_name, config_id):
        self.client_name = client_name
        self.config_id = config_id
        self.target_config_id = 1 - config_id
        self.base = 0
        self.next_seq_num = 0
        self.expected_seq_num = 0
        self.SEND_WINDOW = SEND_WINDOW
        self.timer = 0
        # 建立 Client的发送以及接受线程
        # SOCK_DGRAM 代表发送使用UDP协议
        self.socket_1 = socket
        self.socket_1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_1.bind(PORT_CONFIG[self.config_id][GBNClient.SEND_PORT])
        self.socket_2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_2.bind(PORT_CONFIG[self.config_id][GBNClient.RECEIVE_PORT])
        self.data_send_seq = [b'0'] * LENGTH_SEQUENCE
        self.data_receive_seq = [b'0'] * LENGTH_SEQUENCE

        self.recv_count = 0
        self.init_flag = True

    def timeout(self):
        print("{0} : timeout".format(self.client_name))
        # 发送数据超时 重发数据
        self.timer = 0
        for i in range(self.base,
                       self.next_seq_num if self.next_seq_num > self.base
                       else self.next_seq_num + LENGTH_SEQUENCE):
            # 用于序列号使用的处理
            self.socket_1.sendto(self.data_send_seq[i % LENGTH_SEQUENCE],
                                 PORT_CONFIG[self.target_config_id][GBNClient.RECEIVE_PORT])
            print("{0} : resend".format(self.client_name), str(self.data_send_seq[i % LENGTH_SEQUENCE])[2:-4])

    def send(self):
        # 发送所有处于发送窗口中的数据包
        while self.next_seq_num <= (self.base + self.SEND_WINDOW) % LENGTH_SEQUENCE:
            # 模拟构造数据
            pkt = make_pkt(self.next_seq_num, str(self.next_seq_num + LENGTH_SEQUENCE))
            if self.next_seq_num == self.base:
                # 如果 next_seq_num 之前的已经全部确认，此时重新启动计时器
                self.timer = 0
            self.socket_1.sendto(pkt, PORT_CONFIG[self.target_config_id][GBNClient.RECEIVE_PORT])
            print("{0} : send".format(self.client_name), self.next_seq_num)
            self.data_send_seq[self.next_seq_num] = pkt
            self.next_seq_num = self.next_seq_num + 1

        self.next_seq_num = self.next_seq_num % LENGTH_SEQUENCE
        if self.init_flag:
            self.init_flag = False
            print('Waiting ... ')
            time.sleep(2)
        # Python 的 select() 函数是部署底层操作系统的直接接口。
        # 它监视着套接字，打开的文件和管道（任何调用 fileno() 方法后会返回有效文件描述符的东西）直到它们变得可读可写或有错误发生。
        # select() 让我们同时监视多个连接变得简单，同时比在 Python 中使用套接字超时写轮询池要有效，因为这些监视发生在操作系统网络层而不是在解释器层。
        readable, writeable, errors = select.select([self.socket_1, ], [], [], 1)
        # 非阻塞方式
        if len(readable) > 0:
            mgs_byte, address = self.socket_1.recvfrom(BUFFER_SIZE)
            message = mgs_byte.decode()
            if 'ACK' in message:
                # 收到确认ACK
                messages = message.split()
                print("{0} : receive".format(self.client_name), message)
                # 采用累积确认，返回的ACK_num及其之前的包都已经被收到
                self.base = (int(messages[1]) + 1) % LENGTH_SEQUENCE
                # 如果已经收到base及其之前的所有包则停止计时器 stop_timer
                if self.base == self.next_seq_num:
                    self.timer = -1
                # 此时base改变，重新启动计时器 start_timer
                else:
                    self.timer = 0
        else:
            # 如果没有收到ACK 则将定时器加1
            self.timer += 1
            if self.timer > MAX_TIMER:
                self.timeout()

    def begin_send(self):
        while True:
            self.send()

    def receive(self, throw):
        # 用于测试时观察 模拟网络延迟
        time.sleep(random.random())
        # 监听timeout情况
        readable, writeable, errors = select.select([self.socket_2, ], [], [], 1)
        if len(readable) > 0:
            self.recv_count = self.recv_count + 1
            if throw:
                if self.recv_count % LOSS_CYCLE:
                    return
            mgs_byte, address = self.socket_2.recvfrom(BUFFER_SIZE)
            message = mgs_byte.decode().split()
            # message第一位为序列号，第二位为信息
            if int(message[0]) == self.expected_seq_num:
                self.data_receive_seq[self.expected_seq_num] = message[1]
                ack_pkt = make_ack_pkt(self.expected_seq_num - 1)
                # 发送ack到目标
                self.socket_2.sendto(ack_pkt, PORT_CONFIG[self.target_config_id][GBNClient.SEND_PORT])
                print("{0} : send ACK".format(self.client_name), self.expected_seq_num)
                self.expected_seq_num = (self.expected_seq_num + 1) % LENGTH_SEQUENCE
            else:
                # 序号失序，发送预期的序列号
                ack_pkt = make_ack_pkt(self.expected_seq_num - 1)
                self.socket_2.sendto(ack_pkt, PORT_CONFIG[self.target_config_id][GBNClient.SEND_PORT])
                print("{0} : resend ACK".format(self.client_name), self.expected_seq_num)

    def begin_receive(self):
        while True:
            self.receive(False)

    def begin_receice_with_throw(self):
        while True:
            self.receive(True)


def loss_gbn():
    global LOSS_CYCLE
    LOSS_CYCLE = 10
    client = GBNClient('CLIENT', 0)
    server = GBNClient('SERVER', 1)
    threading.Thread(target=client.begin_send).start()
    time.sleep(2)
    threading.Thread(target=server.begin_receice_with_throw).start()


def gbn():
    client = GBNClient('CLIENT', 0)
    server = GBNClient('SERVER', 1)
    threading.Thread(target=client.begin_send).start()
    threading.Thread(target=client.begin_receice_with_throw).start()
    time.sleep(2)
    threading.Thread(target=server.begin_send).start()
    threading.Thread(target=server.begin_receice_with_throw).start()


if __name__ == '__main__':
    # loss_gbn()
    gbn()
